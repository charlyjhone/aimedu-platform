"""
Módulo do AIM.Edu: Educação Infantil — Registro de Observação (M7.1 do
escopo do projeto).

A Educação Infantil (abordagem Reggio Emilia, conforme o escopo) não usa o
Diagnóstico Adaptativo de múltipla escolha dos demais segmentos — ela é
acompanhada por observação. Este módulo é a versão mais simples possível
disso: o professor registra uma foto ou um áudio curto de uma criança, sem
precisar digitar nada (a legenda é sempre opcional), e isso fica associado
à criança e à turma.

O que este módulo NÃO faz ainda (M7.2, escopo do projeto): organizar esse
material automaticamente em documentação pedagógica apresentável à família,
via IA. Isso depende de um provedor de IA multimodal (foto + áudio) ainda
não contratado — ver PROVEDOR_ATIVO em app/ai_engine.py. Por isso todo
registro nasce com status='aguardando_ia' e texto_ia=NULL, e a tela da
família mostra um aviso nesse lugar em vez de inventar um texto. Quando o
M7.2 for implementado, o texto_ia de cada registro passa a ser preenchido
(provavelmente em lote, por turma/período) sem precisar mudar nada aqui.

Escopo por segmento: só enxerga turma cuja série tem etapa='infantil' (ver
series.etapa em app/db.py) — os outros segmentos continuam usando o
Diagnóstico Adaptativo (app/modules/diagnostico.py). Visibilidade por papel
segue o mesmo desenho já usado em app/modules/turmas.py: direção, direção
pedagógica e psicopedagoga veem toda a Educação Infantil da escola;
coordenação só vê se não tiver segmento definido ou se o segmento dela for
'infantil'; professor só as turmas de infantil em que dá aula (via
professor_turma). Quem PODE REGISTRAR (criar) é mais restrito que quem pode
ver: professor, coordenação e direção/direção pedagógica — psicopedagoga só
visualiza, seu papel aqui é de acompanhamento, não de registro diário.

Arquivo em si: nunca fica em app/static (não pode ser público, é imagem/voz
de criança). Vive na camada app/storage.py (Supabase Storage privado em
produção, pasta local em desenvolvimento) e só é servido por
/infantil/arquivo/<id>, depois de repetir a mesma checagem de permissão da
tela de visualização — nunca por link direto ao arquivo.
"""
import os

from flask import Blueprint, render_template, request, redirect, url_for, flash, Response

from .. import storage
from ..db import get_db, new_id
from ..auth import login_obrigatorio, usuario_logado, escopo_etapa, PAPEIS_DIRECAO

bp = Blueprint("observacoes_infantil", __name__, url_prefix="/infantil")

# Nome do bucket no Supabase Storage (ver migration
# create_bucket_observacoes_infantil) — cada módulo que usa app/storage.py
# passa o próprio bucket em toda chamada, em vez da camada de storage ter um
# padrão fixo (ver app/modules/redacao.py para o segundo exemplo disso).
BUCKET = os.environ.get("SUPABASE_STORAGE_BUCKET", "observacoes-infantil")

PAPEIS_REGISTRO = ("professor", "coordenador") + PAPEIS_DIRECAO
PAPEIS_EQUIPE = ("professor", "coordenador", "psicopedagoga") + PAPEIS_DIRECAO
PAPEIS_ROTA_REGISTRO = PAPEIS_EQUIPE + ("familia",)

# Mesma lista de tipos aceita pelo bucket 'observacoes-infantil' no Supabase
# Storage (allowed_mime_types, ver migration create_bucket_observacoes_infantil)
# — mantidas iguais de propósito, para o erro aparecer aqui (mensagem
# amigável) em vez de só na resposta da API do Storage.
MIME_FOTO = {"image/jpeg", "image/png", "image/webp"}
MIME_AUDIO = {"audio/webm", "audio/mpeg", "audio/mp4", "audio/ogg"}
TAMANHO_MAXIMO_BYTES = 15 * 1024 * 1024  # 15 MB — mesmo limite do bucket


def _turmas_infantil_do_professor(db, usuario_id):
    return db.execute(
        "select t.id, t.nome, s.nome as serie_nome "
        "from turmas t join series s on s.id = t.serie_id "
        "join professor_turma pt on pt.turma_id = t.id "
        "join professores p on p.id = pt.professor_id "
        "where p.usuario_id = ? and s.etapa = 'infantil' order by t.nome",
        (usuario_id,),
    ).fetchall()


def _turmas_infantil_visiveis(db):
    u = usuario_logado()
    escola_id = u["escola_id"]

    if u["papel"] in ("coordenador", "psicopedagoga") or u["papel"] in PAPEIS_DIRECAO:
        segmento = escopo_etapa(u)
        if segmento and segmento != "infantil":
            return []
        return db.execute(
            "select t.id, t.nome, s.nome as serie_nome, "
            "(select count(*) from alunos a where a.turma_id = t.id) as total_alunos "
            "from turmas t join series s on s.id = t.serie_id "
            "where s.escola_id = ? and s.etapa = 'infantil' order by t.nome",
            (escola_id,),
        ).fetchall()

    turmas = _turmas_infantil_do_professor(db, u["id"])
    if not turmas:
        return []
    ids = [t["id"] for t in turmas]
    placeholders = ",".join("?" for _ in ids)
    return db.execute(
        f"select t.id, t.nome, s.nome as serie_nome, "
        f"(select count(*) from alunos a where a.turma_id = t.id) as total_alunos "
        f"from turmas t join series s on s.id = t.serie_id "
        f"where t.id in ({placeholders}) order by t.nome",
        tuple(ids),
    ).fetchall()


def _turma_infantil_visivel(db, turma_id):
    return next((t for t in _turmas_infantil_visiveis(db) if t["id"] == turma_id), None)


def _alunos_da_turma(db, turma_id):
    return db.execute(
        "select al.id, us.nome as nome "
        "from alunos al join usuarios us on us.id = al.usuario_id "
        "where al.turma_id = ? order by us.nome",
        (turma_id,),
    ).fetchall()


def _aluno_para_registro(db, aluno_id):
    """Confere que o aluno existe, está numa turma de infantil e que essa
    turma é visível para quem está logado — as três coisas que autorizam
    ver/criar um registro para ele."""
    row = db.execute(
        "select al.id, al.turma_id, us.nome as nome, t.nome as turma_nome "
        "from alunos al join usuarios us on us.id = al.usuario_id "
        "join turmas t on t.id = al.turma_id join series s on s.id = t.serie_id "
        "where al.id = ? and s.etapa = 'infantil'",
        (aluno_id,),
    ).fetchone()
    if not row:
        return None
    if not _turma_infantil_visivel(db, row["turma_id"]):
        return None
    return row


def _registro_visivel_equipe(db, obs_id):
    row = db.execute(
        "select o.*, us.nome as aluno_nome, t.nome as turma_nome, up.nome as professor_nome "
        "from observacoes_infantil o "
        "join alunos al on al.id = o.aluno_id join usuarios us on us.id = al.usuario_id "
        "join turmas t on t.id = o.turma_id join usuarios up on up.id = o.professor_usuario_id "
        "where o.id = ?",
        (obs_id,),
    ).fetchone()
    if not row or not _turma_infantil_visivel(db, row["turma_id"]):
        return None
    return row


def _registro_visivel_familia(db, obs_id):
    u = usuario_logado()
    return db.execute(
        "select o.*, us.nome as aluno_nome, t.nome as turma_nome "
        "from observacoes_infantil o "
        "join alunos al on al.id = o.aluno_id join usuarios us on us.id = al.usuario_id "
        "join turmas t on t.id = o.turma_id "
        "where o.id = ? and al.responsavel_usuario_id = ?",
        (obs_id, u["id"]),
    ).fetchone()


@bp.route("/")
@login_obrigatorio(papeis=PAPEIS_EQUIPE)
def index():
    db = get_db()
    turmas = _turmas_infantil_visiveis(db)
    return render_template("observacoes_infantil_index.html", turmas=turmas)


@bp.route("/turma/<turma_id>")
@login_obrigatorio(papeis=PAPEIS_EQUIPE)
def turma(turma_id):
    db = get_db()
    t = _turma_infantil_visivel(db, turma_id)
    if not t:
        flash("Turma não encontrada ou fora do seu acesso.", "erro")
        return redirect(url_for("observacoes_infantil.index"))

    alunos = _alunos_da_turma(db, turma_id)
    registros = db.execute(
        "select o.*, us.nome as aluno_nome, up.nome as professor_nome "
        "from observacoes_infantil o "
        "join alunos al on al.id = o.aluno_id join usuarios us on us.id = al.usuario_id "
        "join usuarios up on up.id = o.professor_usuario_id "
        "where o.turma_id = ? order by o.criado_em desc limit 30",
        (turma_id,),
    ).fetchall()
    pode_registrar = usuario_logado()["papel"] in PAPEIS_REGISTRO
    return render_template(
        "observacoes_infantil_turma.html", turma=t, alunos=alunos, registros=registros, pode_registrar=pode_registrar
    )


@bp.route("/aluno/<aluno_id>/novo", methods=["GET", "POST"])
@login_obrigatorio(papeis=PAPEIS_REGISTRO)
def novo(aluno_id):
    db = get_db()
    aluno = _aluno_para_registro(db, aluno_id)
    if not aluno:
        flash("Aluno não encontrado ou fora do seu acesso.", "erro")
        return redirect(url_for("observacoes_infantil.index"))

    if request.method == "POST":
        tipo = request.form.get("tipo", "")
        legenda = request.form.get("legenda", "").strip() or None
        arquivo = request.files.get("arquivo")

        erro = None
        content_type = ""
        if tipo not in ("foto", "audio"):
            erro = "Selecione se este registro é uma foto ou um áudio."
        elif not arquivo or not arquivo.filename:
            erro = "Anexe uma foto ou grave um áudio antes de enviar."
        else:
            # Descarta parâmetros do tipo MIME (ex.: "audio/webm;codecs=opus",
            # comum em áudio gravado no próprio navegador) antes de comparar —
            # o que importa aqui é o formato, não o codec.
            content_type = (arquivo.mimetype or "").split(";")[0].strip().lower()
            mimes_aceitos = MIME_FOTO if tipo == "foto" else MIME_AUDIO
            if content_type not in mimes_aceitos:
                erro = "Formato de arquivo não reconhecido — tire a foto ou grave o áudio novamente."

        conteudo = b""
        if not erro:
            conteudo = arquivo.read()
            if len(conteudo) > TAMANHO_MAXIMO_BYTES:
                erro = "Arquivo maior que o permitido (15 MB) — tente um registro mais curto."

        if erro:
            flash(erro, "erro")
            return render_template("observacoes_infantil_novo.html", aluno=aluno)

        nome_original = arquivo.filename or ""
        extensao = nome_original.rsplit(".", 1)[-1].lower() if "." in nome_original else ("jpg" if tipo == "foto" else "webm")
        caminho = f"{usuario_logado()['escola_id']}/{aluno_id}/{new_id()}.{extensao}"

        try:
            storage.salvar(BUCKET, caminho, conteudo, content_type)
        except storage.ErroArmazenamento:
            flash("Não foi possível salvar o arquivo agora. Tente novamente em instantes.", "erro")
            return render_template("observacoes_infantil_novo.html", aluno=aluno)

        db.execute(
            "insert into observacoes_infantil "
            "(id, aluno_id, turma_id, professor_usuario_id, tipo, arquivo_caminho, arquivo_content_type, legenda) "
            "values (?,?,?,?,?,?,?,?)",
            (new_id(), aluno_id, aluno["turma_id"], usuario_logado()["id"], tipo, caminho, content_type, legenda),
        )
        db.commit()
        flash(f"Registro de {aluno['nome']} salvo.", "ok")
        return redirect(url_for("observacoes_infantil.turma", turma_id=aluno["turma_id"]))

    return render_template("observacoes_infantil_novo.html", aluno=aluno)


@bp.route("/registro/<obs_id>")
@login_obrigatorio(papeis=PAPEIS_ROTA_REGISTRO)
def registro(obs_id):
    db = get_db()
    u = usuario_logado()
    if u["papel"] == "familia":
        r = _registro_visivel_familia(db, obs_id)
        voltar = url_for("observacoes_infantil.familia_aluno", aluno_id=r["aluno_id"]) if r else url_for("observacoes_infantil.familia_index")
    else:
        r = _registro_visivel_equipe(db, obs_id)
        voltar = url_for("observacoes_infantil.turma", turma_id=r["turma_id"]) if r else url_for("observacoes_infantil.index")
    if not r:
        flash("Registro não encontrado ou fora do seu acesso.", "erro")
        return redirect(voltar)
    return render_template("observacoes_infantil_registro.html", r=r, voltar=voltar)


@bp.route("/arquivo/<obs_id>")
@login_obrigatorio(papeis=PAPEIS_ROTA_REGISTRO)
def arquivo(obs_id):
    db = get_db()
    u = usuario_logado()
    if u["papel"] == "familia":
        r = _registro_visivel_familia(db, obs_id)
    else:
        r = _registro_visivel_equipe(db, obs_id)
    if not r:
        flash("Registro não encontrado ou fora do seu acesso.", "erro")
        return redirect(url_for("observacoes_infantil.index"))

    if storage.MODO_SUPABASE:
        try:
            url_temp = storage.url_assinada(BUCKET, r["arquivo_caminho"])
        except storage.ErroArmazenamento:
            flash("Não foi possível carregar o arquivo agora. Tente novamente em instantes.", "erro")
            return redirect(url_for("observacoes_infantil.index"))
        return redirect(url_temp)

    try:
        conteudo = storage.ler_local(BUCKET, r["arquivo_caminho"])
    except storage.ErroArmazenamento:
        flash("Arquivo não encontrado — pode ter sido perdido num reinício do ambiente de teste.", "erro")
        return redirect(url_for("observacoes_infantil.index"))
    return Response(conteudo, mimetype=r["arquivo_content_type"])


# ---------------------------------------------------------------------------
# Visão da família — feed de leitura, sem nenhuma ação de registrar/editar.
# Mesma filosofia de app.modules.relatorios_familia: só enxerga o(s) aluno(s)
# onde é responsavel_usuario_id, nunca a turma inteira.
# ---------------------------------------------------------------------------
def _alunos_infantil_da_familia(db):
    u = usuario_logado()
    return db.execute(
        "select al.id, us.nome as nome, t.nome as turma_nome "
        "from alunos al join usuarios us on us.id = al.usuario_id "
        "join turmas t on t.id = al.turma_id join series s on s.id = t.serie_id "
        "where al.responsavel_usuario_id = ? and s.etapa = 'infantil' order by us.nome",
        (u["id"],),
    ).fetchall()


def _aluno_infantil_da_familia(db, aluno_id):
    u = usuario_logado()
    return db.execute(
        "select al.id, us.nome as nome, t.nome as turma_nome "
        "from alunos al join usuarios us on us.id = al.usuario_id "
        "join turmas t on t.id = al.turma_id join series s on s.id = t.serie_id "
        "where al.id = ? and al.responsavel_usuario_id = ? and s.etapa = 'infantil'",
        (aluno_id, u["id"]),
    ).fetchone()


@bp.route("/familia")
@login_obrigatorio(papeis=["familia"])
def familia_index():
    db = get_db()
    alunos = _alunos_infantil_da_familia(db)
    if len(alunos) == 1:
        return redirect(url_for("observacoes_infantil.familia_aluno", aluno_id=alunos[0]["id"]))
    return render_template("observacoes_infantil_familia_index.html", alunos=alunos)


@bp.route("/familia/aluno/<aluno_id>")
@login_obrigatorio(papeis=["familia"])
def familia_aluno(aluno_id):
    db = get_db()
    aluno = _aluno_infantil_da_familia(db, aluno_id)
    if not aluno:
        flash("Aluno não encontrado ou não vinculado à sua conta.", "erro")
        return redirect(url_for("observacoes_infantil.familia_index"))
    registros = db.execute(
        "select * from observacoes_infantil where aluno_id = ? order by criado_em desc",
        (aluno_id,),
    ).fetchall()
    return render_template("observacoes_infantil_familia_aluno.html", aluno=aluno, registros=registros)
