"""
Camada de armazenamento de arquivos do AIM.Edu — usada pelo M7.1 (Educação
Infantil, app/modules/observacoes_infantil.py, bucket 'observacoes-infantil')
e pelo envio de redação por foto (app/modules/redacao.py, bucket 'redacoes').
Escrita como camada própria (mesmo espírito de app/db.py) para qualquer
módulo futuro que precise guardar foto/áudio/vídeo reaproveitar sem duplicar
a lógica de "onde o arquivo mora de verdade" — cada módulo só passa o nome
do seu próprio bucket em cada chamada.

Dois modos, escolhidos automaticamente pelas variáveis de ambiente:

  - MODO SUPABASE (produção): quando SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY
    estão definidas, os arquivos vão para um bucket PRIVADO no Supabase
    Storage (um por módulo — ver migrations create_bucket_observacoes_infantil
    e create_bucket_redacoes, ambos com public=false). A chave service_role
    só existe como variável de ambiente do servidor (Render), nunca em
    código nem em chat — é o mesmo tratamento que DATABASE_URL já recebe.
    Ela nunca chega ao navegador: toda leitura passa por uma URL assinada de
    curta duração (ver url_assinada), gerada sob demanda por cada módulo
    depois de conferir que quem está pedindo tem permissão para ver aquele
    registro específico.

  - MODO LOCAL (desenvolvimento, sem essas variáveis): os arquivos vão para
    a pasta instance/storage/<bucket>/ deste projeto, fora de app/static
    (então não ficam acessíveis por URL direta, sem passar pela checagem de
    permissão da rota — nem em desenvolvimento).

Importante sobre o disco do Render: um Web Service ali NÃO tem disco
persistente por padrão — o filesystem é recriado a cada deploy. Por isso a
produção precisa estar sempre em MODO SUPABASE; o modo local só é seguro
para demonstração/teste, onde perder os arquivos ao reiniciar não é grave.

Usa só a biblioteca padrão (urllib) para falar com a API REST do Supabase
Storage, em vez de adicionar um novo pacote (supabase-py) só para isto —
mesma filosofia de dependências mínimas já usada no resto do projeto
(requirements.txt).
"""
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

MODO_SUPABASE = bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)

PASTA_LOCAL = Path(__file__).resolve().parent.parent / "instance" / "storage"


class ErroArmazenamento(Exception):
    """Erro genérico ao salvar ou ler um arquivo — quem chama trata mostrando
    uma mensagem amigável, nunca o traceback bruto pro usuário final."""


def salvar(bucket: str, caminho: str, conteudo: bytes, content_type: str) -> None:
    """Grava o arquivo no backend ativo, dentro do bucket indicado. 'caminho'
    é a chave relativa que quem chama já decidiu (ex.:
    '<escola_id>/<aluno_id>/<uuid>.jpg') — esta função só sabe gravar, não
    decide nomes nem bucket padrão."""
    if MODO_SUPABASE:
        url = f"{SUPABASE_URL}/storage/v1/object/{bucket}/{caminho}"
        req = urllib.request.Request(
            url,
            data=conteudo,
            method="POST",
            headers={
                "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                "apikey": SUPABASE_SERVICE_ROLE_KEY,
                "Content-Type": content_type,
                "x-upsert": "true",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp.read()
        except (urllib.error.HTTPError, urllib.error.URLError) as e:
            raise ErroArmazenamento(f"Falha ao enviar arquivo ao Supabase Storage: {e}") from e
        return

    destino = PASTA_LOCAL / bucket / caminho
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(conteudo)


def ler_local(bucket: str, caminho: str) -> bytes:
    """Só usada em MODO LOCAL — a rota que serve o arquivo já conferiu
    permissão antes de chamar isto."""
    try:
        return (PASTA_LOCAL / bucket / caminho).read_bytes()
    except OSError as e:
        raise ErroArmazenamento(f"Arquivo local não encontrado: {e}") from e


def url_assinada(bucket: str, caminho: str, expira_em_s: int = 300) -> str:
    """Só usada em MODO SUPABASE — pede ao Supabase Storage uma URL temporária
    (expira em poucos minutos) para o arquivo, em vez de expor o bucket como
    público. Chamada sob demanda, a cada visualização, por cada módulo —
    depois que ele já confirmou que o usuário logado pode ver aquele
    registro."""
    url = f"{SUPABASE_URL}/storage/v1/object/sign/{bucket}/{caminho}"
    body = json.dumps({"expiresIn": expira_em_s}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
            "apikey": SUPABASE_SERVICE_ROLE_KEY,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            dados = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError) as e:
        raise ErroArmazenamento(f"Falha ao gerar link temporário no Supabase Storage: {e}") from e
    return f"{SUPABASE_URL}/storage/v1{dados['signedURL']}"
