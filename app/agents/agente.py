"""
Funções que chamam cada um dos 12 agentes do "time invisível" do AIM.Edu —
especificação completa recebida do usuário em 2026-09-09 (ver conversa; não
existe nenhum documento no Google Drive do projeto com esta arquitetura,
ela foi descrita diretamente pelo usuário).

Cada `chamar_agente_N` carrega o prompt-base do agente N (arquivo em
app/prompts/), monta a mensagem com a "entrada" específica daquele agente
(tema, texto, último parágrafo, imagem, etc.) e chama a API da Anthropic.

DECISÃO DE IMPLEMENTAÇÃO (sinalizada ao usuário): em vez de instalar o
pacote `anthropic` (SDK oficial), esta camada fala direto com a API REST da
Anthropic usando só `urllib` da biblioteca padrão — mesma filosofia de
dependências mínimas já documentada em app/storage.py ("mesma filosofia de
dependências mínimas já usada no resto do projeto"). Troca fácil pelo SDK
oficial depois, se preferirem.

Modelos: configuráveis por variável de ambiente. ATENÇÃO (confirmado com o
usuário em 2026-09-09): os IDs pedidos originalmente na especificação —
"claude-3-sonnet-20240229" e "claude-3-opus-20240229" — estão APOSENTADOS
(retired) pela Anthropic (sonnet em 21/07/2025, opus em 05/01/2026) e
qualquer chamada a eles falha direto. Os padrões abaixo já foram
atualizados para os modelos atuais (checados em platform.claude.com em
2026-09-09: claude-sonnet-5 a US$2/US$10 por milhão de tokens
entrada/saída; claude-opus-5 a US$5/US$25). Se a Anthropic lançar um
modelo mais novo depois, troque só a variável de ambiente — não é
preciso mexer neste arquivo.
"""
import base64
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

# Modelo usado pelos agentes de texto "comuns" (2,3,4,5,7,8,9,10,11).
MODELO_TEXTO = os.environ.get("ANTHROPIC_MODEL_TEXTO", "claude-sonnet-5")
# Agente 6 é a "autoridade mundial" em C5 — usa o modelo mais forte.
MODELO_C5 = os.environ.get("ANTHROPIC_MODEL_C5", "claude-opus-5")
# Agente 12 (OCR) precisa de visão — todos os modelos atuais da Anthropic
# leem imagem pelo mesmo preço de texto (ver platform.claude.com/docs/en/models/overview),
# então não há motivo pra pagar o preço do Opus só pela visão — Sonnet 5 basta.
MODELO_VISAO = os.environ.get("ANTHROPIC_MODEL_VISAO", "claude-sonnet-5")

PASTA_PROMPTS = Path(__file__).resolve().parent.parent / "prompts"

_CACHE_PROMPTS: dict[str, str] = {}


class ErroAgenteIA(Exception):
    """Erro ao chamar um agente — falha de rede/API ou resposta que não veio
    em JSON válido. Quem chama decide se trata como falha parcial (essa
    competência fica sem nota) ou propaga."""

    def __init__(self, mensagem: str, *, resposta_bruta: str = ""):
        super().__init__(mensagem)
        self.resposta_bruta = resposta_bruta


def _carregar_prompt(nome_arquivo: str) -> str:
    if nome_arquivo not in _CACHE_PROMPTS:
        caminho = PASTA_PROMPTS / nome_arquivo
        _CACHE_PROMPTS[nome_arquivo] = caminho.read_text(encoding="utf-8")
    return _CACHE_PROMPTS[nome_arquivo]


def _extrair_json(texto_resposta: str) -> dict:
    """Os modelos às vezes embrulham o JSON em ```json ... ``` apesar da
    instrução de responder só com JSON — tira a casca antes de tentar
    decodificar, e usa o primeiro '{' e o último '}' como fallback."""
    texto = texto_resposta.strip()
    texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto.strip(), flags=re.IGNORECASE)
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        inicio, fim = texto.find("{"), texto.rfind("}")
        if inicio != -1 and fim != -1 and fim > inicio:
            try:
                return json.loads(texto[inicio:fim + 1])
            except json.JSONDecodeError:
                pass
    raise ErroAgenteIA("Resposta do agente não veio em JSON válido.", resposta_bruta=texto_resposta)


def _chamar_claude(
    system_prompt: str,
    mensagem_usuario: str,
    *,
    modelo: str,
    max_tokens: int = 1500,
    imagem_base64: str | None = None,
    imagem_media_type: str = "image/jpeg",
    timeout: int = 60,
) -> tuple[dict, dict]:
    """Chama a API de mensagens da Anthropic e devolve (json_decodificado,
    metadados) — metadados traz modelo, tokens de entrada/saída e duração
    em ms, para alimentar o registro em app.orchestrator.corretor.

    Levanta ErroAgenteIA em qualquer falha (rede, HTTP, JSON inválido)."""
    if not ANTHROPIC_API_KEY:
        raise ErroAgenteIA(
            "ANTHROPIC_API_KEY não está definida no ambiente — configure-a "
            "como variável de ambiente do serviço (nunca em arquivo "
            "commitado), ver .env.example."
        )

    conteudo_usuario = [{"type": "text", "text": mensagem_usuario}]
    if imagem_base64:
        conteudo_usuario.insert(0, {
            "type": "image",
            "source": {"type": "base64", "media_type": imagem_media_type, "data": imagem_base64},
        })

    corpo = json.dumps({
        "model": modelo,
        "max_tokens": max_tokens,
        "system": system_prompt,
        "messages": [{"role": "user", "content": conteudo_usuario}],
    }).encode("utf-8")

    req = urllib.request.Request(
        ANTHROPIC_API_URL,
        data=corpo,
        method="POST",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
    )

    inicio = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resposta = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detalhe = e.read().decode("utf-8", errors="replace")
        raise ErroAgenteIA(f"Erro HTTP {e.code} da API da Anthropic: {detalhe}") from e
    except urllib.error.URLError as e:
        raise ErroAgenteIA(f"Falha de rede ao chamar a API da Anthropic: {e}") from e
    duracao_ms = int((time.monotonic() - inicio) * 1000)

    blocos_texto = [b["text"] for b in resposta.get("content", []) if b.get("type") == "text"]
    texto_resposta = "\n".join(blocos_texto)
    uso = resposta.get("usage", {})

    metadados = {
        "modelo": modelo,
        "tokens_entrada": uso.get("input_tokens"),
        "tokens_saida": uso.get("output_tokens"),
        "duracao_ms": duracao_ms,
        "resposta_bruta": texto_resposta,
    }
    return _extrair_json(texto_resposta), metadados


# ---------------------------------------------------------------------------
# Agente 1 — Curador de Temas (roda ANTES de o aluno escrever; não é chamado
# por corrigir_redacao hoje — ver flag na resposta ao usuário).
# ---------------------------------------------------------------------------
def chamar_agente_1(tema: str) -> tuple[dict, dict]:
    system = _carregar_prompt("agente_01_curador_de_temas.txt")
    mensagem = f"TEMA DA REDAÇÃO: {tema}"
    return _chamar_claude(system, mensagem, modelo=MODELO_TEXTO, max_tokens=1800)


def chamar_agente_2(texto: str) -> tuple[dict, dict]:
    system = _carregar_prompt("agente_02_c1_norma_padrao.txt")
    mensagem = f"TEXTO DO ALUNO:\n{texto}"
    return _chamar_claude(system, mensagem, modelo=MODELO_TEXTO, max_tokens=1500)


def chamar_agente_3(texto: str, tema: str = "") -> tuple[dict, dict]:
    system = _carregar_prompt("agente_03_c2_repertorio.txt")
    mensagem = f"TEMA DA REDAÇÃO: {tema}\n\nTEXTO DO ALUNO:\n{texto}"
    return _chamar_claude(system, mensagem, modelo=MODELO_TEXTO, max_tokens=1200)


def chamar_agente_4(texto: str) -> tuple[dict, dict]:
    system = _carregar_prompt("agente_04_c3_argumentacao.txt")
    mensagem = f"TEXTO DO ALUNO:\n{texto}"
    return _chamar_claude(system, mensagem, modelo=MODELO_TEXTO, max_tokens=1000)


def chamar_agente_5(texto: str) -> tuple[dict, dict]:
    system = _carregar_prompt("agente_05_c4_coesao.txt")
    mensagem = f"TEXTO DO ALUNO:\n{texto}"
    return _chamar_claude(system, mensagem, modelo=MODELO_TEXTO, max_tokens=1000)


def chamar_agente_6(ultimo_paragrafo: str) -> tuple[dict, dict]:
    system = _carregar_prompt("agente_06_c5_intervencao.txt")
    mensagem = f"ÚLTIMO PARÁGRAFO DA REDAÇÃO (proposta de intervenção):\n{ultimo_paragrafo}"
    return _chamar_claude(system, mensagem, modelo=MODELO_C5, max_tokens=1200)


def chamar_agente_7(tese: str) -> tuple[dict, dict]:
    system = _carregar_prompt("agente_07_inquisidor_socratico.txt")
    mensagem = f"TESE DO ALUNO (frase inicial):\n{tese}"
    return _chamar_claude(system, mensagem, modelo=MODELO_TEXTO, max_tokens=600)


def chamar_agente_8(tema: str) -> tuple[dict, dict]:
    system = _carregar_prompt("agente_08_repertorios_coringa.txt")
    mensagem = f"TEMA DA REDAÇÃO: {tema}"
    return _chamar_claude(system, mensagem, modelo=MODELO_TEXTO, max_tokens=1800)


def chamar_agente_9(texto: str) -> tuple[dict, dict]:
    system = _carregar_prompt("agente_09_simulador_corretor.txt")
    mensagem = f"TEXTO COMPLETO DO ALUNO:\n{texto}"
    return _chamar_claude(system, mensagem, modelo=MODELO_TEXTO, max_tokens=600)


# ---------------------------------------------------------------------------
# Agentes 10 e 11 — marcados pelo próprio usuário como "não usado ainda" /
# "versão futura". Implementados por completo (mesmo contrato dos demais)
# mas não chamados por app.orchestrator.corretor.corrigir_redacao nesta v1.
# ---------------------------------------------------------------------------
def chamar_agente_10(numero_redacao: int) -> tuple[dict, dict]:
    system = _carregar_prompt("agente_10_treinador_esquecimento.txt")
    mensagem = f"Esta é a {numero_redacao}ª redação deste aluno no AIM.Edu."
    return _chamar_claude(system, mensagem, modelo=MODELO_TEXTO, max_tokens=300)


def chamar_agente_11(ultima_correcao_c5: str) -> tuple[dict, dict]:
    system = _carregar_prompt("agente_11_apagador_memorias.txt")
    mensagem = f"ÚLTIMA CORREÇÃO DE C5 (intervenção):\n{ultima_correcao_c5}"
    return _chamar_claude(system, mensagem, modelo=MODELO_TEXTO, max_tokens=400)


def chamar_agente_12(imagem_base64: str, imagem_media_type: str = "image/jpeg") -> tuple[dict, dict]:
    """OCR por visão computacional. 'imagem_base64' é a foto da redação já
    codificada em base64 (sem o prefixo 'data:image/...;base64,').

    Não é chamado por corrigir_redacao(tema, texto) — essa função já recebe
    o texto pronto. Este agente é o passo ANTERIOR, que só faz sentido no
    fluxo de app/modules/redacao.py, antes de existir um 'texto' para
    passar à correção (ver flag na resposta ao usuário)."""
    system = _carregar_prompt("agente_12_leitor_caligrafia.txt")
    mensagem = "Transcreva a redação manuscrita na imagem anexada."
    return _chamar_claude(
        system, mensagem, modelo=MODELO_VISAO, max_tokens=2000,
        imagem_base64=imagem_base64, imagem_media_type=imagem_media_type,
    )


def codificar_imagem_para_base64(conteudo_bytes: bytes) -> str:
    """Utilitário pequeno para quem for plugar o Agente 12 depois — a
    função já existe aqui para não obrigar quem chamar a importar base64
    diretamente."""
    return base64.b64encode(conteudo_bytes).decode("ascii")
