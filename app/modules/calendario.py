"""
Módulo do AIM.Edu: Calendário escolar.

Guarda eventos (provas, reuniões, feriados etc.) que aparecem em dois
lugares: um resumo dos próximos 5 no painel inicial de todo mundo (widget
"Próximos eventos", injetado em app/__init__.py via _injetar_layout() —
ver eventos_proximos ali) e a lista completa aqui em /calendario.

Só coordenação, direção e direção pedagógica cadastram e excluem eventos
(mesmo padrão de acesso do Radar da Coordenação — ver PAPEIS_ACESSO em
coordenador_professores.py). Todo mundo (aluno, professor, família etc.)
só lê. 'publico' filtra quem enxerga cada evento; 'segmento' é opcional e
reaproveita os mesmos valores de series.etapa ('infantil'|'fund1'|'fund2'|
'medio') — um evento sem segmento aparece pra todo mundo daquele público,
não só de uma etapa.

Uma coordenação escopada a um segmento (ver escopo_etapa() em app/auth.py)
sempre cria evento só pro próprio segmento, sem poder escolher outro — o
formulário nem mostra essa opção pra ela. Direção, direção pedagógica e
uma coordenação sem segmento definido podem escolher qualquer segmento ou
deixar em branco (todos).
"""
from flask import Blueprint, render_template, redirect, url_for, request, flash

from ..db import get_db, new_id
from ..auth import login_obrigatorio, usuario_logado, escopo_etapa, PAPEIS_DIRECAO

bp = Blueprint("calendario", __name__, url_prefix="/calendario")

PAPEIS_GERENCIA = ("coordenador",) + PAPEIS_DIRECAO

PUBLICOS_LABEL = {
    "todos": "Todos (escola inteira)",
    "alunos": "Só alunos",
    "professores": "Só professores",
    "coordenacao": "Só coordenação/direção",
    "familias": "Só famílias",
}


def _publicos_visiveis(papel):
    """Quais 'públicos' de evento esse papel enxerga, além de 'todos'."""
    if papel == "aluno":
        return ["todos", "alunos"]
    if papel == "professor":
        return ["todos", "professores"]
    if papel == "familia":
        return ["todos", "familias"]
    # coordenador, direção, direção pedagógica, psicopedagoga
    return ["todos", "coordenacao"]


def _segmento_do_usuario(db, u):
    """Segmento 'natural' desse usuário pra filtrar eventos — só calculado
    quando dá pra saber com um único join simples e sem ambiguidade (uma
    família pode ter mais de um filho em segmentos diferentes, então não
    filtramos por segmento nesse caso; o mesmo vale pra professor, que pode
    lecionar em mais de um segmento)."""
    if not u:
        return None
    if u.get("papel") == "coordenador":
        return escopo_etapa(u)
    if u.get("papel") == "aluno":
        row = db.execute(
            "select s.etapa from alunos a "
            "join turmas t on t.id = a.turma_id "
            "join series s on s.id = t.serie_id "
            "where a.usuario_id = ?",
            (u["id"],),
        ).fetchone()
        return row["etapa"] if row else None
    return None


def _eventos_visiveis(db, escola_id, publicos, segmento=None, incluir_passados=False, limite=None):
    condicoes = ["escola_id = ?", f"publico in ({','.join('?' for _ in publicos)})"]
    params = [escola_id, *publicos]
    if segmento:
        condicoes.append("(segmento is null or segmento = ?)")
        params.append(segmento)
    if not incluir_passados:
        from datetime import datetime, timezone
        condicoes.append("data_evento >= ?")
        params.append(datetime.now(timezone.utc).date().isoformat())
    sql = f"select * from eventos_escolares where {' and '.join(condicoes)} order by data_evento"
    if limite:
        sql += " limit ?"
        params.append(limite)
    return db.execute(sql, tuple(params)).fetchall()


def _dias_do_mes_com_evento(db, escola_id, publicos, segmento, ano, mes):
    """Dias (só o número, 1-31) do mês/ano dados que têm pelo menos um
    evento visível pra esse público/segmento — usado só pra pintar o
    miniaturizado calendário do mês no topo do painel (ver
    app/__init__.py:_injetar_layout e _painel_topo.html). Não filtra por
    'passado/futuro' de propósito: o mês inteiro é pintado, mesmo os dias
    que já passaram."""
    inicio = f"{ano:04d}-{mes:02d}-01"
    fim = f"{ano:04d}-{mes + 1:02d}-01" if mes < 12 else f"{ano + 1:04d}-01-01"
    condicoes = [
        "escola_id = ?", f"publico in ({','.join('?' for _ in publicos)})",
        "data_evento >= ?", "data_evento < ?",
    ]
    params = [escola_id, *publicos, inicio, fim]
    if segmento:
        condicoes.append("(segmento is null or segmento = ?)")
        params.append(segmento)
    sql = f"select data_evento from eventos_escolares where {' and '.join(condicoes)}"
    linhas = db.execute(sql, tuple(params)).fetchall()
    dias = set()
    for linha in linhas:
        valor = linha["data_evento"]
        texto = valor.isoformat() if hasattr(valor, "isoformat") else str(valor)
        dias.add(int(texto[8:10]))
    return dias


@bp.route("/")
@login_obrigatorio()
def index():
    from ..modules.gestao_usuarios import SEGMENTOS_LABEL

    db = get_db()
    u = usuario_logado()
    publicos = _publicos_visiveis(u["papel"])
    segmento = _segmento_do_usuario(db, u)
    eventos = _eventos_visiveis(db, u["escola_id"], publicos, segmento)
    return render_template(
        "calendario_index.html",
        eventos=eventos,
        pode_gerenciar=u["papel"] in PAPEIS_GERENCIA,
        publicos_label=PUBLICOS_LABEL,
        segmentos_label=SEGMENTOS_LABEL,
    )


@bp.route("/novo", methods=["GET", "POST"])
@login_obrigatorio(papeis=list(PAPEIS_GERENCIA))
def novo():
    from ..modules.gestao_usuarios import SEGMENTOS_LABEL

    db = get_db()
    u = usuario_logado()
    segmento_fixo = escopo_etapa(u) if u["papel"] == "coordenador" else None

    if request.method == "POST":
        titulo = request.form.get("titulo", "").strip()
        data_evento = request.form.get("data_evento", "").strip()
        descricao = request.form.get("descricao", "").strip() or None
        publico = request.form.get("publico", "todos")
        if publico not in PUBLICOS_LABEL:
            publico = "todos"
        segmento = segmento_fixo or (request.form.get("segmento", "").strip() or None)

        if not titulo or not data_evento:
            flash("Preencha ao menos o título e a data do evento.", "erro")
        else:
            db.execute(
                "insert into eventos_escolares "
                "(id, escola_id, titulo, descricao, data_evento, publico, segmento, criado_por_usuario_id) "
                "values (?,?,?,?,?,?,?,?)",
                (new_id(), u["escola_id"], titulo, descricao, data_evento, publico, segmento, u["id"]),
            )
            db.commit()
            flash("Evento cadastrado.", "ok")
            return redirect(url_for("calendario.index"))

    return render_template(
        "calendario_form.html",
        publicos_label=PUBLICOS_LABEL,
        segmentos_label=SEGMENTOS_LABEL,
        mostrar_segmento=segmento_fixo is None,
    )


@bp.route("/<evento_id>/excluir", methods=["POST"])
@login_obrigatorio(papeis=list(PAPEIS_GERENCIA))
def excluir(evento_id):
    db = get_db()
    u = usuario_logado()
    segmento_fixo = escopo_etapa(u) if u["papel"] == "coordenador" else None

    if segmento_fixo:
        evento = db.execute(
            "select id from eventos_escolares where id = ? and escola_id = ? "
            "and (segmento is null or segmento = ?)",
            (evento_id, u["escola_id"], segmento_fixo),
        ).fetchone()
    else:
        evento = db.execute(
            "select id from eventos_escolares where id = ? and escola_id = ?",
            (evento_id, u["escola_id"]),
        ).fetchone()

    if not evento:
        flash("Evento não encontrado ou fora do seu acesso.", "erro")
    else:
        db.execute("delete from eventos_escolares where id = ?", (evento_id,))
        db.commit()
        flash("Evento excluído.", "ok")
    return redirect(url_for("calendario.index"))
