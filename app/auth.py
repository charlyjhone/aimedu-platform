"""
Autenticação simples baseada em sessão (compartilhada por todos os módulos).
Um único login serve para qualquer papel (aluno, professor, coordenador,
direção, direção pedagógica, família) — o painel muda conforme o papel, mas
a conta é a mesma base de usuários usada em todo o AIM.Edu.
"""
from functools import wraps
from hashlib import sha256
from flask import Blueprint, render_template, request, redirect, url_for, session, flash

from .db import get_db

bp = Blueprint("auth", __name__)

# Papéis com o mesmo ALCANCE de direção — veem a escola inteira, sem nenhuma
# restrição por segmento, e têm acesso a toda tela que hoje é só de direção
# (Gestão de Turmas, Gestão de Usuários, Inclusão, Radar etc.). A única
# diferença entre elas é exclusão definitiva: "direcao_pedagogica" tem
# praticamente todas as funções de "direcao", mas NUNCA pode excluir nada —
# nem conta de usuário, nem série/turma. Por isso toda rota/condição de
# EXCLUSÃO no sistema continua checando "direcao" sozinho, nunca esta lista
# (ver app/modules/gestao_usuarios.py:excluir() e
# app/modules/turmas.py:PAPEIS_EXCLUSAO_TURMAS); toda outra tela/ação que
# hoje é "só direção" deve usar esta lista, para as duas contas terem o
# mesmo alcance de leitura/edição.
PAPEIS_DIRECAO = ("direcao", "direcao_pedagogica")


def hash_senha(senha: str) -> str:
    return sha256(senha.encode("utf-8")).hexdigest()


def usuario_logado():
    return session.get("usuario")


def escopo_etapa(usuario):
    """Etapa (segmento) à qual um coordenador está restrito, ou None quando
    não há restrição — direção, direção pedagógica e psicopedagoga sempre
    veem a escola inteira (a própria regra de negócio pedida: 'a
    psicopedagoga continua com acesso a todas as turmas e direção'), e um
    coordenador sem segmento definido também não é restringido
    (compatibilidade com contas já existentes antes deste recurso). Só um
    coordenador COM segmento salvo é filtrado. Reaproveita os mesmos valores
    de series.etapa ('infantil'|'fund1'|'fund2'|'medio') em vez de criar uma
    lista paralela."""
    if not usuario or usuario.get("papel") != "coordenador":
        return None
    return usuario.get("segmento")


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
            if not row["ativo"]:
                flash("Esta conta está desativada. Procure a coordenação da escola.", "erro")
                return render_template("login.html")
            session["usuario"] = {
                "id": row["id"], "nome": row["nome"], "papel": row["papel"],
                "escola_id": row["escola_id"], "segmento": row["segmento"],
            }
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
    if u["papel"] == "coordenador" or u["papel"] in PAPEIS_DIRECAO:
        from .modules.radar_coordenacao import _contagem_por_nivel
        from .modules.gestao_usuarios import SEGMENTOS_LABEL

        segmento = escopo_etapa(u)
        segmento_label = SEGMENTOS_LABEL.get(segmento) if segmento else None
        # Só conta diagnóstico já revisado pelo professor (ver o loop de
        # validação em app/modules/coordenador_professores.py) — um cálculo
        # do motor adaptativo ainda não conferido não deve inflar o número
        # que a coordenação vê aqui no painel.
        if segmento:
            total_diag = db.execute(
                "select count(*) c from diagnosticos d join alunos a on a.id = d.aluno_id "
                "join turmas t on t.id = a.turma_id join series s on s.id = t.serie_id "
                "where s.escola_id = ? and s.etapa = ? and d.status = 'revisado'",
                (u["escola_id"], segmento),
            ).fetchone()["c"]
        else:
            total_diag = db.execute(
                "select count(*) c from diagnosticos d join alunos a on a.id = d.aluno_id "
                "join turmas t on t.id = a.turma_id join series s on s.id = t.serie_id "
                "where s.escola_id = ? and d.status = 'revisado'",
                (u["escola_id"],),
            ).fetchone()["c"]
        contagem = _contagem_por_nivel(db, u["escola_id"], segmento)
        return render_template(
            "dashboard_coordenacao.html", u=u, total_diag=total_diag, contagem=contagem, segmento_label=segmento_label
        )
    if u["papel"] == "professor":
        return render_template("dashboard_professor.html", u=u)
    if u["papel"] == "psicopedagoga":
        return render_template("dashboard_psicopedagoga.html", u=u)
    if u["papel"] == "familia":
        return redirect(url_for("relatorios_familia.index"))
    return render_template("dashboard_aluno.html", u=u, aluno=None, diagnosticos=[])
