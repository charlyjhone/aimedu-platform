"""
Módulo do AIM.Edu: Inclusão — cadastro de necessidades específicas e
adaptações por aluno.

Fase 1 (esta versão): um cadastro central por aluno com a categoria da
necessidade, se há laudo formal, quais adaptações usar em sala/avaliações
e o apoio especializado envolvido (ex.: AEE, acompanhante terapêutico).
Quem dá aula para o aluno pode consultar antes de planejar uma aula ou uma
prova; quem cria ou edita o cadastro é a psicopedagoga (a responsável por
esse trabalho no dia a dia) ou coordenação/direção (incluindo direção pedagógica).

Fase 2 (adicionada depois, também neste arquivo): o PEI (Plano Educacional
Individualizado) completo — metas pedagógicas específicas por aluno, cada
uma com status (não iniciada / em andamento / atingida), e um histórico de
revisões periódicas em texto livre. O PEI exige que o aluno já tenha um
cadastro de Inclusão (fase 1) — ele não existe sozinho, é uma continuação
do mesmo cadastro. Mesma regra de acesso da fase 1: psicopedagoga e
coordenação/direção criam metas e registram revisões; o professor só
consulta (acessando a ficha do aluno, ele vê tudo que a psicopedagoga
registrou, sem poder alterar).

Dado sensível — regra de acesso diferente dos outros módulos: aqui o
assunto é laudo/necessidade específica do aluno. Por isso a leitura é mais
restrita que o padrão do projeto: só quem efetivamente dá aula pra aquele
aluno (professor da turma, via professor_turma), a psicopedagoga (vê todos
os alunos da escola, já que seu trabalho atravessa turmas) ou
coordenação/direção da escola. Família e o próprio aluno não têm uma tela
aqui — a escola trata isso com a família por outros canais, fora do
sistema.
"""
from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for, flash

from ..db import get_db, new_id
from ..auth import login_obrigatorio, usuario_logado, escopo_etapa, PAPEIS_DIRECAO

bp = Blueprint("inclusao", __name__, url_prefix="/inclusao")

# Quem edita o cadastro de inclusão e o PEI (cria/atualiza) — psicopedagoga é
# a responsável direta por esse trabalho; coordenação/direção/direção
# pedagógica mantêm acesso de supervisão (não há exclusão neste módulo, só
# criar/atualizar, então direção pedagógica participa por igual, sem
# restrição nenhuma). Professor nunca entra aqui, só nos papéis de leitura
# abaixo.
PAPEIS_EDITOR_INCLUSAO = ("psicopedagoga", "coordenador") + PAPEIS_DIRECAO
# Quem enxerga a tela (edição + leitura) — o professor é o único que só lê.
PAPEIS_LEITURA_INCLUSAO = ("professor",) + PAPEIS_EDITOR_INCLUSAO

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

STATUS_META_LABEL = {
    "nao_iniciada": "Não iniciada",
    "em_andamento": "Em andamento",
    "atingida": "Atingida",
}


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
    """Direção e psicopedagoga SEMPRE veem todos os alunos da escola — dado
    sensível de inclusão é o motivo de a psicopedagoga ter acesso amplo aqui,
    e isso não muda com o recorte por segmento (pedido explícito: 'a
    psicopedagoga continua com acesso a todas as turmas'). Coordenação vê
    todos, a não ser que tenha um segmento definido — nesse caso só os
    alunos daquele segmento. Professor só os alunos das turmas em que dá
    aula (via professor_turma)."""
    u = usuario_logado()
    if u["papel"] == "psicopedagoga" or u["papel"] in PAPEIS_DIRECAO or (u["papel"] == "coordenador" and not escopo_etapa(u)):
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

    if u["papel"] == "coordenador":
        return db.execute(
            "select al.id, us.nome as nome, t.nome as turma_nome, al.turma_id "
            "from alunos al "
            "join usuarios us on us.id = al.usuario_id "
            "join turmas t on t.id = al.turma_id "
            "join series s on s.id = t.serie_id "
            "where s.escola_id = ? and s.etapa = ? "
            "order by t.nome, us.nome",
            (_escola_id_atual(), escopo_etapa(u)),
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
@login_obrigatorio(papeis=PAPEIS_LEITURA_INCLUSAO)
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
@login_obrigatorio(papeis=PAPEIS_LEITURA_INCLUSAO)
def ficha(aluno_id):
    db = get_db()
    aluno = _aluno_visivel(db, aluno_id)
    if not aluno:
        flash("Aluno não encontrado ou fora do seu acesso.", "erro")
        return redirect(url_for("inclusao.index"))
    cadastro = db.execute(
        "select * from inclusao_cadastro where aluno_id = ?", (aluno_id,)
    ).fetchone()
    pode_editar = usuario_logado()["papel"] in PAPEIS_EDITOR_INCLUSAO
    return render_template(
        "inclusao_ficha.html", aluno=aluno, cadastro=cadastro, categorias=CATEGORIAS, pode_editar=pode_editar
    )


@bp.route("/aluno/<aluno_id>/salvar", methods=["POST"])
@login_obrigatorio(papeis=PAPEIS_EDITOR_INCLUSAO)
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


@bp.route("/aluno/<aluno_id>/pei")
@login_obrigatorio(papeis=PAPEIS_LEITURA_INCLUSAO)
def pei(aluno_id):
    db = get_db()
    aluno = _aluno_visivel(db, aluno_id)
    if not aluno:
        flash("Aluno não encontrado ou fora do seu acesso.", "erro")
        return redirect(url_for("inclusao.index"))

    cadastro = db.execute("select id from inclusao_cadastro where aluno_id = ?", (aluno_id,)).fetchone()
    if not cadastro:
        flash("Crie primeiro o cadastro de inclusão deste aluno para depois montar o PEI.", "erro")
        return redirect(url_for("inclusao.ficha", aluno_id=aluno_id))

    metas = db.execute("select * from pei_metas where aluno_id = ? order by criado_em", (aluno_id,)).fetchall()
    revisoes = db.execute(
        "select * from pei_revisoes where aluno_id = ? order by criado_em desc", (aluno_id,)
    ).fetchall()
    pode_editar = usuario_logado()["papel"] in PAPEIS_EDITOR_INCLUSAO
    return render_template(
        "inclusao_pei.html", aluno=aluno, metas=metas, revisoes=revisoes,
        status_label=STATUS_META_LABEL, pode_editar=pode_editar,
    )


@bp.route("/aluno/<aluno_id>/pei/metas/nova", methods=["POST"])
@login_obrigatorio(papeis=PAPEIS_EDITOR_INCLUSAO)
def criar_meta(aluno_id):
    db = get_db()
    aluno = _aluno_visivel(db, aluno_id)
    if not aluno:
        flash("Aluno não encontrado ou fora do seu acesso.", "erro")
        return redirect(url_for("inclusao.index"))

    descricao = request.form.get("descricao", "").strip()
    area = request.form.get("area", "").strip()
    if not descricao:
        flash("Descreva a meta.", "erro")
        return redirect(url_for("inclusao.pei", aluno_id=aluno_id))

    db.execute(
        "insert into pei_metas (id, aluno_id, descricao, area, criado_por_usuario_id) values (?,?,?,?,?)",
        (new_id(), aluno_id, descricao, area or None, usuario_logado()["id"]),
    )
    db.commit()
    flash("Meta adicionada ao PEI.", "ok")
    return redirect(url_for("inclusao.pei", aluno_id=aluno_id))


@bp.route("/aluno/<aluno_id>/pei/metas/<meta_id>/status", methods=["POST"])
@login_obrigatorio(papeis=PAPEIS_EDITOR_INCLUSAO)
def atualizar_status_meta(aluno_id, meta_id):
    db = get_db()
    aluno = _aluno_visivel(db, aluno_id)
    if not aluno:
        flash("Aluno não encontrado ou fora do seu acesso.", "erro")
        return redirect(url_for("inclusao.index"))

    novo_status = request.form.get("status")
    if novo_status not in STATUS_META_LABEL:
        flash("Status inválido.", "erro")
        return redirect(url_for("inclusao.pei", aluno_id=aluno_id))

    meta = db.execute("select id from pei_metas where id = ? and aluno_id = ?", (meta_id, aluno_id)).fetchone()
    if not meta:
        flash("Meta não encontrada.", "erro")
        return redirect(url_for("inclusao.pei", aluno_id=aluno_id))

    db.execute(
        "update pei_metas set status = ?, atualizado_em = ? where id = ?",
        (novo_status, datetime.now(timezone.utc).isoformat(), meta_id),
    )
    db.commit()
    flash("Status da meta atualizado.", "ok")
    return redirect(url_for("inclusao.pei", aluno_id=aluno_id))


@bp.route("/aluno/<aluno_id>/pei/revisoes/nova", methods=["POST"])
@login_obrigatorio(papeis=PAPEIS_EDITOR_INCLUSAO)
def criar_revisao(aluno_id):
    db = get_db()
    aluno = _aluno_visivel(db, aluno_id)
    if not aluno:
        flash("Aluno não encontrado ou fora do seu acesso.", "erro")
        return redirect(url_for("inclusao.index"))

    texto = request.form.get("texto", "").strip()
    if not texto:
        flash("Escreva o texto da revisão.", "erro")
        return redirect(url_for("inclusao.pei", aluno_id=aluno_id))

    db.execute(
        "insert into pei_revisoes (id, aluno_id, texto, criado_por_usuario_id) values (?,?,?,?)",
        (new_id(), aluno_id, texto, usuario_logado()["id"]),
    )
    db.commit()
    flash("Revisão registrada.", "ok")
    return redirect(url_for("inclusao.pei", aluno_id=aluno_id))
