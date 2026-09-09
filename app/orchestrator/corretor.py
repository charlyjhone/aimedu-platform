"""
Orquestrador do "time invisível" de 12 agentes de IA do AIM.Edu — versão 2
(por agentes especializados) da correção de redação.

Especificação completa dos 12 agentes recebida do usuário em 2026-09-09
diretamente na conversa (não existe nenhum documento equivalente no Google
Drive do projeto — procuramos antes de implementar). Ver app/agents/agente.py
para a função de cada agente e app/prompts/ para os prompts.

IMPORTANTE — o que este módulo NÃO faz ainda, por decisão explícita do
usuário:
  - Não tem ciclo de tentativas/reescrita. Cada agente é chamado uma única
    vez por redação ("o portal atual é 'one-shot'"). O ciclo de reescrita é
    uma evolução futura — a tabela `tentativas` já existe para dar
    histórico a essa evolução, mas ninguém ainda lê esse histórico para
    decidir reescrever nada.
  - Não está plugado em nenhuma rota do site. app/modules/redacao.py e
    app/ai_engine.py continuam exatamente como estavam — nenhuma chamada
    real acontece ainda. Ver flags detalhadas na resposta ao usuário sobre
    o que falta decidir antes de ligar isso na produção.

Este módulo é INDEPENDENTE de app/ai_engine.py (mantido intacto, sem
nenhuma alteração) — é uma implementação alternativa da mesma ideia
(corrigir_redacao(tema, texto) -> dict), pensada para um dia substituir
ai_engine.corrigir_redacao ou conviver com ela atrás de uma rota de teste,
como o usuário definir.
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..agents import agente
from ..db import get_db, new_id

# Pesos usados para a "nota ponderada" pedida na especificação (0-200).
# Por padrão, pesos iguais (a média simples das 5 competências) — mesmos
# pesos que o ENEM já usa implicitamente ao somar as 5 notas de 0-200 para
# chegar em 0-1000. Ver flag sobre nota_total x nota_ponderada na resposta
# ao usuário.
PESOS_COMPETENCIAS = {"c1": 0.2, "c2": 0.2, "c3": 0.2, "c4": 0.2, "c5": 0.2}

NOMES_COMPETENCIA = {
    "c1": "domínio da norma padrão",
    "c2": "compreensão do tema e repertório",
    "c3": "argumentação",
    "c4": "coesão e coerência",
    "c5": "proposta de intervenção",
}


class ErroCorrecao(Exception):
    """Erro fatal na correção — só é levantado se agentes essenciais (2 a 6,
    os que dão nota) falharem TODOS. Falha de um agente auxiliar (7,8,9)
    nunca derruba a correção inteira, só empobrece o feedback."""


def _extrair_tese(texto: str) -> str:
    """Heurística simples: a tese é a primeira frase do texto (até o
    primeiro ponto final seguido de espaço/quebra, ou a primeira linha não
    vazia se não achar ponto). Não é um parser de estrutura textual de
    verdade — serve só para dar um pedaço razoável ao Agente 7."""
    texto_limpo = texto.strip()
    match = re.search(r"[.!?]\s", texto_limpo)
    if match and match.start() > 15:
        return texto_limpo[:match.start() + 1].strip()
    primeira_linha = next((l.strip() for l in texto_limpo.split("\n") if l.strip()), texto_limpo)
    return primeira_linha


def _extrair_ultimo_paragrafo(texto: str) -> str:
    paragrafos = [p.strip() for p in re.split(r"\n\s*\n", texto.strip()) if p.strip()]
    if paragrafos:
        return paragrafos[-1]
    return texto.strip()


def _registrar_tentativa(db, *, redacao_id, agente_nome, numero_tentativa,
                          modelo, entrada, saida, nota, erro, duracao_ms,
                          tokens_entrada=None, tokens_saida=None):
    """Grava uma linha em `tentativas` — melhor esforço: se o banco não
    estiver disponível (ex.: chamada fora de um contexto de requisição
    Flask, como num teste manual) isso NUNCA deve derrubar a correção.

    tokens_entrada/tokens_saida vêm do "usage" da API da Anthropic (ver
    agente.py:_chamar_claude) — ficam None quando a chamada falhou antes
    de completar, ou na linha "orquestrador"."""
    if db is None:
        return
    try:
        db.execute(
            "insert into tentativas "
            "(id, redacao_id, agente, numero_tentativa, modelo, entrada, saida, nota, erro, duracao_ms, "
            "tokens_entrada, tokens_saida) "
            "values (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                new_id(), redacao_id, agente_nome, numero_tentativa, modelo,
                entrada[:8000] if entrada else entrada,
                saida[:8000] if saida else saida,
                nota, erro, duracao_ms, tokens_entrada, tokens_saida,
            ),
        )
        db.commit()
    except Exception:
        # Best-effort: histórico de tentativas nunca deve quebrar a
        # correção em si. Se isto falhar silenciosamente demais em
        # produção, vira um logging.exception() antes de ir pro ar.
        pass


def _chamar_com_registro(nome_agente, funcao, *args, db=None, redacao_id=None, **kwargs):
    """Chama um `agente.chamar_agente_N(...)`, registra a tentativa
    (sucesso ou erro) e devolve (resultado_json_ou_None, metadados_ou_None,
    erro_ou_None)."""
    entrada_str = json.dumps({"args": [str(a)[:2000] for a in args], "kwargs": kwargs}, ensure_ascii=False)
    try:
        resultado, metadados = funcao(*args, **kwargs)
        nota = resultado.get("nota") if isinstance(resultado, dict) else None
        _registrar_tentativa(
            db, redacao_id=redacao_id, agente_nome=nome_agente, numero_tentativa=1,
            modelo=metadados.get("modelo"), entrada=entrada_str,
            saida=metadados.get("resposta_bruta"), nota=nota, erro=None,
            duracao_ms=metadados.get("duracao_ms"),
            tokens_entrada=metadados.get("tokens_entrada"), tokens_saida=metadados.get("tokens_saida"),
        )
        return resultado, metadados, None
    except agente.ErroAgenteIA as e:
        _registrar_tentativa(
            db, redacao_id=redacao_id, agente_nome=nome_agente, numero_tentativa=1,
            modelo=None, entrada=entrada_str, saida=getattr(e, "resposta_bruta", ""),
            nota=None, erro=str(e), duracao_ms=None,
        )
        return None, None, str(e)
    except Exception as e:  # nunca deixar um agente derrubar os outros
        _registrar_tentativa(
            db, redacao_id=redacao_id, agente_nome=nome_agente, numero_tentativa=1,
            modelo=None, entrada=entrada_str, saida=None,
            nota=None, erro=f"erro inesperado: {e}", duracao_ms=None,
        )
        return None, None, str(e)


def _consolidar_feedback(tema: str, resultados: dict) -> str:
    """Costura os textos dos agentes 2 a 9 num parágrafo único com tom de
    mentoria, como pedido na especificação. Decisão de implementação
    (sinalizada ao usuário): a costura é feita aqui em Python, por
    concatenação de template — NÃO é mais uma chamada de IA. Isso evita uma
    13ª chamada de modelo só para redigir o texto final, mantendo o
    resultado prático (mesma informação, custo e latência menores) e
    100% determinístico a partir do que cada agente já disse."""
    partes = []

    c1 = resultados.get("c1")
    if c1:
        n_erros = len(c1.get("erros", []))
        if n_erros:
            partes.append(
                f"Na norma padrão (C1), encontrei {n_erros} ponto(s) a ajustar — {c1.get('resumo', '')}"
            )
        else:
            partes.append(f"Na norma padrão (C1): {c1.get('resumo', 'nenhum desvio relevante encontrado.')}")

    c2 = resultados.get("c2")
    if c2:
        partes.append(c2.get("justificativa", ""))
        sugestoes = c2.get("sugestoes_repertorio") or []
        if sugestoes:
            partes.append(f"Para a próxima redação sobre temas parecidos, vale conhecer também: {sugestoes[0]}.")

    c3 = resultados.get("c3")
    if c3:
        partes.append(c3.get("diagnostico", ""))
        if c3.get("pergunta_para_aprofundar"):
            partes.append(f"Uma pergunta para você pensar antes da próxima versão: {c3['pergunta_para_aprofundar']}")

    c4 = resultados.get("c4")
    if c4:
        conectivos = c4.get("conectivos_alternativos") or []
        if conectivos:
            partes.append(
                "Na coesão (C4), experimente variar os conectivos que você mais repetiu — "
                f"opções como {', '.join(conectivos)} ajudam a costurar melhor os parágrafos."
            )

    c5 = resultados.get("c5")
    if c5:
        checklist = c5.get("checklist", {})
        reprovados = [
            NOMES_COMPETENCIA.get(pilar, pilar) if pilar in NOMES_COMPETENCIA else pilar
            for pilar, info in checklist.items()
            if isinstance(info, dict) and info.get("status") != "aprovado"
        ]
        if reprovados:
            partes.append(
                f"Na proposta de intervenção (C5), os pilares que ainda precisam de atenção são: {', '.join(reprovados)}."
            )
            perguntas = c5.get("perguntas_para_pilares_reprovados") or []
            if perguntas:
                partes.append(perguntas[0])
        else:
            partes.append("Na proposta de intervenção (C5), os 5 pilares apareceram completos — ótimo trabalho aqui.")

    agente7 = resultados.get("agente_7")
    if agente7 and agente7.get("perguntas"):
        partes.append(f"Antes de encerrar, uma provocação para amadurecer sua tese: {agente7['perguntas'][0]}")

    agente8 = resultados.get("agente_8")
    if agente8 and agente8.get("repertorios"):
        nomes = [r.get("nome") for r in agente8["repertorios"][:2] if r.get("nome")]
        if nomes:
            partes.append(f"Repertórios que combinariam bem com este tema: {' e '.join(nomes)}.")

    agente9 = resultados.get("agente_9")
    if agente9 and agente9.get("relato"):
        partes.append(agente9["relato"])

    partes.append(
        "Lembre-se: esta é uma correção de apoio gerada por IA — a palavra final sobre a nota é sempre do professor."
    )

    return " ".join(p.strip() for p in partes if p and p.strip())


def corrigir_redacao(tema: str, texto: str, redacao_id: str | None = None) -> dict:
    """Assinatura preservada EXATAMENTE como pedido: corrigir_redacao(tema,
    texto) -> dict. 'redacao_id' foi adicionado como parâmetro OPCIONAL
    (default None) só para permitir religar cada linha de `tentativas` à
    redação correspondente — quem chamar com apenas (tema, texto)
    continua funcionando exatamente igual, só sem esse vínculo no
    histórico. Ver flag sobre isso na resposta ao usuário.

    Orquestra, em paralelo, os agentes 2 a 9 (os únicos que fazem sentido
    DEPOIS que o aluno já entregou um texto — ver docstring do módulo para
    por que 1, 10, 11 e 12 ficam de fora deste fluxo). Devolve:

        {
          "nota_c1": 0-200, "nota_c2": 0-200, "nota_c3": 0-200,
          "nota_c4": 0-200, "nota_c5": 0-200,
          "nota_ponderada": 0-200,    # CANÔNICA — decisão do usuário em 2026-09-09:
                                      # esta é a nota final da correção, a que deve
                                      # aparecer para o aluno e ser salva no banco.
          "nota_total": 0-1000,       # soma das 5 (só para referência/familiaridade
                                      # com o padrão ENEM — NÃO usar como a nota
                                      # exibida; ver flag na resposta ao usuário
                                      # sobre a tela redacao_resultado.html ainda
                                      # esperar um total de 0-1000).
          "feedback_ia": "...",
          "detalhes_agentes": {...},  # saída completa de cada agente, para uso futuro (ex.: tela com o "dedo no texto" de C5)
          "falhas": {...},            # agentes que erraram (se algum erro parcial ocorreu)
        }
    """
    db = None
    try:
        db = get_db()
    except Exception:
        db = None  # chamada fora de um contexto de requisição Flask (ex.: teste manual) — segue sem log

    tese = _extrair_tese(texto)
    ultimo_paragrafo = _extrair_ultimo_paragrafo(texto)

    tarefas = {
        "c1": (agente.chamar_agente_2, (texto,), {}),
        "c2": (agente.chamar_agente_3, (texto, tema), {}),
        "c3": (agente.chamar_agente_4, (texto,), {}),
        "c4": (agente.chamar_agente_5, (texto,), {}),
        "c5": (agente.chamar_agente_6, (ultimo_paragrafo,), {}),
        "agente_7": (agente.chamar_agente_7, (tese,), {}),
        "agente_8": (agente.chamar_agente_8, (tema,), {}),
        "agente_9": (agente.chamar_agente_9, (texto,), {}),
    }

    resultados: dict = {}
    falhas: dict = {}

    with ThreadPoolExecutor(max_workers=len(tarefas)) as executor:
        futuros = {
            executor.submit(_chamar_com_registro, nome, func, *args, db=db, redacao_id=redacao_id, **kwargs): nome
            for nome, (func, args, kwargs) in tarefas.items()
        }
        for futuro in as_completed(futuros):
            nome = futuros[futuro]
            resultado, _metadados, erro = futuro.result()
            if erro:
                falhas[nome] = erro
            else:
                resultados[nome] = resultado

    # Notas: None quando o agente correspondente falhou — ver flag sobre
    # este ponto (competência sem nota) na resposta ao usuário.
    notas = {}
    for c in ("c1", "c2", "c3", "c4", "c5"):
        r = resultados.get(c)
        notas[c] = r.get("nota") if r else None

    notas_validas = {c: n for c, n in notas.items() if n is not None}
    if not notas_validas:
        raise ErroCorrecao(
            "Todos os 5 agentes de competência (2 a 6) falharam — não foi "
            f"possível corrigir esta redação. Falhas: {falhas}"
        )

    nota_total = sum(notas_validas.values())
    soma_pesos_validos = sum(PESOS_COMPETENCIAS[c] for c in notas_validas)
    nota_ponderada = round(
        sum(notas_validas[c] * PESOS_COMPETENCIAS[c] for c in notas_validas) / soma_pesos_validos
    ) if soma_pesos_validos else 0

    feedback_ia = _consolidar_feedback(tema, resultados)
    if falhas:
        agentes_com_falha = ", ".join(sorted(falhas))
        feedback_ia += (
            f" (Aviso técnico: os agentes [{agentes_com_falha}] não responderam nesta correção — "
            "peça ao professor para revisar essa(s) parte(s) manualmente.)"
        )

    resultado_final = {
        "nota_c1": notas["c1"],
        "nota_c2": notas["c2"],
        "nota_c3": notas["c3"],
        "nota_c4": notas["c4"],
        "nota_c5": notas["c5"],
        "nota_total": nota_total,
        "nota_ponderada": nota_ponderada,
        "feedback_ia": feedback_ia,
        "detalhes_agentes": resultados,
        "falhas": falhas,
    }

    _registrar_tentativa(
        db, redacao_id=redacao_id, agente_nome="orquestrador", numero_tentativa=1,
        modelo=None, entrada=json.dumps({"tema": tema}, ensure_ascii=False),
        saida=json.dumps({k: v for k, v in resultado_final.items() if k != "detalhes_agentes"}, ensure_ascii=False),
        nota=nota_total, erro=(json.dumps(falhas, ensure_ascii=False) if falhas else None), duracao_ms=None,
    )

    return resultado_final
