"""
Módulo do AIM.Edu: Gestão de Usuários — permissões por papel e cadastro em
lote.

Regra de permissão adotada (mais simples do que permissões granulares por
módulo, de propósito): continua tudo baseado no papel do usuário (aluno,
professor, coordenador, direção, família) — o que muda aqui é que agora
existe uma tela para coordenação/direção administrar essas contas, em vez
de só o seed_data.py de demonstração. "Admin" não é um papel novo no banco:
é a própria "direção", só chamada assim quando faz sentido na conversa.

Quem pode gerenciar quem: direção pode gerenciar qualquer papel. Coordenador
só pode criar/editar aluno, professor e família — não pode criar nem editar
outro coordenador nem uma conta de direção (evita que um coordenador se
autopromova ou mexa em contas acima da sua própria). Isso é decidido em
_pode_gerenciar_papel() e checado em toda rota que cria ou edita conta.

O que NÃO dá pra fazer aqui, de propósito: trocar o papel de um usuário já
existente (ex.: transformar um aluno em professor). O papel define quais
outras tabelas têm uma linha ligada a esse usuário (alunos, professores) —
permitir a troca abriria uma porta de inconsistência de dados que não vale
a pena para um caso de uso raro. Pra isso, é mais simples desativar a conta
antiga e criar uma nova com o papel certo.

Cadastro em lote: upload de um arquivo CSV separado para alunos
(nome,email,turma) e para professores (nome,email,disciplina,turmas — com
múltiplas turmas separadas por ";"). Cada linha é processada de forma
independente — uma linha com erro (e-mail duplicado, turma não encontrada)
não derruba as outras, o resultado mostra o status linha a linha. Toda
conta criada (individual ou em lote) recebe uma senha temporária aleatória,
mostrada uma única vez logo após a criação — o sistema não guarda senha em
texto puro em nenhum momento.
"""
import csv
import io

from flask import Blueprint, render_template, request, redirect, url_for, flash

from ..db import get_db, new_id
from ..auth import login_obrigatorio, usuario_logado, hash_senha

bp = Blueprint("gestao_usuarios", __name__, url_prefix="/usuarios")

PAPEIS_LABEL = {
    "aluno": "Aluno",
    "professor": "Professor",
    "coordenador": "Coordenador",
    "direcao": "Direção (admin)",
    "familia": "Família",
}


def _escola_id_atual():
    return usuario_logado()["escola_id"]


def _pode_gerenciar_papel(papel_ator: str, papel_alvo: str) -> bool:
    if papel_ator == "direcao":
        return True
    return papel_alvo in ("aluno", "professor", "familia")


def _pode_gerenciar_usuario(ator: dict, alvo) -> bool:
    """Além da regra por papel, todo usuário pode sempre gerenciar a própria
    conta (ex.: redefinir a própria senha) — sem isso, um coordenador
    ficaria travado para mexer no próprio cadastro, já que coordenador não
    pode gerenciar papel 'coordenador' de terceiros."""
    if not alvo:
        return False
    if alvo["id"] == ator["id"]:
        return True
    return _pode_gerenciar_papel(ator["papel"], alvo["papel"])


def _gerar_senha_temporaria(tamanho: int = 8) -> str:
    import secrets
    import string

    alfabeto = "".join(c for c in string.ascii_letters + string.digits if c not in "0O1lI")
    return "".join(secrets.choice(alfabeto) for _ in range(tamanho))


def _turmas_da_escola(db):
    return db.execute(
        "select t.id, t.nome from turmas t join series s on s.id = t.serie_id "
        "where s.escola_id = ? order by t.nome",
        (_escola_id_atual(),),
    ).fetchall()


@bp.route("/")
@login_obrigatorio(papeis=["coordenador", "direcao"])
def index():
    db = get_db()
    usuarios = db.execute(
        "select * from usuarios where escola_id = ? order by papel, nome", (_escola_id_atual(),)
    ).fetchall()
    return render_template("gestao_usuarios_index.html", usuarios=usuarios, papeis_label=PAPEIS_LABEL)


@bp.route("/novo", methods=["GET", "POST"])
@login_obrigatorio(papeis=["coordenador", "direcao"])
def novo():
    db = get_db()
    escola_id = _escola_id_atual()
    papel_ator = usuario_logado()["papel"]
    papeis_disponiveis = {p: rotulo for p, rotulo in PAPEIS_LABEL.items() if _pode_gerenciar_papel(papel_ator, p)}
    turmas = _turmas_da_escola(db)
    alunos_sem_familia = db.execute(
        "select al.id, us.nome as nome from alunos al "
        "join usuarios us on us.id = al.usuario_id "
        "join turmas t on t.id = al.turma_id join series s on s.id = t.serie_id "
        "where s.escola_id = ? and al.responsavel_usuario_id is null order by us.nome",
        (escola_id,),
    ).fetchall()

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        email = request.form.get("email", "").strip().lower()
        papel = request.form.get("papel", "")
        turma_id = request.form.get("turma_id") or None
        disciplina = request.form.get("disciplina", "").strip()
        turmas_professor = request.form.getlist("turmas_professor")
        aluno_vinculado_id = request.form.get("aluno_vinculado_id") or None

        erro = None
        if not nome or not email or papel not in PAPEIS_LABEL:
            erro = "Preencha nome, e-mail e papel corretamente."
        elif not _pode_gerenciar_papel(papel_ator, papel):
            erro = "Você não tem permissão para criar um usuário com esse papel."
        elif db.execute("select id from usuarios where email = ?", (email,)).fetchone():
            erro = "Já existe um usuário com esse e-mail."
        elif papel == "aluno" and not turma_id:
            erro = "Selecione a turma do aluno."

        if erro:
            flash(erro, "erro")
            return render_template(
                "gestao_usuarios_form.html", turmas=turmas, alunos_sem_familia=alunos_sem_familia,
                papeis_disponiveis=papeis_disponiveis, form=request.form,
            )

        senha_temp = _gerar_senha_temporaria()
        uid = new_id()
        db.execute(
            "insert into usuarios (id, escola_id, nome, email, senha_hash, papel, ativo) values (?,?,?,?,?,?,?)",
            (uid, escola_id, nome, email, hash_senha(senha_temp), papel, True),
        )
        if papel == "aluno":
            db.execute("insert into alunos (id, usuario_id, turma_id) values (?,?,?)", (new_id(), uid, turma_id))
        elif papel == "professor":
            professor_id = new_id()
            db.execute(
                "insert into professores (id, usuario_id, disciplina) values (?,?,?)",
                (professor_id, uid, disciplina or None),
            )
            for turma_id_prof in turmas_professor:
                db.execute(
                    "insert into professor_turma (professor_id, turma_id) values (?,?)", (professor_id, turma_id_prof)
                )
        elif papel == "familia" and aluno_vinculado_id:
            db.execute("update alunos set responsavel_usuario_id = ? where id = ?", (uid, aluno_vinculado_id))

        db.commit()
        flash(
            f"Usuário {nome} criado. E-mail: {email} — senha temporária: {senha_temp} "
            "(anote agora, ela não será mostrada de novo).",
            "credenciais",
        )
        return redirect(url_for("gestao_usuarios.index"))

    return render_template(
        "gestao_usuarios_form.html", turmas=turmas, alunos_sem_familia=alunos_sem_familia,
        papeis_disponiveis=papeis_disponiveis, form={},
    )


@bp.route("/<usuario_id>")
@login_obrigatorio(papeis=["coordenador", "direcao"])
def editar(usuario_id):
    db = get_db()
    alvo = db.execute(
        "select * from usuarios where id = ? and escola_id = ?", (usuario_id, _escola_id_atual())
    ).fetchone()
    if not _pode_gerenciar_usuario(usuario_logado(), alvo):
        flash("Usuário não encontrado ou fora do seu acesso.", "erro")
        return redirect(url_for("gestao_usuarios.index"))

    turmas = _turmas_da_escola(db)
    turma_atual_id = None
    professor_row = None
    turmas_vinculadas = []

    if alvo["papel"] == "aluno":
        aluno_row = db.execute("select * from alunos where usuario_id = ?", (usuario_id,)).fetchone()
        turma_atual_id = aluno_row["turma_id"] if aluno_row else None

    if alvo["papel"] == "professor":
        professor_row = db.execute("select * from professores where usuario_id = ?", (usuario_id,)).fetchone()
        if professor_row:
            turmas_vinculadas = [
                r["turma_id"]
                for r in db.execute(
                    "select turma_id from professor_turma where professor_id = ?", (professor_row["id"],)
                ).fetchall()
            ]

    return render_template(
        "gestao_usuarios_editar.html", alvo=alvo, turmas=turmas, turma_atual_id=turma_atual_id,
        professor_row=professor_row, turmas_vinculadas=turmas_vinculadas, papeis_label=PAPEIS_LABEL,
    )


@bp.route("/<usuario_id>/salvar", methods=["POST"])
@login_obrigatorio(papeis=["coordenador", "direcao"])
def salvar(usuario_id):
    db = get_db()
    alvo = db.execute(
        "select * from usuarios where id = ? and escola_id = ?", (usuario_id, _escola_id_atual())
    ).fetchone()
    if not _pode_gerenciar_usuario(usuario_logado(), alvo):
        flash("Usuário não encontrado ou fora do seu acesso.", "erro")
        return redirect(url_for("gestao_usuarios.index"))

    ativo = True if request.form.get("ativo") == "on" else False
    if alvo["id"] == usuario_logado()["id"] and not ativo:
        flash("Você não pode desativar sua própria conta.", "erro")
        return redirect(url_for("gestao_usuarios.editar", usuario_id=usuario_id))

    db.execute("update usuarios set ativo = ? where id = ?", (ativo, usuario_id))

    if alvo["papel"] == "aluno":
        turma_id = request.form.get("turma_id")
        if turma_id:
            db.execute("update alunos set turma_id = ? where usuario_id = ?", (turma_id, usuario_id))

    if alvo["papel"] == "professor":
        disciplina = request.form.get("disciplina", "").strip()
        professor_row = db.execute("select id from professores where usuario_id = ?", (usuario_id,)).fetchone()
        if professor_row:
            db.execute("update professores set disciplina = ? where id = ?", (disciplina or None, professor_row["id"]))
            db.execute("delete from professor_turma where professor_id = ?", (professor_row["id"],))
            for turma_id_prof in request.form.getlist("turmas_professor"):
                db.execute(
                    "insert into professor_turma (professor_id, turma_id) values (?,?)",
                    (professor_row["id"], turma_id_prof),
                )

    db.commit()
    flash("Usuário atualizado.", "ok")
    return redirect(url_for("gestao_usuarios.editar", usuario_id=usuario_id))


@bp.route("/<usuario_id>/redefinir-senha", methods=["POST"])
@login_obrigatorio(papeis=["coordenador", "direcao"])
def redefinir_senha(usuario_id):
    db = get_db()
    alvo = db.execute(
        "select * from usuarios where id = ? and escola_id = ?", (usuario_id, _escola_id_atual())
    ).fetchone()
    if not _pode_gerenciar_usuario(usuario_logado(), alvo):
        flash("Usuário não encontrado ou fora do seu acesso.", "erro")
        return redirect(url_for("gestao_usuarios.index"))

    nova_senha = _gerar_senha_temporaria()
    db.execute("update usuarios set senha_hash = ? where id = ?", (hash_senha(nova_senha), usuario_id))
    db.commit()
    flash(
        f"Nova senha temporária de {alvo['nome']}: {nova_senha} (anote agora, ela não será mostrada de novo).",
        "credenciais",
    )
    return redirect(url_for("gestao_usuarios.editar", usuario_id=usuario_id))


@bp.route("/importar/alunos", methods=["GET", "POST"])
@login_obrigatorio(papeis=["coordenador", "direcao"])
def importar_alunos():
    db = get_db()
    escola_id = _escola_id_atual()
    resultados = None

    if request.method == "POST":
        arquivo = request.files.get("arquivo")
        if not arquivo or not arquivo.filename:
            flash("Selecione um arquivo CSV.", "erro")
            return redirect(url_for("gestao_usuarios.importar_alunos"))

        try:
            texto = arquivo.stream.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            flash("Não consegui ler o arquivo — salve-o como CSV UTF-8 e tente de novo.", "erro")
            return redirect(url_for("gestao_usuarios.importar_alunos"))

        linhas = [linha for linha in csv.reader(io.StringIO(texto)) if any(c.strip() for c in linha)]
        if linhas and [c.strip().lower() for c in linhas[0][:3]] == ["nome", "email", "turma"]:
            linhas = linhas[1:]

        resultados = []
        for i, linha in enumerate(linhas, start=1):
            if len(linha) < 3:
                resultados.append({
                    "linha": i, "nome": linha[0].strip() if linha else "-", "status": "erro",
                    "motivo": "linha com menos de 3 colunas (esperado: nome,email,turma)",
                })
                continue

            nome, email, turma_nome = (c.strip() for c in linha[:3])
            email = email.lower()
            if not nome or not email or not turma_nome:
                resultados.append({"linha": i, "nome": nome or "-", "status": "erro", "motivo": "nome, e-mail ou turma em branco"})
                continue
            if db.execute("select id from usuarios where email = ?", (email,)).fetchone():
                resultados.append({"linha": i, "nome": nome, "status": "erro", "motivo": f"e-mail {email} já cadastrado"})
                continue
            turma = db.execute(
                "select t.id from turmas t join series s on s.id = t.serie_id "
                "where s.escola_id = ? and lower(t.nome) = lower(?)",
                (escola_id, turma_nome),
            ).fetchone()
            if not turma:
                resultados.append({"linha": i, "nome": nome, "status": "erro", "motivo": f"turma '{turma_nome}' não encontrada"})
                continue

            senha_temp = _gerar_senha_temporaria()
            uid = new_id()
            db.execute(
                "insert into usuarios (id, escola_id, nome, email, senha_hash, papel, ativo) values (?,?,?,?,?,?,?)",
                (uid, escola_id, nome, email, hash_senha(senha_temp), "aluno", True),
            )
            db.execute("insert into alunos (id, usuario_id, turma_id) values (?,?,?)", (new_id(), uid, turma["id"]))
            resultados.append({"linha": i, "nome": nome, "email": email, "senha": senha_temp, "status": "criado"})

        db.commit()

    return render_template("gestao_usuarios_importar_alunos.html", resultados=resultados)


@bp.route("/importar/professores", methods=["GET", "POST"])
@login_obrigatorio(papeis=["coordenador", "direcao"])
def importar_professores():
    db = get_db()
    escola_id = _escola_id_atual()
    resultados = None

    if request.method == "POST":
        arquivo = request.files.get("arquivo")
        if not arquivo or not arquivo.filename:
            flash("Selecione um arquivo CSV.", "erro")
            return redirect(url_for("gestao_usuarios.importar_professores"))

        try:
            texto = arquivo.stream.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            flash("Não consegui ler o arquivo — salve-o como CSV UTF-8 e tente de novo.", "erro")
            return redirect(url_for("gestao_usuarios.importar_professores"))

        linhas = [linha for linha in csv.reader(io.StringIO(texto)) if any(c.strip() for c in linha)]
        if linhas and [c.strip().lower() for c in linhas[0][:4]] == ["nome", "email", "disciplina", "turmas"]:
            linhas = linhas[1:]

        resultados = []
        for i, linha in enumerate(linhas, start=1):
            if len(linha) < 2:
                resultados.append({
                    "linha": i, "nome": linha[0].strip() if linha else "-", "status": "erro",
                    "motivo": "linha com menos de 2 colunas (esperado: nome,email,disciplina,turmas)",
                })
                continue

            nome = linha[0].strip()
            email = linha[1].strip().lower()
            disciplina = linha[2].strip() if len(linha) > 2 else ""
            turmas_texto = linha[3].strip() if len(linha) > 3 else ""

            if not nome or not email:
                resultados.append({"linha": i, "nome": nome or "-", "status": "erro", "motivo": "nome ou e-mail em branco"})
                continue
            if db.execute("select id from usuarios where email = ?", (email,)).fetchone():
                resultados.append({"linha": i, "nome": nome, "status": "erro", "motivo": f"e-mail {email} já cadastrado"})
                continue

            nomes_turma = [t.strip() for t in turmas_texto.split(";") if t.strip()]
            turma_ids = []
            turmas_nao_encontradas = []
            for nome_turma in nomes_turma:
                turma = db.execute(
                    "select t.id from turmas t join series s on s.id = t.serie_id "
                    "where s.escola_id = ? and lower(t.nome) = lower(?)",
                    (escola_id, nome_turma),
                ).fetchone()
                if turma:
                    turma_ids.append(turma["id"])
                else:
                    turmas_nao_encontradas.append(nome_turma)

            senha_temp = _gerar_senha_temporaria()
            uid = new_id()
            db.execute(
                "insert into usuarios (id, escola_id, nome, email, senha_hash, papel, ativo) values (?,?,?,?,?,?,?)",
                (uid, escola_id, nome, email, hash_senha(senha_temp), "professor", True),
            )
            professor_id = new_id()
            db.execute(
                "insert into professores (id, usuario_id, disciplina) values (?,?,?)",
                (professor_id, uid, disciplina or None),
            )
            for turma_id in turma_ids:
                db.execute("insert into professor_turma (professor_id, turma_id) values (?,?)", (professor_id, turma_id))

            motivo = None
            if turmas_nao_encontradas:
                motivo = "turma(s) não encontrada(s), ignoradas: " + ", ".join(turmas_nao_encontradas)
            resultados.append({"linha": i, "nome": nome, "email": email, "senha": senha_temp, "status": "criado", "motivo": motivo})

        db.commit()

    return render_template("gestao_usuarios_importar_professores.html", resultados=resultados)
