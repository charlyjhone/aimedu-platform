"""
Módulo do AIM.Edu: Redação (correção estilo ENEM).

O aluno envia o tema e o texto da redação; o app.ai_engine.corrigir_redacao
estima uma nota nas 5 competências do ENEM e devolve um feedback. A tabela
'redacoes' já existia no schema desde o início do projeto — este módulo é o
primeiro a usá-la.

Interligação com o resto do sistema: assim como o Diagnóstico Adaptativo de
Matemática, quando a nota total fica muito baixa (abaixo de 400/1000), este
módulo cria um alerta no Radar da Coordenação — mesmo padrão, mesma tabela
alertas_radar, sem nenhuma integração especial entre os módulos.
"""
from flask import Blueprint, render_template, redirect, url_for, request, flash

from ..db import get_db, new_id
from ..auth import login_obrigatorio, usuario_logado
from ..ai_engine import corrigir_redacao

bp = Blueprint("redacao", __name__, url_prefix="/redacao")

LIMIAR_ALERTA = 400  # nota total (de 1000) abaixo da qual um alerta é criado


def _aluno_atual(db):
    u = usuario_logado()
    return db.execute("select * from alunos where usuario_id = ?", (u["id"],)).fetchone()


@bp.route("/")
@login_obrigatorio(papeis=["aluno"])
def index():
    db = get_db()
    aluno = _aluno_atual(db)
    redacoes = db.execute(
        "select * from redacoes where aluno_id = ? order by criado_em desc",
        (aluno["id"],),
    ).fetchall()
    return render_template("redacao_index.html", redacoes=redacoes)


@bp.route("/nova")
@login_obrigatorio(papeis=["aluno"])
def nova():
    return render_template("redacao_form.html")


@bp.route("/enviar", methods=["POST"])
@login_obrigatorio(papeis=["aluno"])
def enviar():
    db = get_db()
    aluno = _aluno_atual(db)

    tema = request.form.get("tema", "").strip()
    texto = request.form.get("texto", "").strip()
    if not texto:
        flash("Escreva o texto da redação antes de enviar.", "erro")
        return redirect(url_for("redacao.nova"))

    resultado = corrigir_redacao(tema, texto)

    redacao_id = new_id()
    db.execute(
        "insert into redacoes (id, aluno_id, tema, texto, nota_c1, nota_c2, nota_c3, nota_c4, nota_c5, feedback_ia) "
        "values (?,?,?,?,?,?,?,?,?,?)",
        (
            redacao_id, aluno["id"], tema or None, texto,
            resultado["nota_c1"], resultado["nota_c2"], resultado["nota_c3"],
            resultado["nota_c4"], resultado["nota_c5"], resultado["feedback_ia"],
        ),
    )
    db.commit()

    # Mesma lógica do diagnóstico de matemática: nota muito baixa gera alerta
    # para a coordenação, na mesma tabela que ela já acompanha no Radar.
    if resultado["nota_total"] < LIMIAR_ALERTA:
        db.execute(
            "insert into alertas_radar (id, turma_id, aluno_id, nivel, motivo) values (?,?,?,?,?)",
            (new_id(), aluno["turma_id"], aluno["id"], "alto",
             f"Redação com nota estimada de {resultado['nota_total']}/1000 (abaixo do esperado)."),
        )
        db.commit()

    return redirect(url_for("redacao.resultado", redacao_id=redacao_id))


@bp.route("/<redacao_id>")
@login_obrigatorio(papeis=["aluno"])
def resultado(redacao_id):
    db = get_db()
    aluno = _aluno_atual(db)
    redacao = db.execute(
        "select * from redacoes where id = ? and aluno_id = ?",
        (redacao_id, aluno["id"]),
    ).fetchone()
    if not redacao:
        flash("Redação não encontrada.", "erro")
        return redirect(url_for("redacao.index"))

    nota_total = sum(redacao[c] or 0 for c in ("nota_c1", "nota_c2", "nota_c3", "nota_c4", "nota_c5"))
    return render_template("redacao_resultado.html", r=redacao, nota_total=nota_total)
