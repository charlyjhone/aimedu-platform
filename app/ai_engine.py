"""
Camada única de IA do AIM.Edu — TODOS os módulos (diagnóstico, redação,
relatórios, radar, bússola, coordenador de professores) chamam funções
daqui, nunca uma API de IA diretamente. Isso garante duas coisas que o
projeto pediu explicitamente:

  1. Projeto único e interligado: qualquer módulo novo reaproveita a
     mesma camada, os mesmos dados de aluno/turma e o mesmo estilo de
     saída.
  2. Zero vendor lock-in: hoje existe UMA implementação (`_gerar_regra`,
     100% local, sem depender de nenhum provedor). Quando uma chave de
     IA (OpenAI, Google, Anthropic, o que for) estiver disponível neste
     ambiente, basta implementar `_gerar_llm()` e trocar a variável
     `PROVEDOR_ATIVO` abaixo — nenhum outro arquivo do projeto muda.

Por que está assim agora: este ambiente de desenvolvimento não tem
acesso de rede a provedores de IA externos. A lógica adaptativa e os
textos abaixo são gerados por regras determinísticas (nível de acerto,
dificuldade, eixo da BNCC), para que o produto já funcione de ponta a
ponta hoje. Trocar para IA generativa real depois é uma troca de
"motor", não uma reconstrução do produto.
"""

PROVEDOR_ATIVO = "regra"  # trocar para "llm" quando houver acesso a um provedor


def _gerar_llm(prompt: str) -> str:
    raise NotImplementedError(
        "Nenhum provedor de IA está conectado a este ambiente ainda. "
        "Configure a chave e implemente esta função para ativar o motor de IA real."
    )


def resumo_diagnostico(disciplina: str, acertos: int, total: int, nivel_final: float, por_eixo: dict) -> str:
    """Gera o texto de fechamento do diagnóstico adaptativo (o que hoje é
    'regra' e amanhã pode virar uma chamada de LLM sem mudar quem chama)."""
    if PROVEDOR_ATIVO == "llm":
        prompt = (
            f"Aluno fez diagnóstico de {disciplina}. Acertos: {acertos}/{total}. "
            f"Nível final estimado: {nivel_final:.1f}/5. Desempenho por eixo: {por_eixo}. "
            "Escreva um retorno curto, construtivo, em português, para a família."
        )
        return _gerar_llm(prompt)

    pct = acertos / total if total else 0
    if pct >= 0.75:
        tom = "um desempenho muito sólido"
    elif pct >= 0.5:
        tom = "um desempenho dentro do esperado, com pontos específicos para reforçar"
    else:
        tom = "sinais claros de que o aluno precisa de apoio mais próximo agora"

    piores = sorted(por_eixo.items(), key=lambda kv: kv[1])[:2]
    piores_txt = ", ".join(f"{eixo} ({round(taxa*100)}% de acerto)" for eixo, taxa in piores) if piores else "—"

    return (
        f"O aluno respondeu {total} questões adaptativas de {disciplina}, acertando {acertos} "
        f"({round(pct*100)}%). O sistema ajustou a dificuldade a cada resposta e estimou o nível "
        f"atual em {nivel_final:.1f} de 5. Isso indica {tom}. Os eixos que mais precisam de atenção "
        f"agora são: {piores_txt}. Recomendação: priorizar exercícios nesses eixos nas próximas duas semanas."
    )


def perfil_vocacional(pontuacoes: dict, nivel_matematica: float | None = None) -> str:
    """Gera o texto de orientação da Bússola Vocacional a partir da pontuação
    (0 a 10) de cada área de interesse. Quando existe um diagnóstico de
    Matemática já feito pelo aluno, cruza os dois — é aqui que a Bússola
    "conversa" com o Diagnóstico Adaptativo pelo mesmo banco de dados."""
    if PROVEDOR_ATIVO == "llm":
        prompt = (
            f"Aluno respondeu um questionário de interesses vocacionais com estas pontuações "
            f"(0 a 10 por área): {pontuacoes}. Nível estimado em Matemática (0 a 5, se houver): "
            f"{nivel_matematica}. Escreva uma orientação vocacional curta, construtiva, em "
            "português, para um estudante do ensino médio, sem soar definitiva."
        )
        return _gerar_llm(prompt)

    ordenado = sorted(pontuacoes.items(), key=lambda kv: kv[1], reverse=True)
    topo_valor = ordenado[0][1]
    top_areas = [area for area, valor in ordenado if valor >= topo_valor - 1 and valor > 0]
    if len(top_areas) == 1:
        top_txt = top_areas[0]
    else:
        top_txt = ", ".join(top_areas[:-1]) + " e " + top_areas[-1]

    texto = (
        f"Com base nas suas respostas, sua maior afinidade hoje aparece em {top_txt}. "
        "Isso não é uma resposta definitiva sobre sua carreira — é um retrato do que mais "
        "chamou sua atenção neste momento, útil como ponto de partida."
    )

    if nivel_matematica is not None:
        exatas_no_topo = any("Exatas" in area for area in top_areas)
        if exatas_no_topo and nivel_matematica >= 3.5:
            texto += (
                " Isso combina com o seu bom desempenho no Diagnóstico Adaptativo de Matemática, "
                "o que reforça esse caminho como uma opção sólida."
            )
        elif exatas_no_topo and nivel_matematica < 3.5:
            texto += (
                " Seu Diagnóstico Adaptativo de Matemática ainda mostra espaço para evoluir — "
                "vale reforçar a base nessa disciplina para seguir esse caminho com mais segurança."
            )
        elif not exatas_no_topo and nivel_matematica >= 4:
            texto += (
                " Vale notar: seu Diagnóstico de Matemática mostrou um desempenho forte mesmo essa "
                "não sendo sua área de maior interesse — pode valer a pena considerar cursos que "
                "combinem exatas com a sua área principal."
            )

    texto += " Converse com a coordenação sobre trilhas, cursos e profissões ligadas a essas áreas."
    return texto
