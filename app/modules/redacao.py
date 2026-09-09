"""
Módulo do AIM.Edu: Redação (correção estilo ENEM).

O aluno envia uma FOTO da redação manuscrita (decisão do usuário — nunca
mais digita o texto na tela, "sem digitação obrigatória" no mesmo espírito
do M7.1/Educação Infantil). A tabela 'redacoes' já existia no schema desde
o início do projeto, mas ganhou colunas novas para isso (ver migration
redacoes_envio_por_foto): 'arquivo_caminho'/'arquivo_content_type' (onde a
foto está — bucket privado 'redacoes' no Supabase Storage, ver
app/storage.py) e 'status'.

Correção por IA (versão 2, ligada em 2026-09-09): ao enviar a foto, esta
rota tenta, na hora, (1) transcrever a redação com o Agente 12 (OCR por
visão — ver app/agents/agente.py) e (2) corrigi-la com o "time invisível"
de agentes 2 a 9 (ver app/orchestrator/corretor.py). Se QUALQUER uma das
duas etapas falhar (sem ANTHROPIC_API_KEY configurada, erro de rede, JSON
inválido, etc.), a redação SEMPRE fica salva e visível — só permanece com
status='aguardando_ia' e nota_c1..c5/feedback_ia ficam NULL, exatamente
como já acontecia antes desta versão. Ou seja: sem a chave configurada no
ambiente, o comportamento é idêntico ao de antes (nenhuma quebra).

Este módulo continua independente de app/ai_engine.py — aquele arquivo
segue existindo, intocado, como a implementação "v1" (nunca chamada por
ninguém). corrigir_redacao() usada aqui é a de app/orchestrator/corretor.py.
"""
import logging

from flask import Blueprint, jsonify, render_template, redirect, url_for, request, flash, Response

from .. import storage
from ..agents import agente
from ..auth import login_obrigatorio, usuario_logado, PAPEIS_DIRECAO
from ..db import get_db, new_id
from ..orchestrator.corretor import ErroCorrecao, corrigir_redacao
from .calendario import _segmento_do_usuario

bp = Blueprint("redacao", __name__, url_prefix="/redacao")

_log = logging.getLogger(__name__)

# Nome do bucket no Supabase Storage (ver migration create_bucket_redacoes)
# — cada módulo que usa app/storage.py passa o próprio bucket, ver também
# app/modules/observacoes_infantil.py.
BUCKET = "redacoes"

MIME_FOTO = {"image/jpeg", "image/png", "image/webp"}
TAMANHO_MAXIMO_BYTES = 15 * 1024 * 1024  # 15 MB — mesmo limite do bucket


def _aluno_atual(db):
    u = usuario_logado()
    return db.execute("select * from alunos where usuario_id = ?", (u["id"],)).fetchone()


def _bloqueio_se_nao_medio(db):
    """Redação é só para o Ensino Médio (decisão do usuário em 2026-09-09).
    O menu já esconde o link pra quem não é do médio (ver _injetar_layout
    em app/__init__.py), mas isso sozinho não impede acesso direto por URL
    — quem chamar uma rota deste módulo deve checar isto primeiro e, se vier
    algo diferente de None, devolver esse valor direto (é a resposta de
    redirecionamento já pronta)."""
    u = usuario_logado()
    if _segmento_do_usuario(db, u) != "medio":
        flash("A Redação está disponível apenas para o Ensino Médio.", "erro")
        return redirect(url_for("auth.painel"))
    return None


@bp.route("/")
@login_obrigatorio(papeis=["aluno"])
def index():
    db = get_db()
    bloqueio = _bloqueio_se_nao_medio(db)
    if bloqueio:
        return bloqueio
    aluno = _aluno_atual(db)
    redacoes = db.execute(
        "select * from redacoes where aluno_id = ? order by criado_em desc",
        (aluno["id"],),
    ).fetchall()
    return render_template("redacao_index.html", redacoes=redacoes)


@bp.route("/nova")
@login_obrigatorio(papeis=["aluno"])
def nova():
    bloqueio = _bloqueio_se_nao_medio(get_db())
    if bloqueio:
        return bloqueio
    return render_template("redacao_form.html")


@bp.route("/enviar", methods=["POST"])
@login_obrigatorio(papeis=["aluno"])
def enviar():
    db = get_db()
    bloqueio = _bloqueio_se_nao_medio(db)
    if bloqueio:
        return bloqueio
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

    # Correção automática, na hora — best-effort. QUALQUER falha aqui (sem
    # ANTHROPIC_API_KEY, rede fora, JSON malformado, etc.) é engolida por
    # _tentar_corrigir_automaticamente: a redação já está salva acima e
    # continua com status='aguardando_ia', exatamente como antes desta
    # versão. Nunca deixe uma falha de IA impedir o redirect abaixo.
    corrigida = _tentar_corrigir_automaticamente(db, redacao_id, tema or "", conteudo, content_type)

    if corrigida:
        flash("Redação enviada e corrigida — confira o resultado abaixo.", "ok")
    else:
        flash("Redação enviada — assim que a correção por IA estiver disponível, o resultado aparece aqui.", "ok")
    return redirect(url_for("redacao.resultado", redacao_id=redacao_id))


def _tentar_corrigir_automaticamente(db, redacao_id: str, tema: str, foto_bytes: bytes, content_type: str) -> bool:
    """Tenta transcrever (Agente 12) e corrigir (corrigir_redacao) a
    redação recém-enviada, e já atualiza a linha no banco se der certo.
    Devolve True se a redação terminou com status='corrigida', False se
    ficou (ou continuou) 'aguardando_ia' por qualquer motivo — nunca
    levanta exceção para quem chamou."""
    try:
        imagem_base64 = agente.codificar_imagem_para_base64(foto_bytes)
        resultado_ocr, _meta = agente.chamar_agente_12(imagem_base64, imagem_media_type=content_type)
        texto_transcrito = (resultado_ocr or {}).get("texto_transcrito", "").strip()
        if not texto_transcrito:
            return False

        resultado = corrigir_redacao(tema, texto_transcrito, redacao_id=redacao_id)

        db.execute(
            "update redacoes set texto = ?, status = 'corrigida', "
            "nota_c1 = ?, nota_c2 = ?, nota_c3 = ?, nota_c4 = ?, nota_c5 = ?, "
            "nota_ponderada = ?, feedback_ia = ? where id = ?",
            (
                texto_transcrito,
                resultado["nota_c1"], resultado["nota_c2"], resultado["nota_c3"],
                resultado["nota_c4"], resultado["nota_c5"], resultado["nota_ponderada"],
                resultado["feedback_ia"], redacao_id,
            ),
        )
        db.commit()
        return True
    except (agente.ErroAgenteIA, ErroCorrecao) as e:
        _log.warning("Correção automática da redação %s não completou: %s", redacao_id, e)
        return False
    except Exception:
        # Best-effort de verdade: um bug aqui nunca pode derrubar o envio
        # da redação em si. Se isto disparar demais em produção, é sinal de
        # que vale investigar via logging.exception() antes deste except.
        _log.exception("Erro inesperado na correção automática da redação %s", redacao_id)
        return False


@bp.route("/<redacao_id>")
@login_obrigatorio(papeis=["aluno"])
def resultado(redacao_id):
    db = get_db()
    bloqueio = _bloqueio_se_nao_medio(db)
    if bloqueio:
        return bloqueio
    aluno = _aluno_atual(db)
    redacao = db.execute(
        "select * from redacoes where id = ? and aluno_id = ?",
        (redacao_id, aluno["id"]),
    ).fetchone()
    if not redacao:
        flash("Redação não encontrada.", "erro")
        return redirect(url_for("redacao.index"))

    # nota_ponderada é a nota canônica (decisão do usuário em 2026-09-09,
    # ver app/orchestrator/corretor.py) — guardada na coluna no momento da
    # correção, não recalculada aqui, para não mudar retroativamente a nota
    # de uma redação já corrigida se os pesos entre competências mudarem.
    nota_ponderada = redacao["nota_ponderada"]
    return render_template("redacao_resultado.html", r=redacao, nota_ponderada=nota_ponderada)


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


@bp.route("/teste-corrigir", methods=["POST"])
@login_obrigatorio(papeis=["coordenador"] + list(PAPEIS_DIRECAO))
def teste_corrigir():
    """Rota de teste ISOLADA para validar o "time invisível" de agentes com
    texto DIGITADO (sem foto, sem OCR, sem gravar nada no banco) — pensada
    para testar a qualidade da correção antes de confiar nela no fluxo real
    do aluno. Aceita POST com 'tema' e 'texto' (form ou JSON) e devolve o
    JSON da correção.

    Restrita a coordenação/direção de propósito: cada chamada gasta
    créditos reais de API — não deixamos ao alcance do aluno."""
    dados = request.get_json(silent=True) or request.form
    tema = (dados.get("tema") or "").strip()
    texto = (dados.get("texto") or "").strip()

    if not texto:
        return jsonify({"erro": "Envie 'texto' (a redação digitada) no corpo do POST."}), 400

    try:
        resultado = corrigir_redacao(tema, texto)
    except ErroCorrecao as e:
        return jsonify({"erro": str(e)}), 502

    return jsonify(resultado)
