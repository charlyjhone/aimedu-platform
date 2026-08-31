"""
Autenticação simples baseada em sessão (compartilhada por todos os módulos).
Um único login serve para qualquer papel (aluno, professor, coordenador,
direção, família) — o painel muda conforme o papel, mas a conta é a mesma
base de usuários usada em todo o AIM.Edu.
"""
from functools import wraps
from hashlib import sha256
from flask import Blueprint, render_template, request, redirect, url_for, session, flash

from .db import get_db

bp = Blueprint("auth", __name__)


def hash_senha(senha: str) -> str:
    return sha256(senha.encode("utf-8")).hexdigest()


def usuario_logado():
    return session.get("usuario")


def login_obrigatorio(papeis=None):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            u = usuario_logado()
            if not u:
                return redirect(url_for("auth.login"))
            if papeis and u["papel"] not in papeis:
                flash("Você não tem acesso a esta área.", "erro")
                return redirect(url_for("auth.painel"))
            return fn(*args, **kwargs)
        return wrapper
    return decorator


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        senha = request.form.get("senha", "")
        db = get_db()
        row = db.execute("select * from usuarios where email = ?", (email,)).fetchone()
        if row and row["senha_hash"] == hash_senha(senha):
            session["usuario"] = {"id": row["id"], "nome": row["nome"], "papel": row["papel"], "escola_id": row["escola_id"]}
            return redirect(url_for("auth.painel"))
        flash("E-mail ou senha inválidos.", "erro")
    return render_template("login.html")


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/")
@login_obrigatorio()
def painel():
    u = usuario_logado()
    db = get_db()
    if u["papel"] == "aluno":
        aluno = db.execute("select * from alunos where usuario_id = ?", (u["id"],)).fetchone()
        diagnosticos = db.execute(
            "select * from diagnosticos where aluno_id = ? order by iniciado_em desc", (aluno["id"],)
        ).fetchall()
        return render_template("dashboard_aluno.html", u=u, aluno=aluno, diagnosticos=diagnosticos)
    if u["papel"] in ("coordenador", "direcao"):
        total_diag = db.execute("select count(*) c from diagnosticos").fetchone()["c"]
        alertas = db.execute(
            "select a.*, al.id as aluno_id, t.nome as turma_nome, us.nome as aluno_nome "
            "from alertas_radar a "
            "join turmas t on t.id = a.turma_id "
            "left join alunos al on al.id = a.aluno_id "
            "left join usuarios us on us.id = al.usuario_id "
            "where a.resolvido = false order by a.criado_em desc"
        ).fetchall()
        return render_template("dashboard_coordenacao.html", u=u, total_diag=total_diag, alertas=alertas)
    if u["papel"] == "professor":
        return render_template("dashboard_professor.html", u=u)
    return render_template("dashboard_aluno.html", u=u, aluno=None, diagnosticos=[])
