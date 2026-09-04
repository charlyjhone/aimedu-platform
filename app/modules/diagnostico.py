"""
Módulo do AIM.Edu: Diagnóstico Adaptativo (multi-disciplina).

Lógica adaptativa (staircase simples, sem depender de IA externa):
  - Começa na dificuldade 3 (de 1 a 5).
  - Acertou -> sobe 1 nível (até 5). Errou -> desce 1 nível (até 1).
  - 10 questões por diagnóstico, sem repetir item.
  - Nível final = média das dificuldades das duas últimas questões
    respondidas corretamente, ponderada pelo histórico — aqui simplificado
    para a média das dificuldades apresentadas nas últimas 3 questões.

Esse motor é independente da camada de IA (app.ai_engine) — a IA entra só
na hora de transformar o resultado numérico em texto para a família/coordenação.
Isso é o que permite religar este módulo com "IA de verdade" no futuro sem
reescrever a lógica adaptativa.

Loop de validação do professor: o diagnóstico que resultado() finaliza aqui
nasce com status "aguardando_revisao" (default do schema — ver app/db.py) e
o aluno já vê o próprio resultado na hora. Mas ele só conta como oficial
para os painéis da coordenação e o relatório da família depois que o
professor da disciplina revisa e confirma (podendo ajustar o nível) em
app.modules.coordenador_professores.revisar_diagnostico().

Nasceu só para Matemática, mas o schema (itens_banco.disciplina,
diagnosticos.disciplina) sempre foi genérico — a única coisa hardcoded era
este módulo, com rotas fixas em /diagnostico/matematica. Agora a disciplina é
parte da URL (/diagnostico/<disciplina>/...) e a lista de disciplinas
disponíveis vem direto do banco de itens: para dar Diagnóstico Adaptativo a
uma disciplina nova, basta cadastrar itens em itens_banco com aquele slug —
nenhuma rota nova precisa ser escrita. Hoje existem bancos de Matemática e
Português (ver seed_data.py); o rótulo de exibição de cada slug fica em
app.ai_engine.NOMES_DISCIPLINA.
"""
import json
from datetime import datetime, timezone
from flask import Blueprint, render_template, redirect, url_for, session, flash, request

from ..db import get_db, new_id
from ..auth import login_obrigatorio, usuario_logado
from ..ai_engine import resumo_diagnostico, NOMES_DISCIPLINA

bp = Blueprint("diagnostico", __name__, url_prefix="/diagnostico")

TOTAL_QUESTOES = 10
DIFICULDADE_INICIAL = 3


def _aluno_atual(db):
    u = usuario_logado()
    return db.execute("select * from alunos where usuario_id = ?", (u["id"],)).fetchone()


def _disciplinas_disponiveis(db):
    """Disciplinas com pelo menos 1 item cadastrado no banco de itens — é
    isso que decide o que aparece para o aluno escolher."""
    linhas = db.execute("select distinct disciplina from itens_banco order by disciplina").fetchall()
    return [linha["disciplina"] for linha in linhas]


@bp.route("/")
@login_obrigatorio(papeis=["aluno"])
def index():
    db = get_db()
    aluno = _aluno_atual(db)
    disciplinas = _disciplinas_disponiveis(db)
    feitos_por_disciplina = {}
    if aluno:
        feitos = db.execute(
            "select disciplina, count(*) c from diagnosticos "
            "where aluno_id = ? and finalizado_em is not null group by disciplina",
            (aluno["id"],),
        ).fetchall()
        feitos_por_disciplina = {f["disciplina"]: f["c"] for f in feitos}
    return render_template(
        "diagnostico_index.html", disciplinas=disciplinas, feitos_por_disciplina=feitos_por_disciplina
    )


@bp.route("/<disciplina>/iniciar", methods=["GET", "POST"])
@login_obrigatorio(papeis=["aluno"])
def iniciar(disciplina):
    db = get_db()
    if disciplina not in _disciplinas_disponiveis(db):
        flash("Ainda não há Diagnóstico Adaptativo cadastrado para essa disciplina.", "erro")
        return redirect(url_for("diagnostico.index"))

    aluno = _aluno_atual(db)
    if not aluno:
        flash("Cadastro de aluno não encontrado.", "erro")
        return redirect(url_for("auth.painel"))

    diag_id = new_id()
    db.execute(
        "insert into diagnosticos (id, aluno_id, disciplina) values (?,?,?)",
        (diag_id, aluno["id"], disciplina),
    )
    db.commit()

    session["diagnostico"] = {
        "id": diag_id,
        "aluno_id": aluno["id"],
        "disciplina": disciplina,
        "num": 0,
        "dificuldade": DIFICULDADE_INICIAL,
        "vistos": [],
        "historico_dificuldade": [],
        "acertos": 0,
        "por_eixo": {},  # eixo -> [acertos, total]
    }
    return redirect(url_for("diagnostico.questao", disciplina=disciplina))


def _clausula_exclusao(vistos):
    if not vistos:
        return "", ()
    return f"and id not in ({','.join('?' * len(vistos))})", tuple(vistos)


def _proximo_item(db, disciplina, dificuldade, vistos):
    exclui_sql, exclui_params = _clausula_exclusao(vistos)
    q = db.execute(
        "select * from itens_banco where disciplina = ? and dificuldade = ? "
        f"{exclui_sql} order by random() limit 1",
        (disciplina, dificuldade, *exclui_params),
    ).fetchone()
    if q:
        return q
    # fallback: relaxa a dificuldade exata se o banco não tiver item suficiente
    for delta in (1, -1, 2, -2):
        alt = db.execute(
            "select * from itens_banco where disciplina = ? and dificuldade = ? "
            f"{exclui_sql} order by random() limit 1",
            (disciplina, max(1, min(5, dificuldade + delta)), *exclui_params),
        ).fetchone()
        if alt:
            return alt
    return None


def _diag_da_sessao(disciplina):
    diag = session.get("diagnostico")
    if not diag or diag.get("disciplina") != disciplina:
        return None
    return diag


@bp.route("/<disciplina>/questao", methods=["GET"])
@login_obrigatorio(papeis=["aluno"])
def questao(disciplina):
    diag = _diag_da_sessao(disciplina)
    if not diag:
        return redirect(url_for("diagnostico.iniciar", disciplina=disciplina))
    if diag["num"] >= TOTAL_QUESTOES:
        return redirect(url_for("diagnostico.resultado", disciplina=disciplina))

    db = get_db()
    item = _proximo_item(db, disciplina, diag["dificuldade"], diag["vistos"])
    if item is None:
        flash("Banco de itens insuficiente para continuar o diagnóstico — adicione mais questões.", "erro")
        return redirect(url_for("auth.painel"))

    diag["vistos"].append(item["id"])
    session["diagnostico"] = diag
    session["item_atual"] = item["id"]
    session.modified = True

    # SQLite guarda "alternativas" como texto (precisa de json.loads); o driver
    # do Postgres já decodifica a coluna jsonb direto para lista/dict.
    raw_alternativas = item["alternativas"]
    alternativas = json.loads(raw_alternativas) if isinstance(raw_alternativas, str) else raw_alternativas
    return render_template(
        "diagnostico_questao.html",
        item=item,
        disciplina=disciplina,
        alternativas=alternativas,
        numero=diag["num"] + 1,
        total=TOTAL_QUESTOES,
        dificuldade=diag["dificuldade"],
    )


@bp.route("/<disciplina>/responder", methods=["POST"])
@login_obrigatorio(papeis=["aluno"])
def responder(disciplina):
    diag = _diag_da_sessao(disciplina)
    if not diag:
        return redirect(url_for("diagnostico.iniciar", disciplina=disciplina))

    db = get_db()
    item_id = session.get("item_atual")
    item = db.execute("select * from itens_banco where id = ?", (item_id,)).fetchone()
    resposta = request.form.get("resposta", "")
    correta = (resposta == item["correta"])

    db.execute(
        "insert into diagnostico_respostas "
        "(id, diagnostico_id, item_id, ordem, dificuldade_apresentada, resposta_dada, correta) "
        "values (?,?,?,?,?,?,?)",
        (new_id(), diag["id"], item_id, diag["num"] + 1, diag["dificuldade"], resposta, correta),
    )
    db.commit()

    eixo = item["eixo_bncc"] or "geral"
    par = diag["por_eixo"].get(eixo, [0, 0])
    par[1] += 1
    if correta:
        par[0] += 1
    diag["por_eixo"][eixo] = par

    diag["historico_dificuldade"].append(diag["dificuldade"])
    if correta:
        diag["acertos"] += 1
        diag["dificuldade"] = min(5, diag["dificuldade"] + 1)
    else:
        diag["dificuldade"] = max(1, diag["dificuldade"] - 1)
    diag["num"] += 1
    session["diagnostico"] = diag
    session.modified = True

    return render_template(
        "diagnostico_feedback.html",
        disciplina=disciplina,
        correta=correta,
        explicacao=item["explicacao"],
        correta_letra=item["correta"],
        numero=diag["num"],
        total=TOTAL_QUESTOES,
    )


@bp.route("/<disciplina>/resultado")
@login_obrigatorio(papeis=["aluno"])
def resultado(disciplina):
    diag = _diag_da_sessao(disciplina)
    if not diag:
        return redirect(url_for("diagnostico.iniciar", disciplina=disciplina))

    db = get_db()
    ultimas = diag["historico_dificuldade"][-3:] or [DIFICULDADE_INICIAL]
    nivel_final = sum(ultimas) / len(ultimas)
    por_eixo_taxa = {eixo: (a / t if t else 0) for eixo, (a, t) in diag["por_eixo"].items()}

    nome_disciplina = NOMES_DISCIPLINA.get(disciplina, disciplina.capitalize())
    resumo = resumo_diagnostico(nome_disciplina, diag["acertos"], TOTAL_QUESTOES, nivel_final, por_eixo_taxa)

    # Timestamp calculado em Python (não com datetime('now')/now() do banco) para
    # funcionar igual em SQLite e Postgres, sem depender da função específica de cada um.
    agora = datetime.now(timezone.utc).isoformat()
    db.execute(
        "update diagnosticos set finalizado_em = ?, nivel_final = ?, resumo_ia = ? where id = ?",
        (agora, nivel_final, resumo, diag["id"]),
    )
    db.commit()

    # Gera automaticamente um alerta para a coordenação se o desempenho for baixo —
    # é aqui que o módulo "conversa" com o Radar da Coordenação, ainda no mesmo banco.
    if diag["acertos"] / TOTAL_QUESTOES < 0.4:
        aluno = db.execute("select * from alunos where id = ?", (diag["aluno_id"],)).fetchone()
        db.execute(
            "insert into alertas_radar (id, turma_id, aluno_id, nivel, motivo, diagnostico_id) values (?,?,?,?,?,?)",
            (new_id(), aluno["turma_id"], aluno["id"], "alto",
             f"Diagnóstico adaptativo de {nome_disciplina} com {diag['acertos']}/{TOTAL_QUESTOES} acertos "
             f"(nível {nivel_final:.1f}/5).", diag["id"]),
        )
        db.commit()

    resultado_view = {
        "disciplina": disciplina,
        "acertos": diag["acertos"],
        "total": TOTAL_QUESTOES,
        "nivel_final": round(nivel_final, 1),
        "por_eixo": por_eixo_taxa,
        "resumo": resumo,
    }
    session.pop("diagnostico", None)
    session.pop("item_atual", None)
    return render_template("diagnostico_resultado.html", r=resultado_view)
