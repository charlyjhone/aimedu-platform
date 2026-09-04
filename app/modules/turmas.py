"""
Módulo do AIM.Edu: Turmas.

Antes deste módulo, a única forma de ver os alunos de uma turma era abrir a
Gestão de Usuários (lista plana de TODOS os usuários da escola, sem agrupar
por turma) e abrir um por um. Turmas em si só existiam a partir do
seed_data.py de demonstração — não havia nenhuma tela que agrupasse "quem
está em qual turma".

Este módulo resolve isso com duas telas:
  1. Lista de turmas (com quantos alunos cada uma tem) — coordenação e
     direção veem todas as turmas da escola; professor só as turmas em que
     dá aula (via professor_turma); psicopedagoga vê todas (mesmo critério
     já usado no módulo de Inclusão, já que o trabalho dela atravessa
     turmas).
  2. Dentro de uma turma, a lista dos alunos dela — com um atalho por
     aluno apontando para a tela mais relevante que aquele papel já tem no
     sistema (coordenação/direção vão para a ficha do Radar da Coordenação
     e para a gestão da conta; professor e psicopedagoga vão para a ficha
     de Inclusão). Este módulo não inventa uma tela de perfil de aluno
     nova — só organiza o caminho até as que já existem, evitando
     duplicar lógica de permissão que os outros módulos já resolvem.

A busca por nome da barra superior (ver app/__init__.py e base.html) usa a
mesma lógica de visibilidade por papel deste módulo, na rota /turmas/busca.
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash

from ..db import get_db, new_id
from ..auth import login_obrigatorio, usuario_logado, escopo_etapa, PAPEIS_DIRECAO
from .gestao_usuarios import SEGMENTOS_DISPONIVEIS, SEGMENTOS_LABEL

bp = Blueprint("turmas", __name__, url_prefix="/turmas")

PAPEIS_ACESSO = ("coordenador", "professor", "psicopedagoga") + PAPEIS_DIRECAO


def _escola_id_atual():
    return usuario_logado()["escola_id"]


def _turmas_do_professor(db, usuario_id):
    return [
        row["turma_id"]
        for row in db.execute(
            "select pt.turma_id from professor_turma pt "
            "join professores p on p.id = pt.professor_id "
            "where p.usuario_id = ?",
            (usuario_id,),
        ).fetchall()
    ]


def _turmas_visiveis(db):
    """Direção e psicopedagoga sempre veem todas as turmas da escola.
    Coordenação vê todas, A NÃO SER que tenha um segmento (etapa) definido —
    nesse caso só as turmas daquele segmento (ver escopo_etapa em app/auth.py).
    Professor só as turmas em que dá aula — mesmo critério de
    app.modules.inclusao._alunos_visiveis, só que agrupado por turma.

    Traz também serie_id/serie_etapa/serie_ordem (antes só serie_nome) e
    ordena por s.ordem antes de t.nome — não para mudar quem vê o quê, e sim
    para dar à tela (ver _agrupar_por_serie) o que precisa para agrupar as
    turmas por série na mesma ordem pedagógica (Infantil → Fund1 → Fund2 →
    Médio) já usada em turmas.gestao(), em vez da lista única e plana de
    antes."""
    u = usuario_logado()
    escola_id = _escola_id_atual()

    if u["papel"] in ("coordenador", "psicopedagoga") or u["papel"] in PAPEIS_DIRECAO:
        segmento = escopo_etapa(u)
        if segmento:
            return db.execute(
                "select t.id, t.nome, t.ano_letivo, s.id as serie_id, s.nome as serie_nome, "
                "s.etapa as serie_etapa, s.ordem as serie_ordem, "
                "(select count(*) from alunos a where a.turma_id = t.id) as total_alunos "
                "from turmas t join series s on s.id = t.serie_id "
                "where s.escola_id = ? and s.etapa = ? order by s.ordem, t.nome",
                (escola_id, segmento),
            ).fetchall()
        return db.execute(
            "select t.id, t.nome, t.ano_letivo, s.id as serie_id, s.nome as serie_nome, "
            "s.etapa as serie_etapa, s.ordem as serie_ordem, "
            "(select count(*) from alunos a where a.turma_id = t.id) as total_alunos "
            "from turmas t join series s on s.id = t.serie_id "
            "where s.escola_id = ? order by s.ordem, t.nome",
            (escola_id,),
        ).fetchall()

    turma_ids = _turmas_do_professor(db, u["id"])
    if not turma_ids:
        return []
    placeholders = ",".join("?" for _ in turma_ids)
    return db.execute(
        f"select t.id, t.nome, t.ano_letivo, s.id as serie_id, s.nome as serie_nome, "
        f"s.etapa as serie_etapa, s.ordem as serie_ordem, "
        f"(select count(*) from alunos a where a.turma_id = t.id) as total_alunos "
        f"from turmas t join series s on s.id = t.serie_id "
        f"where t.id in ({placeholders}) order by s.ordem, t.nome",
        tuple(turma_ids),
    ).fetchall()


def _turma_visivel(db, turma_id):
    """Confere se o usuário logado pode ver esta turma específica — mesma
    regra de _turmas_visiveis, para uma turma só."""
    return next((t for t in _turmas_visiveis(db) if t["id"] == turma_id), None)


def _agrupar_por_serie(turmas):
    """Agrupa a lista (já ordenada por s.ordem, t.nome) de turmas visíveis em
    blocos por série, na mesma forma que turmas_gestao.html já usa (ver
    _series_com_turmas acima) — assim a tela de listagem (turmas_index.html,
    vista por professor/coordenação/psicopedagoga/direção) fica com a mesma
    organização visual da tela de estrutura (turmas_gestao.html, só
    direção), em vez da lista única e plana de antes. Como 'turmas' já veio
    filtrado por quem pode ver o quê, esta função só reagrupa — não repete
    nenhuma checagem de permissão."""
    grupos = []
    grupo_atual = None
    for t in turmas:
        if grupo_atual is None or grupo_atual["serie_id"] != t["serie_id"]:
            grupo_atual = {
                "serie_id": t["serie_id"],
                "serie_nome": t["serie_nome"],
                "serie_etapa": t["serie_etapa"],
                "turmas": [],
            }
            grupos.append(grupo_atual)
        grupo_atual["turmas"].append(t)
    return grupos


def _links_do_aluno(papel, aluno_id, usuario_id):
    """Pra onde o atalho de cada aluno aponta, por papel — reaproveita as
    telas que já existem por aluno em vez de criar uma tela de perfil
    nova."""
    links = []
    if papel == "coordenador" or papel in PAPEIS_DIRECAO:
        links.append(("Ver ficha (Radar)", url_for("radar_coordenacao.aluno", aluno_id=aluno_id)))
        links.append(("Gerenciar conta", url_for("gestao_usuarios.editar", usuario_id=usuario_id)))
    if papel in ("professor", "psicopedagoga", "coordenador") or papel in PAPEIS_DIRECAO:
        links.append(("Ficha de Inclusão", url_for("inclusao.ficha", aluno_id=aluno_id)))
    return links


def _alunos_da_turma(db, turma_id):
    return db.execute(
        "select al.id, al.usuario_id, us.nome as nome, us.email as email, us.ativo as ativo "
        "from alunos al join usuarios us on us.id = al.usuario_id "
        "where al.turma_id = ? order by us.nome",
        (turma_id,),
    ).fetchall()


@bp.route("/")
@login_obrigatorio(papeis=PAPEIS_ACESSO)
def index():
    db = get_db()
    turmas = _turmas_visiveis(db)
    grupos = _agrupar_por_serie(turmas)
    total_alunos = sum(t["total_alunos"] for t in turmas)
    return render_template(
        "turmas_index.html", grupos=grupos, total_turmas=len(turmas), total_alunos=total_alunos,
        segmentos_label=SEGMENTOS_LABEL,
    )


@bp.route("/<turma_id>")
@login_obrigatorio(papeis=PAPEIS_ACESSO)
def roster(turma_id):
    db = get_db()
    u = usuario_logado()
    turma = _turma_visivel(db, turma_id)
    if not turma:
        flash("Turma não encontrada ou fora do seu acesso.", "erro")
        return redirect(url_for("turmas.index"))

    alunos = _alunos_da_turma(db, turma_id)
    alunos_com_links = [
        {"aluno": a, "links": _links_do_aluno(u["papel"], a["id"], a["usuario_id"])} for a in alunos
    ]
    return render_template("turmas_roster.html", turma=turma, alunos_com_links=alunos_com_links)


@bp.route("/busca")
@login_obrigatorio(papeis=PAPEIS_ACESSO)
def busca():
    db = get_db()
    u = usuario_logado()
    escola_id = _escola_id_atual()
    q = request.args.get("q", "").strip()

    linhas = []
    if q:
        if u["papel"] in ("coordenador", "psicopedagoga") or u["papel"] in PAPEIS_DIRECAO:
            segmento = escopo_etapa(u)
            if segmento:
                linhas = db.execute(
                    "select al.id, al.usuario_id, us.nome as nome, t.nome as turma_nome "
                    "from alunos al join usuarios us on us.id = al.usuario_id "
                    "join turmas t on t.id = al.turma_id join series s on s.id = t.serie_id "
                    "where s.escola_id = ? and s.etapa = ? and lower(us.nome) like lower(?) "
                    "order by us.nome",
                    (escola_id, segmento, f"%{q}%"),
                ).fetchall()
            else:
                linhas = db.execute(
                    "select al.id, al.usuario_id, us.nome as nome, t.nome as turma_nome "
                    "from alunos al join usuarios us on us.id = al.usuario_id "
                    "join turmas t on t.id = al.turma_id join series s on s.id = t.serie_id "
                    "where s.escola_id = ? and lower(us.nome) like lower(?) "
                    "order by us.nome",
                    (escola_id, f"%{q}%"),
                ).fetchall()
        else:
            turma_ids = _turmas_do_professor(db, u["id"])
            if turma_ids:
                placeholders = ",".join("?" for _ in turma_ids)
                linhas = db.execute(
                    f"select al.id, al.usuario_id, us.nome as nome, t.nome as turma_nome "
                    f"from alunos al join usuarios us on us.id = al.usuario_id "
                    f"join turmas t on t.id = al.turma_id "
                    f"where al.turma_id in ({placeholders}) and lower(us.nome) like lower(?) "
                    f"order by us.nome",
                    tuple(turma_ids) + (f"%{q}%",),
                ).fetchall()

    resultados = [
        {"aluno": a, "links": _links_do_aluno(u["papel"], a["id"], a["usuario_id"])} for a in linhas
    ]
    return render_template("turmas_busca.html", q=q, resultados=resultados)


# ---------------------------------------------------------------------------
# Gestão de Turmas (estrutura de séries/turmas da escola) — só direção e
# direção pedagógica.
#
# Só quem tem alcance de direção mexe na ESTRUTURA (criar/editar série e
# turma), de propósito: uma coordenação já é escopada por segmento (ver
# escopo_etapa), então criar turma é uma decisão que atravessa a escola
# inteira (ex.: mudar quantas turmas o 6º ano tem afeta a organização da
# escola toda, não só o segmento de uma coordenação). Isso não precisa de um
# seletor de escola — a rota já opera só sobre a escola do usuário logado
# (_escola_id_atual()), então funciona sem nenhuma mudança quando uma
# segunda escola existir.
#
# EXCLUIR é diferente de criar/editar: só "direcao" pode excluir série ou
# turma (PAPEIS_EXCLUSAO_TURMAS abaixo, não PAPEIS_GESTAO_TURMAS) — direção
# pedagógica tem o mesmo acesso à tela e pode criar/editar normalmente, mas
# nunca vê nem consegue chamar as rotas de exclusão (ver gestao(), que
# manda pode_excluir=False pra ela no template, e os decorators de
# excluir_serie()/excluir_turma() abaixo).
# ---------------------------------------------------------------------------
PAPEIS_GESTAO_TURMAS = PAPEIS_DIRECAO
PAPEIS_EXCLUSAO_TURMAS = ("direcao",)


def _series_com_turmas(db, escola_id):
    series = db.execute(
        "select id, nome, etapa, ordem from series where escola_id = ? order by ordem, nome",
        (escola_id,),
    ).fetchall()
    resultado = []
    for s in series:
        turmas_da_serie = db.execute(
            "select t.id, t.nome, t.ano_letivo, "
            "(select count(*) from alunos a where a.turma_id = t.id) as total_alunos "
            "from turmas t where t.serie_id = ? order by t.nome",
            (s["id"],),
        ).fetchall()
        resultado.append({"serie": s, "turmas": turmas_da_serie})
    return resultado


def _serie_pode_excluir(db, serie_id):
    """Bloqueia a exclusão de uma série que ainda tem turma — evita apagar
    por engano uma série cujas turmas (e, em cascata, os alunos delas)
    dependem dela (ver 'on delete cascade' em schema_postgres.sql)."""
    return db.execute("select 1 from turmas where serie_id = ?", (serie_id,)).fetchone() is None


def _turma_pode_excluir(db, turma_id):
    """Mesma lógica de segurança de _bloqueios_exclusao() em gestao_usuarios.py:
    turma com aluno matriculado não pode ser excluída (o 'on delete cascade'
    apagaria o(s) aluno(s) e todo o histórico pedagógico deles junto)."""
    return db.execute("select 1 from alunos where turma_id = ?", (turma_id,)).fetchone() is None


@bp.route("/gestao")
@login_obrigatorio(papeis=PAPEIS_GESTAO_TURMAS)
def gestao():
    db = get_db()
    grupos = _series_com_turmas(db, _escola_id_atual())
    pode_excluir = usuario_logado()["papel"] in PAPEIS_EXCLUSAO_TURMAS
    return render_template(
        "turmas_gestao.html", grupos=grupos, segmentos_label=SEGMENTOS_LABEL, pode_excluir=pode_excluir
    )


@bp.route("/gestao/serie/nova", methods=["GET", "POST"])
@login_obrigatorio(papeis=PAPEIS_GESTAO_TURMAS)
def nova_serie():
    db = get_db()
    escola_id = _escola_id_atual()

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        etapa = request.form.get("etapa", "")
        ordem_bruta = request.form.get("ordem", "").strip()

        erro = None
        if not nome or etapa not in SEGMENTOS_LABEL:
            erro = "Preencha o nome e selecione um segmento válido."
        if not erro and ordem_bruta and not ordem_bruta.isdigit():
            erro = "A ordem deve ser um número."

        if erro:
            flash(erro, "erro")
            return render_template("turmas_gestao_serie_form.html", segmentos=SEGMENTOS_DISPONIVEIS, serie=None, form=request.form)

        if ordem_bruta:
            ordem = int(ordem_bruta)
        else:
            maior = db.execute("select coalesce(max(ordem), 0) m from series where escola_id = ?", (escola_id,)).fetchone()["m"]
            ordem = maior + 1

        db.execute(
            "insert into series (id, escola_id, nome, etapa, ordem) values (?,?,?,?,?)",
            (new_id(), escola_id, nome, etapa, ordem),
        )
        db.commit()
        flash(f"Série {nome} criada.", "ok")
        return redirect(url_for("turmas.gestao"))

    return render_template("turmas_gestao_serie_form.html", segmentos=SEGMENTOS_DISPONIVEIS, serie=None, form={})


@bp.route("/gestao/serie/<serie_id>/editar", methods=["GET", "POST"])
@login_obrigatorio(papeis=PAPEIS_GESTAO_TURMAS)
def editar_serie(serie_id):
    db = get_db()
    escola_id = _escola_id_atual()
    serie = db.execute("select * from series where id = ? and escola_id = ?", (serie_id, escola_id)).fetchone()
    if not serie:
        flash("Série não encontrada.", "erro")
        return redirect(url_for("turmas.gestao"))

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        etapa = request.form.get("etapa", "")
        ordem_bruta = request.form.get("ordem", "").strip()

        erro = None
        if not nome or etapa not in SEGMENTOS_LABEL:
            erro = "Preencha o nome e selecione um segmento válido."
        if not erro and (not ordem_bruta or not ordem_bruta.isdigit()):
            erro = "A ordem deve ser um número."

        if erro:
            flash(erro, "erro")
            return render_template("turmas_gestao_serie_form.html", segmentos=SEGMENTOS_DISPONIVEIS, serie=serie, form=request.form)

        db.execute(
            "update series set nome = ?, etapa = ?, ordem = ? where id = ?",
            (nome, etapa, int(ordem_bruta), serie_id),
        )
        db.commit()
        flash(f"Série {nome} atualizada.", "ok")
        return redirect(url_for("turmas.gestao"))

    return render_template(
        "turmas_gestao_serie_form.html", segmentos=SEGMENTOS_DISPONIVEIS, serie=serie,
        form={"nome": serie["nome"], "etapa": serie["etapa"], "ordem": str(serie["ordem"])},
    )


@bp.route("/gestao/serie/<serie_id>/excluir", methods=["POST"])
@login_obrigatorio(papeis=PAPEIS_EXCLUSAO_TURMAS)
def excluir_serie(serie_id):
    db = get_db()
    escola_id = _escola_id_atual()
    serie = db.execute("select * from series where id = ? and escola_id = ?", (serie_id, escola_id)).fetchone()
    if not serie:
        flash("Série não encontrada.", "erro")
    elif not _serie_pode_excluir(db, serie_id):
        flash(f"Não é possível excluir {serie['nome']} — ela ainda tem turma(s) cadastrada(s). Exclua as turmas primeiro.", "erro")
    else:
        db.execute("delete from series where id = ?", (serie_id,))
        db.commit()
        flash(f"Série {serie['nome']} excluída.", "ok")
    return redirect(url_for("turmas.gestao"))


@bp.route("/gestao/turma/nova", methods=["GET", "POST"])
@login_obrigatorio(papeis=PAPEIS_GESTAO_TURMAS)
def nova_turma():
    db = get_db()
    escola_id = _escola_id_atual()
    series = db.execute("select id, nome from series where escola_id = ? order by ordem, nome", (escola_id,)).fetchall()

    if request.method == "POST":
        serie_id = request.form.get("serie_id", "")
        nome = request.form.get("nome", "").strip()
        ano_letivo_bruto = request.form.get("ano_letivo", "").strip()

        serie_valida = any(s["id"] == serie_id for s in series)
        erro = None
        if not serie_valida:
            erro = "Selecione uma série válida."
        elif not nome:
            erro = "Informe o nome da turma."
        elif not ano_letivo_bruto.isdigit():
            erro = "O ano letivo deve ser um número (ex.: 2027)."

        if erro:
            flash(erro, "erro")
            return render_template("turmas_gestao_turma_form.html", series=series, turma=None, form=request.form)

        db.execute(
            "insert into turmas (id, serie_id, nome, ano_letivo) values (?,?,?,?)",
            (new_id(), serie_id, nome, int(ano_letivo_bruto)),
        )
        db.commit()
        flash(f"Turma {nome} criada.", "ok")
        return redirect(url_for("turmas.gestao"))

    return render_template(
        "turmas_gestao_turma_form.html", series=series, turma=None,
        form={"ano_letivo": "2027"},
    )


@bp.route("/gestao/turma/<turma_id>/editar", methods=["GET", "POST"])
@login_obrigatorio(papeis=PAPEIS_GESTAO_TURMAS)
def editar_turma(turma_id):
    db = get_db()
    escola_id = _escola_id_atual()
    turma = db.execute(
        "select t.* from turmas t join series s on s.id = t.serie_id where t.id = ? and s.escola_id = ?",
        (turma_id, escola_id),
    ).fetchone()
    if not turma:
        flash("Turma não encontrada.", "erro")
        return redirect(url_for("turmas.gestao"))
    series = db.execute("select id, nome from series where escola_id = ? order by ordem, nome", (escola_id,)).fetchall()

    if request.method == "POST":
        serie_id = request.form.get("serie_id", "")
        nome = request.form.get("nome", "").strip()
        ano_letivo_bruto = request.form.get("ano_letivo", "").strip()

        serie_valida = any(s["id"] == serie_id for s in series)
        erro = None
        if not serie_valida:
            erro = "Selecione uma série válida."
        elif not nome:
            erro = "Informe o nome da turma."
        elif not ano_letivo_bruto.isdigit():
            erro = "O ano letivo deve ser um número (ex.: 2027)."

        if erro:
            flash(erro, "erro")
            return render_template("turmas_gestao_turma_form.html", series=series, turma=turma, form=request.form)

        db.execute(
            "update turmas set serie_id = ?, nome = ?, ano_letivo = ? where id = ?",
            (serie_id, nome, int(ano_letivo_bruto), turma_id),
        )
        db.commit()
        flash(f"Turma {nome} atualizada.", "ok")
        return redirect(url_for("turmas.gestao"))

    return render_template(
        "turmas_gestao_turma_form.html", series=series, turma=turma,
        form={"serie_id": turma["serie_id"], "nome": turma["nome"], "ano_letivo": str(turma["ano_letivo"])},
    )


@bp.route("/gestao/turma/<turma_id>/excluir", methods=["POST"])
@login_obrigatorio(papeis=PAPEIS_EXCLUSAO_TURMAS)
def excluir_turma(turma_id):
    db = get_db()
    escola_id = _escola_id_atual()
    turma = db.execute(
        "select t.* from turmas t join series s on s.id = t.serie_id where t.id = ? and s.escola_id = ?",
        (turma_id, escola_id),
    ).fetchone()
    if not turma:
        flash("Turma não encontrada.", "erro")
    elif not _turma_pode_excluir(db, turma_id):
        flash(f"Não é possível excluir {turma['nome']} — ela ainda tem aluno(s) matriculado(s). Transfira-os para outra turma primeiro.", "erro")
    else:
        db.execute("delete from professor_turma where turma_id = ?", (turma_id,))
        db.execute("delete from turmas where id = ?", (turma_id,))
        db.commit()
        flash(f"Turma {turma['nome']} excluída.", "ok")
    return redirect(url_for("turmas.gestao"))
