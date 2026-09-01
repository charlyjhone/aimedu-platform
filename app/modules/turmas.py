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

from ..db import get_db
from ..auth import login_obrigatorio, usuario_logado

bp = Blueprint("turmas", __name__, url_prefix="/turmas")

PAPEIS_ACESSO = ("coordenador", "direcao", "professor", "psicopedagoga")


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
    """Coordenação/direção/psicopedagoga veem todas as turmas da escola;
    professor só as turmas em que dá aula — mesmo critério de
    app.modules.inclusao._alunos_visiveis, só que agrupado por turma."""
    u = usuario_logado()
    escola_id = _escola_id_atual()

    if u["papel"] in ("coordenador", "direcao", "psicopedagoga"):
        return db.execute(
            "select t.id, t.nome, t.ano_letivo, s.nome as serie_nome, "
            "(select count(*) from alunos a where a.turma_id = t.id) as total_alunos "
            "from turmas t join series s on s.id = t.serie_id "
            "where s.escola_id = ? order by t.nome",
            (escola_id,),
        ).fetchall()

    turma_ids = _turmas_do_professor(db, u["id"])
    if not turma_ids:
        return []
    placeholders = ",".join("?" for _ in turma_ids)
    return db.execute(
        f"select t.id, t.nome, t.ano_letivo, s.nome as serie_nome, "
        f"(select count(*) from alunos a where a.turma_id = t.id) as total_alunos "
        f"from turmas t join series s on s.id = t.serie_id "
        f"where t.id in ({placeholders}) order by t.nome",
        tuple(turma_ids),
    ).fetchall()


def _turma_visivel(db, turma_id):
    """Confere se o usuário logado pode ver esta turma específica — mesma
    regra de _turmas_visiveis, para uma turma só."""
    return next((t for t in _turmas_visiveis(db) if t["id"] == turma_id), None)


def _links_do_aluno(papel, aluno_id, usuario_id):
    """Pra onde o atalho de cada aluno aponta, por papel — reaproveita as
    telas que já existem por aluno em vez de criar uma tela de perfil
    nova."""
    links = []
    if papel in ("coordenador", "direcao"):
        links.append(("Ver ficha (Radar)", url_for("radar_coordenacao.aluno", aluno_id=aluno_id)))
        links.append(("Gerenciar conta", url_for("gestao_usuarios.editar", usuario_id=usuario_id)))
    if papel in ("professor", "psicopedagoga", "coordenador", "direcao"):
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
    return render_template("turmas_index.html", turmas=turmas)


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
        if u["papel"] in ("coordenador", "direcao", "psicopedagoga"):
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
