"""
Módulo 1 do AIM.Edu: Diagnóstico Adaptativo de Matemática (foco ENEM).

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
"""
import json
from datetime import datetime, timezone
from flask import Blueprint, render_template, redirect, url_for, session, flash

from ..db import get_db, new_id
from ..auth import login_obrigatorio, usuario_logado
from ..ai_engine import resumo_diagnostico

bp = Blueprint("diagnostico_matematica", __name__, url_prefix="/diagnostico/matematica")

TOTAL_QUESTOES = 10
DIFICULDADE_INICIAL = 3


def _aluno_atual(db):
    u = usuario_logado()
    return db.execute("select * from alunos where usuario_id = ?", (u["id"],)).fetchone()


@bp.route("/iniciar", methods=["GET", "POST"])
@login_obrigatorio(papeis=["aluno"])
def iniciar():
    db = get_db()
    aluno = _aluno_atual(db)
    if not aluno:
        flash("Cadastro de aluno não encontrado.", "erro")
        return redirect(url_for("auth.painel"))

    diag_id = new_id()
    db.execute(
        "insert into diagnosticos (id, aluno_id, disciplina) values (?,?,?)",
        (diag_id, aluno["id"], "matematica"),
    )
    db.commit()

    session["diagnostico"] = {
        "id": diag_id,
        "aluno_id": aluno["id"],
        "num": 0,
        "dificuldade": DIFICULDADE_INICIAL,
        "vistos": [],
        "historico_dificuldade": [],
        "acertos": 0,
        "por_eixo": {},  # eixo -> [acertos, total]
    }
    return redirect(url_for("diagnostico_matematica.questao"))


def _clausula_exclusao(vistos):
    if not vistos:
        return "", ()
    return f"and id not in ({','.join('?' * len(vistos))})", tuple(vistos)


def _proximo_item(db, dificuldade, vistos):
    exclui_sql, exclui_params = _clausula_exclusao(vistos)
    q = db.execute(
        "select * from itens_banco where disciplina = 'matematica' and dificuldade = ? "
        f"{exclui_sql} order by random() limit 1",
        (dificuldade, *exclui_params),
    ).fetchone()
    if q:
        return q
    # fallback: relaxa a dificuldade exata se o banco não tiver item suficiente
    for delta in (1, -1, 2, -2):
        alt = db.execute(
            "select * from itens_banco where disciplina = 'matematica' and dificuldade = ? "
            f"{exclui_sql} order by random() limit 1",
            (max(1, min(5, dificuldade + delta)), *exclui_params),
        ).fetchone()
        if alt:
            return alt
    return None


@bp.route("/questao", methods=["GET"])
@login_obrigatorio(papeis=["aluno"])
def questao():
    diag = session.get("diagnostico")
    if not diag:
        return redirect(url_for("diagnostico_matematica.iniciar"))
    if diag["num"] >= TOTAL_QUESTOES:
        return redirect(url_for("diagnostico_matematica.resultado"))

    db = get_db()
    item = _proximo_item(db, diag["dificuldade"], diag["vistos"])
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
        alternativas=alternativas,
        numero=diag["num"] + 1,
        total=TOTAL_QUESTOES,
        dificuldade=diag["dificuldade"],
    )


@bp.route("/responder", methods=["POST"])
@login_obrigatorio(papeis=["aluno"])
def responder():
    from flask import request

    diag = session.get("diagnostico")
    if not diag:
        return redirect(url_for("diagnostico_matematica.iniciar"))

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
        correta=correta,
        explicacao=item["explicacao"],
        correta_letra=item["correta"],
        numero=diag["num"],
        total=TOTAL_QUESTOES,
    )


@bp.route("/resultado")
@login_obrigatorio(papeis=["aluno"])
def resultado():
    diag = session.get("diagnostico")
    if not diag:
        return redirect(url_for("diagnostico_matematica.iniciar"))

    db = get_db()
    ultimas = diag["historico_dificuldade"][-3:] or [DIFICULDADE_INICIAL]
    nivel_final = sum(ultimas) / len(ultimas)
    por_eixo_taxa = {eixo: (a / t if t else 0) for eixo, (a, t) in diag["por_eixo"].items()}

    resumo = resumo_diagnostico("matemática", diag["acertos"], TOTAL_QUESTOES, nivel_final, por_eixo_taxa)

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
            "insert into alertas_radar (id, turma_id, aluno_id, nivel, motivo) values (?,?,?,?,?)",
            (new_id(), aluno["turma_id"], aluno["id"], "alto",
             f"Diagnóstico adaptativo de matemática com {diag['acertos']}/{TOTAL_QUESTOES} acertos (nível {nivel_final:.1f}/5)."),
        )
        db.commit()

    resultado_view = {
        "acertos": diag["acertos"],
        "total": TOTAL_QUESTOES,
        "nivel_final": round(nivel_final, 1),
        "por_eixo": por_eixo_taxa,
        "resumo": resumo,
    }
    session.pop("diagnostico", None)
    session.pop("item_atual", None)
    return render_template("diagnostico_resultado.html", r=resultado_view)
