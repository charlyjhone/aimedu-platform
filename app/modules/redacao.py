"""
Módulo do AIM.Edu: Redação (correção estilo ENEM).

O aluno envia uma FOTO da redação manuscrita (decisão do usuário — nunca
mais digita o texto na tela, "sem digitação obrigatória" no mesmo espírito
do M7.1/Educação Infantil). A tabela 'redacoes' já existia no schema desde
o início do projeto, mas ganhou colunas novas para isso (ver migration
redacoes_envio_por_foto): 'arquivo_caminho'/'arquivo_content_type' (onde a
foto está — bucket privado 'redacoes' no Supabase Storage, ver
app/storage.py) e 'status'.

Correção pendente até um provedor de IA real: hoje NENHUMA correção
automática roda mais no envio — a IA que "segue fielmente" os critérios do
ENEM e faz a mentoria do aluno depende de um provedor com visão (o usuário
decidiu que será o Gemini, no futuro — ver PROVEDOR_ATIVO em
app/ai_engine.py) para ler a letra manuscrita direto da foto. Até essa
chave existir, toda redação nasce com status='aguardando_ia' e
nota_c1..c5/feedback_ia ficam NULL — a tela de resultado mostra um aviso
nesse lugar, mesmo padrão do M7.2 (documentação pedagógica do Infantil).
Quando o Gemini for conectado, o preenchimento desses campos (e o alerta de
nota baixa pro Radar da Coordenação, hoje removido daqui por não haver mais
nota calculada no envio) volta a acontecer nesse momento — em lote ou por
webhook, sem precisar mudar as telas do aluno.
"""
from flask import Blueprint, render_template, redirect, url_for, request, flash, Response

from .. import storage
from ..db import get_db, new_id
from ..auth import login_obrigatorio, usuario_logado

bp = Blueprint("redacao", __name__, url_prefix="/redacao")

# Nome do bucket no Supabase Storage (ver migration create_bucket_redacoes)
# — cada módulo que usa app/storage.py passa o próprio bucket, ver também
# app/modules/observacoes_infantil.py.
BUCKET = "redacoes"

MIME_FOTO = {"image/jpeg", "image/png", "image/webp"}
TAMANHO_MAXIMO_BYTES = 15 * 1024 * 1024  # 15 MB — mesmo limite do bucket


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
    u = usuario_logado()
    aluno = _aluno_atual(db)

    tema = request.form.get("tema", "").strip() or None
    arquivo = request.files.get("arquivo")

    erro = None
    content_type = ""
    if not arquivo or not arquivo.filename:
        erro = "Tire uma foto da sua redação antes de enviar."
    else:
        # Descarta parâmetros do tipo MIME antes de comparar (mesmo cuidado
        # de app/modules/observacoes_infantil.py) — o que importa é o
        # formato da imagem, não detalhes do codec/variante.
        content_type = (arquivo.mimetype or "").split(";")[0].strip().lower()
        if content_type not in MIME_FOTO:
            erro = "Formato de imagem não reconhecido — tire a foto novamente."

    conteudo = b""
    if not erro:
        conteudo = arquivo.read()
        if len(conteudo) > TAMANHO_MAXIMO_BYTES:
            erro = "Arquivo maior que o permitido (15 MB) — tire a foto novamente com menos resolução."

    if erro:
        flash(erro, "erro")
        return render_template("redacao_form.html", form={"tema": tema or ""})

    nome_original = arquivo.filename or ""
    extensao = nome_original.rsplit(".", 1)[-1].lower() if "." in nome_original else "jpg"
    caminho = f"{u['escola_id']}/{aluno['id']}/{new_id()}.{extensao}"

    try:
        storage.salvar(BUCKET, caminho, conteudo, content_type)
    except storage.ErroArmazenamento:
        flash("Não foi possível salvar a foto agora. Tente novamente em instantes.", "erro")
        return render_template("redacao_form.html", form={"tema": tema or ""})

    redacao_id = new_id()
    db.execute(
        "insert into redacoes (id, aluno_id, tema, arquivo_caminho, arquivo_content_type) "
        "values (?,?,?,?,?)",
        (redacao_id, aluno["id"], tema, caminho, content_type),
    )
    db.commit()

    flash("Redação enviada — assim que a correção por IA estiver disponível, o resultado aparece aqui.", "ok")
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


@bp.route("/<redacao_id>/arquivo")
@login_obrigatorio(papeis=["aluno"])
def arquivo(redacao_id):
    db = get_db()
    aluno = _aluno_atual(db)
    redacao = db.execute(
        "select arquivo_caminho, arquivo_content_type from redacoes where id = ? and aluno_id = ?",
        (redacao_id, aluno["id"]),
    ).fetchone()
    if not redacao or not redacao["arquivo_caminho"]:
        flash("Foto não encontrada.", "erro")
        return redirect(url_for("redacao.index"))

    if storage.MODO_SUPABASE:
        try:
            url_temp = storage.url_assinada(BUCKET, redacao["arquivo_caminho"])
        except storage.ErroArmazenamento:
            flash("Não foi possível carregar a foto agora. Tente novamente em instantes.", "erro")
            return redirect(url_for("redacao.index"))
        return redirect(url_temp)

    try:
        conteudo = storage.ler_local(BUCKET, redacao["arquivo_caminho"])
    except storage.ErroArmazenamento:
        flash("Foto não encontrada — pode ter sido perdida num reinício do ambiente de teste.", "erro")
        return redirect(url_for("redacao.index"))
    return Response(conteudo, mimetype=redacao["arquivo_content_type"])
