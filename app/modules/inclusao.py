"""
Módulo do AIM.Edu: Inclusão — cadastro de necessidades específicas e
adaptações por aluno.

Fase 1 (esta versão): um cadastro central por aluno com a categoria da
necessidade, se há laudo formal, quais adaptações usar em sala/avaliações
e o apoio especializado envolvido (ex.: AEE, acompanhante terapêutico).
Quem dá aula para o aluno pode consultar antes de planejar uma aula ou uma
prova; só coordenação/direção podem criar ou editar o cadastro.

Fase futura (não implementada ainda): Plano Educacional Individualizado
(PEI) completo, com metas pedagógicas específicas e revisões periódicas —
este módulo já nasce com o nome/URL pensados para crescer nessa direção
sem quebrar o que existe hoje (o cadastro atual vira a base do PEI, não é
substituído por ele).

Dado sensível — regra de acesso diferente dos outros módulos: aqui o
assunto é laudo/necessidade específica do aluno. Por isso a leitura é mais
restrita que o padrão do projeto: só quem efetivamente dá aula pra aquele
aluno (professor da turma, via professor_turma) ou coordenação/direção da
escola. Família e o próprio aluno não têm uma tela aqui — a escola trata
isso com a família por outros canais, fora do sistema.
"""
from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for, flash

from ..db import get_db, new_id
from ..auth import login_obrigatorio, usuario_logado

bp = Blueprint("inclusao", __name__, url_prefix="/inclusao")

CATEGORIAS = [
    "TEA (Transtorno do Espectro Autista)",
    "TDAH",
    "Deficiência Física",
    "Deficiência Visual",
    "Deficiência Auditiva",
    "Deficiência Intelectual",
    "Altas Habilidades / Superdotação",
    "Dislexia / Transtorno de Aprendizagem",
    "Outro",
]


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


def _alunos_visiveis(db):
    """Coordenação/direção veem todos os alunos da escola; professor só os
    alunos das turmas em que dá aula (via professor_turma)."""
    u = usuario_logado()
    if u["papel"] in ("coordenador", "direcao"):
        return db.execute(
            "select al.id, us.nome as nome, t.nome as turma_nome, al.turma_id "
            "from alunos al "
            "join usuarios us on us.id = al.usuario_id "
            "join turmas t on t.id = al.turma_id "
            "join series s on s.id = t.serie_id "
            "where s.escola_id = ? "
            "order by t.nome, us.nome",
            (_escola_id_atual(),),
        ).fetchall()

    turma_ids = _turmas_do_professor(db, u["id"])
    if not turma_ids:
        return []
    placeholders = ",".join("?" for _ in turma_ids)
    return db.execute(
        f"select al.id, us.nome as nome, t.nome as turma_nome, al.turma_id "
        f"from alunos al "
        f"join usuarios us on us.id = al.usuario_id "
        f"join turmas t on t.id = al.turma_id "
        f"where al.turma_id in ({placeholders}) "
        f"order by t.nome, us.nome",
        tuple(turma_ids),
    ).fetchall()


def _aluno_visivel(db, aluno_id):
    """Confere se o usuário logado pode ver esse aluno específico — mesma
    regra do _alunos_visiveis, mas para um só."""
    return next((a for a in _alunos_visiveis(db) if a["id"] == aluno_id), None)


@bp.route("/")
@login_obrigatorio(papeis=["professor", "coordenador", "direcao"])
def index():
    db = get_db()
    alunos = _alunos_visiveis(db)
    aluno_ids = [a["id"] for a in alunos]
    cadastros = {}
    if aluno_ids:
        placeholders = ",".join("?" for _ in aluno_ids)
        for c in db.execute(
            f"select * from inclusao_cadastro where aluno_id in ({placeholders})",
            tuple(aluno_ids),
        ).fetchall():
            cadastros[c["aluno_id"]] = c
    return render_template("inclusao_index.html", alunos=alunos, cadastros=cadastros)


@bp.route("/aluno/<aluno_id>")
@login_obrigatorio(papeis=["professor", "coordenador", "direcao"])
def ficha(aluno_id):
    db = get_db()
    aluno = _aluno_visivel(db, aluno_id)
    if not aluno:
        flash("Aluno não encontrado ou fora do seu acesso.", "erro")
        return redirect(url_for("inclusao.index"))
    cadastro = db.execute(
        "select * from inclusao_cadastro where aluno_id = ?", (aluno_id,)
    ).fetchone()
    pode_editar = usuario_logado()["papel"] in ("coordenador", "direcao")
    return render_template(
        "inclusao_ficha.html", aluno=aluno, cadastro=cadastro, categorias=CATEGORIAS, pode_editar=pode_editar
    )


@bp.route("/aluno/<aluno_id>/salvar", methods=["POST"])
@login_obrigatorio(papeis=["coordenador", "direcao"])
def salvar(aluno_id):
    db = get_db()
    aluno = _aluno_visivel(db, aluno_id)
    if not aluno:
        flash("Aluno não encontrado ou fora do seu acesso.", "erro")
        return redirect(url_for("inclusao.index"))

    categoria = request.form.get("categoria", "").strip()
    diagnostico_formal = True if request.form.get("diagnostico_formal") == "on" else False
    adaptacoes = request.form.get("adaptacoes", "").strip()
    apoio_especializado = request.form.get("apoio_especializado", "").strip()
    observacoes = request.form.get("observacoes", "").strip()

    if not categoria or not adaptacoes:
        flash("Categoria e adaptações são campos obrigatórios.", "erro")
        return redirect(url_for("inclusao.ficha", aluno_id=aluno_id))

    existente = db.execute(
        "select id from inclusao_cadastro where aluno_id = ?", (aluno_id,)
    ).fetchone()
    u = usuario_logado()
    agora = datetime.now(timezone.utc).isoformat()

    if existente:
        db.execute(
            "update inclusao_cadastro set categoria = ?, diagnostico_formal = ?, adaptacoes = ?, "
            "apoio_especializado = ?, observacoes = ?, atualizado_em = ? where id = ?",
            (categoria, diagnostico_formal, adaptacoes, apoio_especializado, observacoes, agora, existente["id"]),
        )
        flash("Cadastro de inclusão atualizado.", "ok")
    else:
        db.execute(
            "insert into inclusao_cadastro "
            "(id, aluno_id, categoria, diagnostico_formal, adaptacoes, apoio_especializado, "
            "observacoes, criado_por_usuario_id, criado_em, atualizado_em) "
            "values (?,?,?,?,?,?,?,?,?,?)",
            (new_id(), aluno_id, categoria, diagnostico_formal, adaptacoes, apoio_especializado,
             observacoes, u["id"], agora, agora),
        )
        flash("Cadastro de inclusão criado.", "ok")

    db.commit()
    return redirect(url_for("inclusao.ficha", aluno_id=aluno_id))
