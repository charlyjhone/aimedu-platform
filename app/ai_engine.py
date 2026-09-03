"""
Camada única de IA do AIM.Edu — TODOS os módulos (diagnóstico, redação,
relatórios, radar, bússola, coordenador de professores) chamam funções
daqui, nunca uma API de IA diretamente. Isso garante duas coisas que o
projeto pediu explicitamente:

Nota sobre o Coordenador de Professores por IA: as quatro funções no fim
deste arquivo (resumo_desempenho_turma, sugestoes_pedagogicas_turma,
responder_duvida_professor, resumo_engajamento_professor) seguem o mesmo
contrato — hoje regra local, amanhã LLM real — usadas pelo módulo
app.modules.coordenador_professores.

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

# Nomes das 5 competências do ENEM — único lugar onde isso é definido, usado
# tanto na correção da redação quanto no Coordenador de Professores por IA
# (que precisa citar a mesma competência pelo mesmo nome nos dois lugares).
NOMES_COMPETENCIA_REDACAO = {
    "nota_c1": "domínio da norma culta (C1)",
    "nota_c2": "compreensão do tema (C2)",
    "nota_c3": "organização e argumentação (C3)",
    "nota_c4": "coesão e coerência, uso de conectivos (C4)",
    "nota_c5": "proposta de intervenção (C5)",
}

# Rótulos de exibição para as disciplinas do Diagnóstico Adaptativo (o slug é
# o que fica salvo em itens_banco.disciplina/diagnosticos.disciplina). Único
# lugar do projeto onde essa lista existe — app/__init__.py usa isto no
# filtro Jinja "disciplina" e app/modules/coordenador_professores.py usa para
# rotular os blocos por disciplina. Adicionar uma disciplina nova ao
# Diagnóstico Adaptativo é: cadastrar itens em itens_banco com um novo slug
# e acrescentar o rótulo aqui — nenhuma rota nem template precisa mudar.
NOMES_DISCIPLINA = {
    "matematica": "Matemática",
    "portugues": "Português",
}


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


CONECTIVOS = [
    "portanto", "por isso", "dessa forma", "desse modo", "assim sendo", "logo",
    "entretanto", "no entanto", "contudo", "todavia", "além disso", "ademais",
    "outrossim", "por conseguinte", "em suma", "nesse sentido", "sob essa ótica",
]
MARCAS_INFORMAIS = ["vc ", " pq ", "tipo assim", "mano", "slk", "kkk", "!!!", "afff", " né "]
AGENTES_INTERVENCAO = ["governo", "poder público", "estado", "escola", "família", "mídia", "sociedade", "ongs", "ministério"]
ACOES_INTERVENCAO = ["campanha", "fiscalização", "investimento", "conscientização", "educação", "política pública", "lei ", "projeto", "criação de"]


def corrigir_redacao(tema: str, texto: str) -> dict:
    """Estima uma nota nas 5 competências do ENEM (0 a 200 cada, múltiplos de
    40) a partir de heurísticas de texto (tamanho, parágrafos, conectivos,
    palavras do tema, indícios de proposta de intervenção). Retorna um dict
    com nota_c1..nota_c5, nota_total e feedback_ia.

    IMPORTANTE: isto é uma estimativa automática por regras, não uma correção
    oficial — não há um corretor humano nem um modelo de linguagem por trás
    disto hoje (ver aviso no topo deste arquivo). Serve para dar um primeiro
    retorno rápido ao aluno; a palavra final é sempre do professor.

    Nota (redação por foto): esta função não tem mais nenhum ponto do
    sistema que a chame — o aluno agora envia uma FOTO da redação manuscrita
    (ver app/modules/redacao.py) e a correção fica pendente até um provedor
    de IA com visão (Gemini, decidido para o futuro) ler a foto diretamente,
    sem OCR/transcrição por regra. Mantida aqui de propósito, sem alteração,
    porque a lógica de heurísticas de texto pode ser reaproveitada quando
    houver uma transcrição (pelo próprio Gemini) desse texto no futuro."""
    if PROVEDOR_ATIVO == "llm":
        prompt = (
            f"Corrija esta redação dissertativa-argumentativa no modelo ENEM. "
            f"Tema: {tema!r}. Texto: {texto!r}. Dê nota de 0 a 200 (múltiplos de 40) "
            "em cada uma das 5 competências do ENEM e um feedback construtivo em português."
        )
        return _gerar_llm(prompt)

    palavras = texto.split()
    n_palavras = len(palavras)
    paragrafos = [p.strip() for p in texto.split("\n") if p.strip()]
    n_paragrafos = len(paragrafos)
    texto_lower = texto.lower()

    if n_palavras < 50:
        return {
            "nota_c1": 0, "nota_c2": 0, "nota_c3": 0, "nota_c4": 0, "nota_c5": 0,
            "nota_total": 0,
            "feedback_ia": (
                "O texto está muito curto para ser avaliado como uma redação dissertativa-argumentativa "
                "completa (o ENEM já zera textos muito curtos). Desenvolva introdução, pelo menos dois "
                "parágrafos de argumentação e uma conclusão com proposta de intervenção — no total, "
                "normalmente entre 200 e 350 palavras."
            ),
        }

    # C1 — domínio da norma culta: penaliza marcas de informalidade encontradas no texto.
    penalidades_c1 = sum(texto_lower.count(m) for m in MARCAS_INFORMAIS)
    pontos_c1 = max(1, 5 - penalidades_c1)

    # C2 — compreensão do tema: quantas palavras "de conteúdo" do tema aparecem no texto.
    palavras_tema = [p.lower() for p in (tema or "").split() if len(p) >= 5]
    if palavras_tema:
        presentes = sum(1 for p in palavras_tema if p in texto_lower)
        proporcao = presentes / len(palavras_tema)
        pontos_c2 = 5 if proporcao >= 0.6 else 4 if proporcao >= 0.4 else 3 if proporcao >= 0.2 else 2 if presentes else 1
    else:
        pontos_c2 = 3  # sem tema informado, não dá pra avaliar aderência — nota neutra

    # C3 — organização/argumentação: estrutura em parágrafos e desenvolvimento (nº de palavras).
    pontos_estrutura = 5 if n_paragrafos in (4, 5) else 4 if n_paragrafos in (3, 6) else 2 if n_paragrafos >= 2 else 1
    pontos_extensao = 5 if n_palavras >= 250 else 4 if n_palavras >= 180 else 3 if n_palavras >= 120 else 2
    pontos_c3 = round((pontos_estrutura + pontos_extensao) / 2)

    # C4 — coesão: densidade de conectivos ao longo do texto.
    n_conectivos = sum(texto_lower.count(c) for c in CONECTIVOS)
    densidade = n_conectivos / n_paragrafos if n_paragrafos else 0
    pontos_c4 = 5 if densidade >= 1.5 else 4 if densidade >= 1 else 3 if densidade >= 0.5 else 2 if n_conectivos >= 1 else 1

    # C5 — proposta de intervenção: procura agente + ação no último parágrafo (a conclusão).
    conclusao = paragrafos[-1].lower() if paragrafos else ""
    tem_agente = any(a in conclusao for a in AGENTES_INTERVENCAO)
    tem_acao = any(a in conclusao for a in ACOES_INTERVENCAO)
    pontos_c5 = 5 if (tem_agente and tem_acao) else 3 if (tem_agente or tem_acao) else 1

    notas = {
        "nota_c1": pontos_c1 * 40,
        "nota_c2": pontos_c2 * 40,
        "nota_c3": pontos_c3 * 40,
        "nota_c4": pontos_c4 * 40,
        "nota_c5": pontos_c5 * 40,
    }
    nota_total = sum(notas.values())

    piores = sorted(notas.items(), key=lambda kv: kv[1])[:2]
    piores_txt = " e ".join(NOMES_COMPETENCIA_REDACAO[c] for c, _ in piores)

    feedback = (
        f"Estimativa automática: {nota_total}/1000. As competências que mais precisam de atenção agora "
        f"são {piores_txt}. "
    )
    if pontos_c5 < 4:
        feedback += (
            "Na conclusão, deixe claro QUEM deve agir (governo, escola, família, mídia, sociedade) e QUAL "
            "ação concreta deve ser tomada (uma campanha, uma lei, um investimento, um projeto) — essa é "
            "a proposta de intervenção que o ENEM cobra na competência 5. "
        )
    if pontos_c4 < 4:
        feedback += (
            "Use mais conectivos entre parágrafos e frases (portanto, além disso, no entanto, dessa forma) "
            "para deixar a argumentação mais costurada. "
        )
    feedback += (
        "Lembre-se: esta é uma correção automática por regras, útil como primeiro retorno rápido — "
        "peça também a leitura de um professor antes de considerar a nota final."
    )

    notas["nota_total"] = nota_total
    notas["feedback_ia"] = feedback
    return notas


def gerar_relatorio_familia(nome_aluno: str, diagnosticos: list, redacoes: list, bussola, alertas_pendentes: list) -> str:
    """Gera o texto do relatório periódico para a família, juntando dados de
    TODOS os módulos pedagógicos do aluno — Diagnóstico de Matemática,
    Redação, Bússola Vocacional e Radar da Coordenação. Este é o retrato mais
    direto do "projeto único e interligado": o relatório não pertence a
    nenhum módulo específico, ele só existe porque todos gravam na mesma
    base de dados e podem ser lidos juntos aqui."""
    if PROVEDOR_ATIVO == "llm":
        prompt = (
            f"Escreva um relatório periódico curto e acolhedor para a família de {nome_aluno}, "
            f"em português, juntando: diagnósticos adaptativos ({len(diagnosticos)} registrados, em "
            f"várias disciplinas possíveis), redações ({len(redacoes)} registradas), bússola vocacional "
            f"({bussola}), e {len(alertas_pendentes)} alerta(s) pendente(s) na coordenação."
        )
        return _gerar_llm(prompt)

    partes = [f"Relatório de acompanhamento de {nome_aluno}."]

    if diagnosticos:
        ultimo = diagnosticos[0]
        nome_disc = NOMES_DISCIPLINA.get(ultimo["disciplina"], (ultimo["disciplina"] or "").capitalize())
        nivel = ultimo["nivel_final"]
        trecho = (
            f"No Diagnóstico Adaptativo de {nome_disc} mais recente, o nível estimado foi {nivel:.1f}/5"
            if nivel is not None else f"Há um diagnóstico de {nome_disc} em andamento"
        )
        partes.append(trecho + ".")
        if len(diagnosticos) > 1:
            disciplinas_distintas = sorted({d["disciplina"] for d in diagnosticos})
            if len(disciplinas_distintas) > 1:
                nomes = ", ".join(NOMES_DISCIPLINA.get(d, d.capitalize()) for d in disciplinas_distintas)
                partes.append(f"Ao todo, já foram realizados {len(diagnosticos)} diagnósticos adaptativos, em: {nomes}.")
            else:
                partes.append(f"Ao todo, já foram realizados {len(diagnosticos)} diagnósticos de {nome_disc}.")
    else:
        partes.append("Ainda não há diagnósticos adaptativos registrados.")

    if redacoes:
        ultima = redacoes[0]
        tema = ultima["tema"] or "sem tema informado"
        # A redação é enviada por foto e só ganha nota quando um provedor de
        # IA real corrigir (ver app/modules/redacao.py) — sem isso, mostrar
        # "0/1000" passaria a impressão errada de que o aluno zerou.
        if ultima["status"] == "corrigida":
            nota_total = sum(ultima[c] or 0 for c in ("nota_c1", "nota_c2", "nota_c3", "nota_c4", "nota_c5"))
            partes.append(f"Na Redação mais recente ({tema}), a nota estimada foi {nota_total}/1000.")
        else:
            partes.append(f"Há uma Redação mais recente ({tema}) aguardando correção por IA.")
    else:
        partes.append("Ainda não há redações enviadas.")

    if bussola:
        partes.append(f"Na Bússola Vocacional, a maior afinidade identificada foi em {bussola['perfil_top']}.")
    else:
        partes.append("A Bússola Vocacional ainda não foi respondida.")

    if alertas_pendentes:
        motivos = "; ".join(a["motivo"] for a in alertas_pendentes[:3])
        partes.append(
            f"Atenção: há {len(alertas_pendentes)} alerta(s) pendente(s) na coordenação — {motivos}."
        )
    else:
        partes.append("Não há alertas pendentes na coordenação neste momento.")

    partes.append(
        "Este relatório é gerado automaticamente a partir dos dados já registrados no sistema; "
        "qualquer dúvida, procure a coordenação da escola."
    )

    return " ".join(partes)


def resumo_desempenho_turma(nome_turma: str, total_alunos: int, diagnosticos_por_disciplina: dict,
                             alunos_com_redacao: int, media_nota_redacao, competencias_fracas: list,
                             alertas_pendentes: int) -> str:
    """Gera o texto de leitura do desempenho de uma turma inteira — usado pelo
    professor (na própria turma, só na disciplina dele) e pela coordenação/
    direção (em qualquer turma, com um bloco por disciplina). Cruza
    Diagnóstico Adaptativo (de cada disciplina que já tem banco de itens),
    Redação e Radar pela mesma lógica dos outros relatórios do AIM.Edu: são
    os dados que os outros módulos já gravaram, lidos juntos aqui.

    diagnosticos_por_disciplina: {slug_disciplina: {"alunos_com_diagnostico",
    "media_nivel", "eixos_fracos"}} — um item por disciplina com Diagnóstico
    Adaptativo relevante para quem está vendo a turma."""
    if PROVEDOR_ATIVO == "llm":
        prompt = (
            f"Resuma o desempenho da turma {nome_turma!r}: {total_alunos} alunos. Diagnóstico Adaptativo "
            f"por disciplina: {diagnosticos_por_disciplina}. {alunos_com_redacao} enviaram redação (nota "
            f"média {media_nota_redacao}), competências mais fracas: {competencias_fracas}. "
            f"{alertas_pendentes} alerta(s) pendente(s) no Radar da Coordenação. "
            "Escreva um resumo curto e construtivo em português."
        )
        return _gerar_llm(prompt)

    partes = [f"Turma {nome_turma}: {total_alunos} aluno(s) cadastrado(s)."]

    if diagnosticos_por_disciplina:
        for slug, bloco in diagnosticos_por_disciplina.items():
            nome_disc = NOMES_DISCIPLINA.get(slug, slug.capitalize())
            if bloco["alunos_com_diagnostico"]:
                trecho = (
                    f"Em {nome_disc}, {bloco['alunos_com_diagnostico']} de {total_alunos} já fizeram o "
                    f"Diagnóstico Adaptativo, com nível médio estimado de {bloco['media_nivel']:.1f}/5"
                )
                if bloco["eixos_fracos"]:
                    eixos_txt = ", ".join(f"{eixo} ({round(taxa*100)}% de acerto)" for eixo, taxa in bloco["eixos_fracos"])
                    trecho += f" — eixos da BNCC com mais dificuldade: {eixos_txt}"
                partes.append(trecho + ".")
            else:
                partes.append(f"Em {nome_disc}, ainda ninguém na turma fez o Diagnóstico Adaptativo.")
    else:
        partes.append("Ainda não há Diagnóstico Adaptativo disponível para nenhuma disciplina desta turma.")

    if alunos_com_redacao:
        # media_nota_redacao só existe quando há pelo menos uma redação já
        # corrigida (ver _stats_gerais_turma em coordenador_professores.py) —
        # com a redação por foto, todo envio nasce 'aguardando_ia' até um
        # provedor de IA real corrigir, então é normal ter aluno_com_redacao
        # > 0 e media_nota_redacao ainda None.
        if media_nota_redacao is not None:
            partes.append(
                f"{alunos_com_redacao} de {total_alunos} já enviaram redação, com nota média de "
                f"{media_nota_redacao:.0f}/1000."
            )
            if competencias_fracas:
                partes.append(f"A(s) competência(s) do ENEM que mais precisa(m) de atenção: {', '.join(competencias_fracas)}.")
        else:
            partes.append(f"{alunos_com_redacao} de {total_alunos} já enviaram redação, todas aguardando correção por IA.")
    else:
        partes.append("Ainda ninguém na turma enviou redação.")

    if alertas_pendentes:
        partes.append(
            f"Há {alertas_pendentes} alerta(s) pendente(s) desta turma no Radar da Coordenação — vale revisar."
        )
    else:
        partes.append("Não há alertas pendentes desta turma no Radar no momento.")

    return " ".join(partes)


def sugestoes_pedagogicas_turma(diagnosticos_por_disciplina: dict, competencias_fracas: list, alertas_pendentes: int) -> list:
    """Gera uma lista curta de sugestões de ação para o professor, a partir
    dos mesmos dados do resumo acima — separado em função própria porque o
    professor pode querer só as ações, sem reler o diagnóstico inteiro."""
    if PROVEDOR_ATIVO == "llm":
        prompt = (
            f"A partir do Diagnóstico Adaptativo por disciplina {diagnosticos_por_disciplina} e das "
            f"competências de redação mais fracas {competencias_fracas}, com {alertas_pendentes} "
            "alerta(s) pendente(s), sugira de 2 a 4 ações pedagógicas curtas e práticas em português, "
            "uma por linha."
        )
        return [_gerar_llm(prompt)]

    sugestoes = []

    for slug, bloco in diagnosticos_por_disciplina.items():
        nome_disc = NOMES_DISCIPLINA.get(slug, slug.capitalize())
        for eixo, taxa in bloco["eixos_fracos"]:
            sugestoes.append(
                f"Reforçar o eixo \"{eixo}\" de {nome_disc} com exercícios extras — a turma acerta apenas "
                f"{round(taxa*100)}% das questões desse eixo no Diagnóstico Adaptativo."
            )

    dicas_competencia = {
        "domínio da norma culta (C1)": "Trabalhar revisão gramatical e reescrita de trechos com desvios de norma culta.",
        "compreensão do tema (C2)": "Praticar leitura de propostas de redação e sublinhar as palavras-chave do tema antes de escrever.",
        "organização e argumentação (C3)": "Reforçar a estrutura em 4-5 parágrafos (introdução, 2 de desenvolvimento, conclusão).",
        "coesão e coerência, uso de conectivos (C4)": "Exercitar o uso de conectivos entre parágrafos (portanto, além disso, no entanto).",
        "proposta de intervenção (C5)": "Treinar a conclusão com agente + ação concreta (quem deve agir e o que deve ser feito).",
    }
    for competencia in competencias_fracas:
        if competencia in dicas_competencia:
            sugestoes.append(dicas_competencia[competencia])

    if alertas_pendentes:
        sugestoes.append(
            f"Revisar os {alertas_pendentes} alerta(s) pendente(s) desta turma no Radar da Coordenação — "
            "priorizar contato com os alunos envolvidos."
        )

    if not sugestoes:
        sugestoes.append(
            "Ainda não há dados suficientes desta turma (diagnósticos, redações ou alertas) para gerar "
            "sugestões — assim que os alunos usarem os módulos pedagógicos, as sugestões aparecem aqui."
        )

    return sugestoes


FAQ_PROFESSOR = [
    (("pei", "plano educacional individualizado"),
     "O PEI (Plano Educacional Individualizado) é editado pela psicopedagoga, na ficha de Inclusão do aluno. "
     "Você, como professor, pode consultar as metas e revisões do PEI na ficha do aluno, mas a edição é "
     "exclusiva da psicopedagoga."),
    (("inclusao", "inclusão", "adaptação", "adaptacao", "necessidade especial", "necessidade específica"),
     "O cadastro de Inclusão (necessidades, adaptações e apoio especializado) fica na área \"Inclusão\", "
     "acessível pelo seu painel. Professores podem consultar os dados de qualquer aluno das suas turmas, "
     "mas quem edita é a psicopedagoga, a coordenação ou a direção."),
    (("senha", "esqueci", "trocar senha", "redefinir"),
     "Para trocar sua própria senha, use \"Meu perfil\" no topo da página. Se você esqueceu a senha e não "
     "consegue entrar, peça para a coordenação redefinir pela tela de Gestão de Usuários."),
    (("diagnostico", "diagnóstico", "matematica", "matemática"),
     "O Diagnóstico Adaptativo de Matemática é feito pelo próprio aluno; o nível estimado e os eixos da "
     "BNCC com mais dificuldade aparecem aqui no Coordenador de Professores por IA, na página da turma."),
    (("redacao", "redação"),
     "As redações são enviadas e corrigidas automaticamente (nota estimada nas 5 competências do ENEM) "
     "quando o aluno envia pelo módulo de Redação. O resultado por turma aparece aqui, na página da turma."),
    (("alerta", "radar"),
     "Alertas de alunos que precisam de atenção aparecem no Radar da Coordenação. Professores podem "
     "consultar; quem resolve ou reabre um alerta é a coordenação ou a direção."),
    (("importar", "csv", "cadastro em lote", "cadastrar aluno", "cadastrar professor"),
     "O cadastro em lote de alunos e professores por CSV é feito pela coordenação ou direção, na tela de "
     "Gestão de Usuários — inclusive o download de um modelo em branco para preencher."),
]

RESPOSTA_PADRAO_DUVIDA = (
    "Ainda não tenho uma resposta pronta para essa dúvida específica — isso hoje é respondido por regras "
    "simples de palavras-chave, sem um modelo de linguagem por trás (ver aviso no topo de app/ai_engine.py). "
    "Procure a coordenação da escola, ou tente reformular a pergunta usando palavras como \"PEI\", "
    "\"inclusão\", \"diagnóstico\", \"redação\", \"alerta\" ou \"senha\"."
)


def responder_duvida_professor(pergunta: str) -> str:
    """Responde a uma dúvida do professor sobre o próprio sistema AIM.Edu.
    Hoje é um FAQ por palavras-chave (sem custo, sem depender de provedor
    externo); o contrato é o mesmo dos outros textos deste arquivo, então
    trocar para um LLM real no futuro não muda quem chama esta função."""
    if PROVEDOR_ATIVO == "llm":
        prompt = (
            f"Um professor do AIM.Edu perguntou: {pergunta!r}. Responda em português, de forma curta e "
            "objetiva, sobre como usar a plataforma. Se não souber, oriente a procurar a coordenação."
        )
        return _gerar_llm(prompt)

    pergunta_lower = (pergunta or "").lower()
    for palavras_chave, resposta in FAQ_PROFESSOR:
        if any(p in pergunta_lower for p in palavras_chave):
            return resposta
    return RESPOSTA_PADRAO_DUVIDA


def resumo_engajamento_professor(nome_professor: str, disciplina, turmas_info: list) -> str:
    """Gera o texto do relatório da coordenação/direção sobre UM professor —
    adesão ao sistema (não desempenho dos alunos em si): quantos alunos das
    turmas dele já usaram cada módulo, e quantos alertas das turmas dele
    seguem pendentes. turmas_info é uma lista de dicts por turma, cada um
    com nome, total_alunos, alunos_com_diagnostico (na disciplina DELE — None
    se essa disciplina ainda não tem banco de itens no Diagnóstico Adaptativo),
    alunos_com_redacao, alertas_pendentes."""
    if PROVEDOR_ATIVO == "llm":
        prompt = (
            f"Resuma para a coordenação a adesão do professor {nome_professor} ({disciplina}) às "
            f"ferramentas do AIM.Edu, por turma: {turmas_info}. Português, curto, objetivo."
        )
        return _gerar_llm(prompt)

    if not turmas_info:
        return f"{nome_professor} ainda não está vinculado(a) a nenhuma turma."

    total_alunos = sum(t["total_alunos"] for t in turmas_info)
    total_red = sum(t["alunos_com_redacao"] for t in turmas_info)
    total_alertas = sum(t["alertas_pendentes"] for t in turmas_info)
    nomes_turmas = ", ".join(t["nome"] for t in turmas_info)

    partes = [
        f"{nome_professor}" + (f" ({disciplina})" if disciplina else "")
        + f" leciona em {len(turmas_info)} turma(s): {nomes_turmas}, somando {total_alunos} aluno(s)."
    ]

    tem_diagnostico_na_disciplina = any(t["alunos_com_diagnostico"] is not None for t in turmas_info)
    if tem_diagnostico_na_disciplina and total_alunos:
        total_diag = sum(t["alunos_com_diagnostico"] or 0 for t in turmas_info)
        pct_diag = round(100 * total_diag / total_alunos)
        partes.append(
            f"{pct_diag}% dos alunos dessas turmas já fizeram o Diagnóstico Adaptativo na disciplina "
            "dele/dela."
        )
    elif disciplina:
        partes.append(
            f"Ainda não há Diagnóstico Adaptativo disponível para {disciplina} — a adesão dele/dela por "
            "enquanto só pode ser medida pela Redação e pelos alertas do Radar."
        )

    if total_alunos:
        pct_red = round(100 * total_red / total_alunos)
        partes.append(
            f"{pct_red}% dos alunos dessas turmas já enviaram redação — um retrato geral do uso dos "
            "módulos pedagógicos nessas turmas."
        )

    if total_alertas:
        partes.append(f"Há {total_alertas} alerta(s) pendente(s) no Radar entre as turmas dele/dela.")
    else:
        partes.append("Não há alertas pendentes entre as turmas dele/dela no momento.")

    return " ".join(partes)
