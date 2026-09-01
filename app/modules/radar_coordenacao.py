"""
Módulo do AIM.Edu: Radar da Coordenação (versão expandida).

Antes, o painel da coordenação só listava os alertas ainda não resolvidos,
sem filtro nem histórico. Este módulo adiciona:
  - Filtros por turma, nível de gravidade e status (pendente/resolvido/todos).
  - Contadores por nível, para a coordenação priorizar de olho rápido.
  - Ação de marcar um alerta como resolvido (e reabrir, se for engano).
  - Uma página por aluno que junta, num só lugar, os alertas dele E o
    histórico de diagnósticos adaptativos (de qualquer disciplina) — a prova
    visual de que o Radar "conversa" com o módulo de Diagnóstico Adaptativo
    pelo mesmo banco, sem nenhuma integração especial entre os dois: é tudo
    uma coisa só.

Este módulo é só de leitura/gestão de alertas — quem CRIA um alerta continua
sendo cada módulo pedagógico (hoje o Diagnóstico Adaptativo e a Redação),
inserindo direto na tabela alertas_radar. Isso é proposital: o Radar é o painel comum
por onde qualquer módulo futuro (redação, bússola, inclusão etc.) pode avisar
a coordenação, sem precisar conhecer os outros módulos.
"""
from flask import Blueprint, render_template, redirect, url_for, request, flash

from ..db import get_db
from ..auth import login_obrigatorio, usuario_logado, escopo_etapa

bp = Blueprint("radar_coordenacao", __name__, url_prefix="/coordenacao/radar")

NIVEIS_VALIDOS = ("alto", "medio", "baixo")
STATUS_VALIDOS = ("pendente", "resolvido", "todos")


def _escola_id_atual():
    return usuario_logado()["escola_id"]


def _turmas_da_escola(db, escola_id, segmento=None):
    if segmento:
        return db.execute(
            "select t.id, t.nome from turmas t "
            "join series s on s.id = t.serie_id "
            "where s.escola_id = ? and s.etapa = ? order by t.nome",
            (escola_id, segmento),
        ).fetchall()
    return db.execute(
        "select t.id, t.nome from turmas t "
        "join series s on s.id = t.serie_id "
        "where s.escola_id = ? order by t.nome",
        (escola_id,),
    ).fetchall()


def _contagem_por_nivel(db, escola_id, segmento=None):
    """Usado tanto por este módulo quanto pelo painel de auth.painel() —
    'segmento' é opcional de propósito: o painel de direção/psicopedagoga
    chama sem segmento (vê tudo), e este módulo passa o segmento do
    coordenador logado quando ele tiver um definido."""
    if segmento:
        linhas = db.execute(
            "select a.nivel, count(*) c from alertas_radar a "
            "join turmas t on t.id = a.turma_id "
            "join series s on s.id = t.serie_id "
            "where s.escola_id = ? and s.etapa = ? and a.resolvido = false "
            "group by a.nivel",
            (escola_id, segmento),
        ).fetchall()
    else:
        linhas = db.execute(
            "select a.nivel, count(*) c from alertas_radar a "
            "join turmas t on t.id = a.turma_id "
            "join series s on s.id = t.serie_id "
            "where s.escola_id = ? and a.resolvido = false "
            "group by a.nivel",
            (escola_id,),
        ).fetchall()
    contagem = {"alto": 0, "medio": 0, "baixo": 0}
    for linha in linhas:
        if linha["nivel"] in contagem:
            contagem[linha["nivel"]] = linha["c"]
    return contagem


@bp.route("/")
@login_obrigatorio(papeis=["coordenador", "direcao"])
def index():
    db = get_db()
    escola_id = _escola_id_atual()
    segmento = escopo_etapa(usuario_logado())

    turma_filtro = request.args.get("turma", "").strip()
    nivel_filtro = request.args.get("nivel", "").strip()
    status_filtro = request.args.get("status", "pendente").strip()
    if status_filtro not in STATUS_VALIDOS:
        status_filtro = "pendente"

    condicoes = ["s.escola_id = ?"]
    params = [escola_id]

    if segmento:
        condicoes.append("s.etapa = ?")
        params.append(segmento)
    if turma_filtro:
        condicoes.append("t.id = ?")
        params.append(turma_filtro)
    if nivel_filtro in NIVEIS_VALIDOS:
        condicoes.append("a.nivel = ?")
        params.append(nivel_filtro)
    if status_filtro == "pendente":
        condicoes.append("a.resolvido = false")
    elif status_filtro == "resolvido":
        condicoes.append("a.resolvido = true")
    # "todos" não adiciona condição de status

    sql = (
        "select a.*, t.nome as turma_nome, us.nome as aluno_nome "
        "from alertas_radar a "
        "join turmas t on t.id = a.turma_id "
        "join series s on s.id = t.serie_id "
        "left join alunos al on al.id = a.aluno_id "
        "left join usuarios us on us.id = al.usuario_id "
        "where " + " and ".join(condicoes) +
        " order by a.resolvido asc, "
        "case a.nivel when 'alto' then 0 when 'medio' then 1 else 2 end, "
        "a.criado_em desc"
    )
    alertas = db.execute(sql, tuple(params)).fetchall()

    return render_template(
        "radar_coordenacao.html",
        alertas=alertas,
        turmas=_turmas_da_escola(db, escola_id, segmento),
        contagem=_contagem_por_nivel(db, escola_id, segmento),
        turma_filtro=turma_filtro,
        nivel_filtro=nivel_filtro,
        status_filtro=status_filtro,
    )


@bp.route("/<alerta_id>/marcar", methods=["POST"])
@login_obrigatorio(papeis=["coordenador", "direcao"])
def marcar(alerta_id):
    db = get_db()
    escola_id = _escola_id_atual()
    segmento = escopo_etapa(usuario_logado())
    acao = request.form.get("acao")
    novo_valor = True if acao == "resolver" else False

    # Confirma que o alerta pertence à mesma escola (e, se for coordenador
    # escopado, ao mesmo segmento) antes de mexer.
    if segmento:
        alerta = db.execute(
            "select a.id from alertas_radar a "
            "join turmas t on t.id = a.turma_id "
            "join series s on s.id = t.serie_id "
            "where a.id = ? and s.escola_id = ? and s.etapa = ?",
            (alerta_id, escola_id, segmento),
        ).fetchone()
    else:
        alerta = db.execute(
            "select a.id from alertas_radar a "
            "join turmas t on t.id = a.turma_id "
            "join series s on s.id = t.serie_id "
            "where a.id = ? and s.escola_id = ?",
            (alerta_id, escola_id),
        ).fetchone()
    if not alerta:
        flash("Alerta não encontrado.", "erro")
    else:
        db.execute("update alertas_radar set resolvido = ? where id = ?", (novo_valor, alerta_id))
        db.commit()
        flash("Alerta marcado como resolvido." if novo_valor else "Alerta reaberto.", "ok")

    return redirect(url_for(
        "radar_coordenacao.index",
        turma=request.form.get("turma", ""),
        nivel=request.form.get("nivel", ""),
        status=request.form.get("status", "pendente"),
    ))


@bp.route("/aluno/<aluno_id>")
@login_obrigatorio(papeis=["coordenador", "direcao"])
def aluno(aluno_id):
    db = get_db()
    escola_id = _escola_id_atual()
    segmento = escopo_etapa(usuario_logado())

    if segmento:
        aluno_row = db.execute(
            "select al.id, us.nome as nome, t.nome as turma_nome "
            "from alunos al "
            "join usuarios us on us.id = al.usuario_id "
            "join turmas t on t.id = al.turma_id "
            "join series s on s.id = t.serie_id "
            "where al.id = ? and s.escola_id = ? and s.etapa = ?",
            (aluno_id, escola_id, segmento),
        ).fetchone()
    else:
        aluno_row = db.execute(
            "select al.id, us.nome as nome, t.nome as turma_nome "
            "from alunos al "
            "join usuarios us on us.id = al.usuario_id "
            "join turmas t on t.id = al.turma_id "
            "join series s on s.id = t.serie_id "
            "where al.id = ? and s.escola_id = ?",
            (aluno_id, escola_id),
        ).fetchone()
    if not aluno_row:
        flash("Aluno não encontrado.", "erro")
        return redirect(url_for("radar_coordenacao.index"))

    alertas = db.execute(
        "select * from alertas_radar where aluno_id = ? order by criado_em desc",
        (aluno_id,),
    ).fetchall()
    diagnosticos = db.execute(
        "select * from diagnosticos where aluno_id = ? order by iniciado_em desc",
        (aluno_id,),
    ).fetchall()
    redacoes = db.execute(
        "select * from redacoes where aluno_id = ? order by criado_em desc",
        (aluno_id,),
    ).fetchall()

    return render_template(
        "radar_aluno.html",
        aluno=aluno_row,
        alertas=alertas,
        diagnosticos=diagnosticos,
        redacoes=redacoes,
    )
