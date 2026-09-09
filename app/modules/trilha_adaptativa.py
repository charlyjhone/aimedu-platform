"""
Módulo do AIM.Edu: Trilha Adaptativa (ensino adaptativo por habilidade).

Diferença para o Diagnóstico Adaptativo (app/modules/diagnostico.py): aquele
é um teste único de nivelamento (10 questões, sobe/desce dificuldade, gera
uma nota final e acaba). Esta Trilha é contínua — não tem "início e fim", o
aluno entra quantas vezes quiser e ela sempre retoma de onde parou.

Lógica (MVP aprovado pelo usuário em 2026-09-09 — versão enxuta da visão
completa do documento "Módulo de Excelência em Matemática ENEM" no Drive do
projeto, sem os componentes de Otimizador de Ganho Marginal, Gêmeo
Estatístico, Simulados Semanais com correção TRI e Simulador de Trajetória
de Ranking, todos adiados para uma fase futura):

  1. Cada item do banco (itens_banco) pode ter uma 'habilidade' — mais fina
     que 'disciplina' (ex.: não só "matemática", mas "juros compostos") — e
     uma 'prioridade' inteira. As duas colunas são preenchidas à mão pela
     coordenação/professor no cadastro da questão: a IA nunca inventa essa
     prioridade a partir de estatística de incidência no ENEM — não temos
     dado real de frequência por edição, e o projeto tem o princípio de
     nunca inventar dado (ver Agente 1 em app/agents/agente.py). Item sem
     habilidade preenchida simplesmente não entra na Trilha — continua
     servindo normalmente o Diagnóstico Adaptativo, que não usa esse campo.
  2. Para cada aluno, a Trilha escolhe a habilidade de maior prioridade
     (dentre as disponíveis na disciplina) que ele ainda não "domina",
     manda uma questão daquela habilidade, e registra o resultado em
     dominio_habilidades (uma linha por aluno+disciplina+habilidade).
  3. "Domina" = acertar STREAK_DOMINIO questões seguidas daquela habilidade
     (qualquer erro zera a sequência). O documento de origem pede "8 de 10
     últimas tentativas, com tempo de resolução estável"; aqui simplificado
     para uma sequência direta de acertos, sem medir tempo de resolução,
     como primeira versão testável — mesmo espírito de simplificação do
     staircase do Diagnóstico Adaptativo (que também é uma versão mais
     simples do que uma calibração adaptativa completa).
  4. Assim que domina uma habilidade, a próxima chamada de /questao já
     escolhe automaticamente a próxima de maior prioridade ainda não
     dominada — não existe tela de "escolher habilidade", o aluno só aperta
     "praticar" e a Trilha decide.

Restrita ao Ensino Médio, mesmo padrão de dupla defesa (menu + guarda de
rota) já usado em app/modules/redacao.py — é lá que a visão do projeto situa
esse módulo ("módulo adaptativo do ensino médio").
"""
import json
from datetime import datetime, timezone

from flask import Blueprint, render_template, redirect, url_for, session, flash, request

from ..db import get_db, new_id
from ..auth import login_obrigatorio, usuario_logado
from ..ai_engine import NOMES_DISCIPLINA
from .calendario import _segmento_do_usuario

bp = Blueprint("trilha_adaptativa", __name__, url_prefix="/trilha")

STREAK_DOMINIO = 5  # acertos seguidos pra considerar uma habilidade dominada


def _aluno_atual(db):
    u = usuario_logado()
    return db.execute("select * from alunos where usuario_id = ?", (u["id"],)).fetchone()


def _bloqueio_se_nao_medio(db):
    """Trilha Adaptativa é só para o Ensino Médio — mesmo padrão de
    app/modules/redacao.py:_bloqueio_se_nao_medio (ver docstring lá)."""
    u = usuario_logado()
    if _segmento_do_usuario(db, u) != "medio":
        flash("A Trilha Adaptativa está disponível apenas para o Ensino Médio.", "erro")
        return redirect(url_for("auth.painel"))
    return None


def _disciplinas_disponiveis(db):
    """Só entram disciplinas com pelo menos 1 item já marcado com
    habilidade — item sem habilidade não participa da Trilha."""
    linhas = db.execute(
        "select distinct disciplina from itens_banco where habilidade is not null order by disciplina"
    ).fetchall()
    return [linha["disciplina"] for linha in linhas]


def _habilidades_da_disciplina(db, disciplina):
    """Habilidades da disciplina, ordenadas da maior pra menor prioridade
    (prioridade nula conta como 0, fica por último). Quando itens da mesma
    habilidade têm prioridades diferentes cadastradas, usa a maior — mais
    seguro do que a menor, já que 'prioridade' representa o quanto vale a
    pena focar nela."""
    linhas = db.execute(
        "select habilidade, max(coalesce(prioridade, 0)) as prioridade "
        "from itens_banco where disciplina = ? and habilidade is not null "
        "group by habilidade order by prioridade desc, habilidade asc",
        (disciplina,),
    ).fetchall()
    return [{"habilidade": l["habilidade"], "prioridade": l["prioridade"]} for l in linhas]


def _dominio_do_aluno(db, aluno_id, disciplina):
    """Mapa habilidade -> linha de dominio_habilidades para esse aluno
    nessa disciplina (só as que já têm alguma tentativa registrada)."""
    linhas = db.execute(
        "select * from dominio_habilidades where aluno_id = ? and disciplina = ?",
        (aluno_id, disciplina),
    ).fetchall()
    return {l["habilidade"]: l for l in linhas}


def _ou_cria_dominio(db, aluno_id, disciplina, habilidade):
    linha = db.execute(
        "select * from dominio_habilidades where aluno_id = ? and disciplina = ? and habilidade = ?",
        (aluno_id, disciplina, habilidade),
    ).fetchone()
    if linha:
        return linha
    novo_id = new_id()
    db.execute(
        "insert into dominio_habilidades (id, aluno_id, disciplina, habilidade) values (?,?,?,?)",
        (novo_id, aluno_id, disciplina, habilidade),
    )
    db.commit()
    return db.execute("select * from dominio_habilidades where id = ?", (novo_id,)).fetchone()


def _proxima_habilidade(db, aluno_id, disciplina):
    """A habilidade de maior prioridade que o aluno ainda não domina — ou
    None se ele já dominou todas as habilidades cadastradas nessa
    disciplina (trilha completa por enquanto)."""
    habilidades = _habilidades_da_disciplina(db, disciplina)
    dominio = _dominio_do_aluno(db, aluno_id, disciplina)
    for h in habilidades:
        linha = dominio.get(h["habilidade"])
        if not linha or linha["status"] != "dominada":
            return h["habilidade"]
    return None


def _proximo_item(db, disciplina, habilidade, excluir_id):
    """Escolhe um item aleatório daquela habilidade, evitando repetir o
    último respondido — mas se a habilidade só tiver aquele item cadastrado,
    repete mesmo assim (banco pequeno é esperado no início; melhor repetir
    do que travar a Trilha)."""
    if excluir_id:
        item = db.execute(
            "select * from itens_banco where disciplina = ? and habilidade = ? and id != ? "
            "order by random() limit 1",
            (disciplina, habilidade, excluir_id),
        ).fetchone()
        if item:
            return item
    return db.execute(
        "select * from itens_banco where disciplina = ? and habilidade = ? order by random() limit 1",
        (disciplina, habilidade),
    ).fetchone()


@bp.route("/")
@login_obrigatorio(papeis=["aluno"])
def index():
    db = get_db()
    bloqueio = _bloqueio_se_nao_medio(db)
    if bloqueio:
        return bloqueio
    aluno = _aluno_atual(db)
    disciplinas = _disciplinas_disponiveis(db)
    progresso = {}
    for d in disciplinas:
        habilidades = _habilidades_da_disciplina(db, d)
        dominio = _dominio_do_aluno(db, aluno["id"], d) if aluno else {}
        dominadas = sum(1 for h in habilidades if dominio.get(h["habilidade"], {}).get("status") == "dominada")
        progresso[d] = {"dominadas": dominadas, "total": len(habilidades)}
    return render_template("trilha_index.html", disciplinas=disciplinas, progresso=progresso)


@bp.route("/<disciplina>")
@login_obrigatorio(papeis=["aluno"])
def painel(disciplina):
    db = get_db()
    bloqueio = _bloqueio_se_nao_medio(db)
    if bloqueio:
        return bloqueio
    if disciplina not in _disciplinas_disponiveis(db):
        flash("Ainda não há Trilha Adaptativa cadastrada para essa disciplina.", "erro")
        return redirect(url_for("trilha_adaptativa.index"))

    aluno = _aluno_atual(db)
    habilidades = _habilidades_da_disciplina(db, disciplina)
    dominio = _dominio_do_aluno(db, aluno["id"], disciplina) if aluno else {}
    linhas = []
    for h in habilidades:
        linha = dominio.get(h["habilidade"])
        linhas.append({
            "habilidade": h["habilidade"],
            "status": linha["status"] if linha else "nao_iniciada",
            "streak_atual": linha["streak_atual"] if linha else 0,
        })
    tudo_dominado = bool(linhas) and all(l["status"] == "dominada" for l in linhas)
    nome_disciplina = NOMES_DISCIPLINA.get(disciplina, disciplina.capitalize())
    return render_template(
        "trilha_painel.html", disciplina=disciplina, nome_disciplina=nome_disciplina,
        linhas=linhas, tudo_dominado=tudo_dominado, meta=STREAK_DOMINIO,
    )


@bp.route("/<disciplina>/questao")
@login_obrigatorio(papeis=["aluno"])
def questao(disciplina):
    db = get_db()
    bloqueio = _bloqueio_se_nao_medio(db)
    if bloqueio:
        return bloqueio
    aluno = _aluno_atual(db)
    if not aluno:
        flash("Cadastro de aluno não encontrado.", "erro")
        return redirect(url_for("auth.painel"))

    habilidade = _proxima_habilidade(db, aluno["id"], disciplina)
    if habilidade is None:
        flash("Você já domina todas as habilidades cadastradas nesta trilha — mande ver em outra disciplina!", "sucesso")
        return redirect(url_for("trilha_adaptativa.painel", disciplina=disciplina))

    dominio = _ou_cria_dominio(db, aluno["id"], disciplina, habilidade)
    excluir_id = session.get("trilha_item_anterior")
    item = _proximo_item(db, disciplina, habilidade, excluir_id)
    if item is None:
        flash("Banco de itens insuficiente para essa habilidade — avise a coordenação.", "erro")
        return redirect(url_for("trilha_adaptativa.painel", disciplina=disciplina))

    session["trilha_item_atual"] = item["id"]
    session["trilha_habilidade_atual"] = habilidade
    session["trilha_disciplina_atual"] = disciplina
    session.modified = True

    raw_alternativas = item["alternativas"]
    alternativas = json.loads(raw_alternativas) if isinstance(raw_alternativas, str) else raw_alternativas
    return render_template(
        "trilha_questao.html", item=item, disciplina=disciplina,
        nome_disciplina=NOMES_DISCIPLINA.get(disciplina, disciplina.capitalize()),
        alternativas=alternativas, habilidade=habilidade,
        streak_atual=dominio["streak_atual"], meta=STREAK_DOMINIO,
    )


@bp.route("/<disciplina>/responder", methods=["POST"])
@login_obrigatorio(papeis=["aluno"])
def responder(disciplina):
    db = get_db()
    bloqueio = _bloqueio_se_nao_medio(db)
    if bloqueio:
        return bloqueio
    aluno = _aluno_atual(db)
    item_id = session.get("trilha_item_atual")
    habilidade = session.get("trilha_habilidade_atual")
    if not item_id or not habilidade or session.get("trilha_disciplina_atual") != disciplina:
        return redirect(url_for("trilha_adaptativa.questao", disciplina=disciplina))

    item = db.execute("select * from itens_banco where id = ?", (item_id,)).fetchone()
    resposta = request.form.get("resposta", "")
    correta = (resposta == item["correta"])

    dominio = _ou_cria_dominio(db, aluno["id"], disciplina, habilidade)
    novo_streak = dominio["streak_atual"] + 1 if correta else 0
    novos_acertos = dominio["acertos_total"] + (1 if correta else 0)
    nova_resposta_total = dominio["respostas_total"] + 1
    acabou_de_dominar = correta and novo_streak >= STREAK_DOMINIO and dominio["status"] != "dominada"

    if acabou_de_dominar:
        # Timestamp calculado em Python (não datetime('now')/now() do
        # banco) para funcionar igual em SQLite e Postgres — mesmo padrão
        # de app/modules/diagnostico.py:resultado().
        agora = datetime.now(timezone.utc).isoformat()
        db.execute(
            "update dominio_habilidades set streak_atual = ?, respostas_total = ?, acertos_total = ?, "
            "status = 'dominada', dominada_em = ? where id = ?",
            (novo_streak, nova_resposta_total, novos_acertos, agora, dominio["id"]),
        )
    else:
        db.execute(
            "update dominio_habilidades set streak_atual = ?, respostas_total = ?, acertos_total = ? where id = ?",
            (novo_streak, nova_resposta_total, novos_acertos, dominio["id"]),
        )
    db.commit()

    session["trilha_item_anterior"] = item_id
    session.pop("trilha_item_atual", None)
    session.pop("trilha_habilidade_atual", None)
    session.modified = True

    return render_template(
        "trilha_feedback.html", disciplina=disciplina, correta=correta,
        explicacao=item["explicacao"], correta_letra=item["correta"],
        habilidade=habilidade, streak_atual=novo_streak, meta=STREAK_DOMINIO,
        acabou_de_dominar=acabou_de_dominar,
    )
