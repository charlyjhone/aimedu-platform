"""
Módulo do AIM.Edu: Relatórios para a Família.

Este é o módulo mais "interligado" do sistema: ele não gera nenhum dado
próprio (não tem uma atividade que o aluno faz aqui) — ele só lê o que os
outros módulos já gravaram (diagnósticos, redações, bússola vocacional,
alertas do radar) e monta um retrato único pra família, via
app.ai_engine.gerar_relatorio_familia. Existe porque a tabela
relatorios_familia e o campo alunos.responsavel_usuario_id já estavam no
schema desde o início do projeto — este é o primeiro módulo a usá-los.

Papel "família": um usuário de família só enxerga os alunos onde ele é o
responsavel_usuario_id — nunca a turma inteira nem outros alunos.
"""
from datetime import datetime, timezone
from flask import Blueprint, render_template, redirect, url_for, flash

from ..db import get_db, new_id
from ..auth import login_obrigatorio, usuario_logado
from ..ai_engine import gerar_relatorio_familia

bp = Blueprint("relatorios_familia", __name__, url_prefix="/familia")

MESES = [
    "", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]


def _alunos_da_familia(db):
    u = usuario_logado()
    return db.execute(
        "select al.id, us.nome as nome, t.nome as turma_nome "
        "from alunos al "
        "join usuarios us on us.id = al.usuario_id "
        "join turmas t on t.id = al.turma_id "
        "where al.responsavel_usuario_id = ? "
        "order by us.nome",
        (u["id"],),
    ).fetchall()


def _aluno_da_familia(db, aluno_id):
    u = usuario_logado()
    return db.execute(
        "select al.id, us.nome as nome, t.nome as turma_nome "
        "from alunos al "
        "join usuarios us on us.id = al.usuario_id "
        "join turmas t on t.id = al.turma_id "
        "where al.id = ? and al.responsavel_usuario_id = ?",
        (aluno_id, u["id"]),
    ).fetchone()


@bp.route("/")
@login_obrigatorio(papeis=["familia"])
def index():
    db = get_db()
    alunos = _alunos_da_familia(db)
    if len(alunos) == 1:
        return redirect(url_for("relatorios_familia.aluno", aluno_id=alunos[0]["id"]))
    return render_template("familia_index.html", alunos=alunos)


@bp.route("/aluno/<aluno_id>")
@login_obrigatorio(papeis=["familia"])
def aluno(aluno_id):
    db = get_db()
    aluno_row = _aluno_da_familia(db, aluno_id)
    if not aluno_row:
        flash("Aluno não encontrado ou não vinculado à sua conta.", "erro")
        return redirect(url_for("relatorios_familia.index"))
    relatorios = db.execute(
        "select * from relatorios_familia where aluno_id = ? order by criado_em desc",
        (aluno_id,),
    ).fetchall()
    return render_template("familia_aluno.html", aluno=aluno_row, relatorios=relatorios)


@bp.route("/aluno/<aluno_id>/gerar", methods=["POST"])
@login_obrigatorio(papeis=["familia"])
def gerar(aluno_id):
    db = get_db()
    aluno_row = _aluno_da_familia(db, aluno_id)
    if not aluno_row:
        flash("Aluno não encontrado ou não vinculado à sua conta.", "erro")
        return redirect(url_for("relatorios_familia.index"))

    diagnosticos = db.execute(
        "select * from diagnosticos where aluno_id = ? and finalizado_em is not null "
        "order by finalizado_em desc",
        (aluno_id,),
    ).fetchall()
    redacoes = db.execute(
        "select * from redacoes where aluno_id = ? order by criado_em desc",
        (aluno_id,),
    ).fetchall()
    bussola = db.execute(
        "select * from bussola_respostas where aluno_id = ? order by criado_em desc limit 1",
        (aluno_id,),
    ).fetchone()
    alertas_pendentes = db.execute(
        "select * from alertas_radar where aluno_id = ? and resolvido = false order by criado_em desc",
        (aluno_id,),
    ).fetchall()

    conteudo = gerar_relatorio_familia(aluno_row["nome"], diagnosticos, redacoes, bussola, alertas_pendentes)

    agora = datetime.now(timezone.utc)
    periodo = f"{MESES[agora.month]} de {agora.year}"

    relatorio_id = new_id()
    db.execute(
        "insert into relatorios_familia (id, aluno_id, periodo, conteudo) values (?,?,?,?)",
        (relatorio_id, aluno_id, periodo, conteudo),
    )
    db.commit()

    return redirect(url_for("relatorios_familia.relatorio", relatorio_id=relatorio_id))


@bp.route("/relatorio/<relatorio_id>")
@login_obrigatorio(papeis=["familia"])
def relatorio(relatorio_id):
    db = get_db()
    u = usuario_logado()
    r = db.execute(
        "select rf.*, al.id as aluno_id, us.nome as aluno_nome "
        "from relatorios_familia rf "
        "join alunos al on al.id = rf.aluno_id "
        "join usuarios us on us.id = al.usuario_id "
        "where rf.id = ? and al.responsavel_usuario_id = ?",
        (relatorio_id, u["id"]),
    ).fetchone()
    if not r:
        flash("Relatório não encontrado.", "erro")
        return redirect(url_for("relatorios_familia.index"))
    return render_template("familia_relatorio.html", r=r)
