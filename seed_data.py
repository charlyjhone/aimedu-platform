"""
Popula o banco local (SQLite) com dados de demonstração:
  - 1 escola ("Escola A"), 1 série (3º ano EM), 1 turma
  - usuários de demonstração para todos os papéis — aluno, coordenador,
    2 professores (Matemática e Português), família, direção (admin) e
    psicopedagoga (senha "123456" para todos)
  - banco de itens de Matemática: 5 eixos x 5 dificuldades = 25 questões
  - banco de itens de Português: 4 eixos x 5 dificuldades = 20 questões
    (prova de que o Diagnóstico Adaptativo e o Coordenador de Professores
    por IA funcionam com mais de uma disciplina — não só Matemática)

Rodar: python3 seed_data.py  (idempotente — pode rodar de novo sem duplicar)
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import create_app
from app.db import get_db, new_id
from app.auth import hash_senha

EIXOS_MATEMATICA = ["Números", "Álgebra e Funções", "Geometria", "Grandezas e Medidas", "Probabilidade e Estatística"]

# (eixo, dificuldade) -> item. Uma questão por combinação = 25 itens no total.
ITENS_MATEMATICA = [
    # ---- Números ----
    dict(eixo="Números", dif=1, enunciado="Uma loja deu 10% de desconto em um produto de R$ 200. Qual o valor do desconto?",
         alts=[("A","R$ 10"),("B","R$ 20"),("C","R$ 30"),("D","R$ 2")], correta="B",
         exp="10% de 200 = 0,10 × 200 = R$ 20."),
    dict(eixo="Números", dif=2, enunciado="Um produto custava R$ 80 e teve aumento de 15%. Qual o novo preço?",
         alts=[("A","R$ 92"),("B","R$ 95"),("C","R$ 88"),("D","R$ 100")], correta="A",
         exp="80 × 1,15 = R$ 92."),
    dict(eixo="Números", dif=3, enunciado="Um investimento de R$ 1.000 rende 2% ao mês, em juros compostos. Qual o valor aproximado após 2 meses?",
         alts=[("A","R$ 1.020"),("B","R$ 1.040"),("C","R$ 1.040,40"),("D","R$ 1.400")], correta="C",
         exp="1000 × 1,02² = 1000 × 1,0404 = R$ 1.040,40."),
    dict(eixo="Números", dif=4, enunciado="Se 3/5 de uma turma de 40 alunos foram aprovados diretamente, quantos alunos ficaram para recuperação?",
         alts=[("A","16"),("B","24"),("C","8"),("D","12")], correta="A",
         exp="3/5 de 40 = 24 aprovados; 40 − 24 = 16 para recuperação."),
    dict(eixo="Números", dif=5, enunciado="Uma dívida de R$ 5.000 é paga com juros compostos de 3% ao mês durante 3 meses, sem amortização. Qual o valor aproximado da dívida ao final?",
         alts=[("A","R$ 5.450"),("B","R$ 5.463,64"),("C","R$ 5.150"),("D","R$ 5.900")], correta="B",
         exp="5000 × 1,03³ ≈ 5000 × 1,092727 ≈ R$ 5.463,64."),

    # ---- Álgebra e Funções ----
    dict(eixo="Álgebra e Funções", dif=1, enunciado="Se x + 5 = 12, qual o valor de x?",
         alts=[("A","5"),("B","6"),("C","7"),("D","17")], correta="C", exp="x = 12 − 5 = 7."),
    dict(eixo="Álgebra e Funções", dif=2, enunciado="Uma corrida de táxi custa R$ 4 fixos mais R$ 2 por km rodado. Quanto custa uma corrida de 8 km?",
         alts=[("A","R$ 16"),("B","R$ 20"),("C","R$ 24"),("D","R$ 12")], correta="B",
         exp="4 + 2×8 = 4 + 16 = R$ 20."),
    dict(eixo="Álgebra e Funções", dif=3, enunciado="Na função f(x) = 2x² − 3x + 1, qual o valor de f(2)?",
         alts=[("A","3"),("B","5"),("C","7"),("D","9")], correta="A", exp="2(4) − 3(2) + 1 = 8 − 6 + 1 = 3."),
    dict(eixo="Álgebra e Funções", dif=4, enunciado="Duas empresas de aluguel de carro cobram: A) R$ 100 fixos + R$ 0,50/km; B) R$ 0,80/km sem taxa fixa. A partir de quantos km rodados a empresa A fica mais barata?",
         alts=[("A","200 km"),("B","300 km"),("C","333 km"),("D","400 km")], correta="C",
         exp="100 + 0,5k < 0,8k → 100 < 0,3k → k > 333,3 km."),
    dict(eixo="Álgebra e Funções", dif=5, enunciado="A função quadrática f(x) = x² − 6x + 8 tem seu valor mínimo em qual ponto?",
         alts=[("A","x = 2"),("B","x = 3"),("C","x = 4"),("D","x = 6")], correta="B",
         exp="Vértice em x = −b/2a = 6/2 = 3."),

    # ---- Geometria ----
    dict(eixo="Geometria", dif=1, enunciado="Qual é a área de um retângulo de 4 cm de largura por 5 cm de altura?",
         alts=[("A","9 cm²"),("B","20 cm²"),("C","18 cm²"),("D","25 cm²")], correta="B", exp="Área = 4 × 5 = 20 cm²."),
    dict(eixo="Geometria", dif=2, enunciado="Um terreno quadrado tem 100 m² de área. Qual é o perímetro desse terreno?",
         alts=[("A","10 m"),("B","20 m"),("C","40 m"),("D","100 m")], correta="C",
         exp="Lado = √100 = 10 m; perímetro = 4 × 10 = 40 m."),
    dict(eixo="Geometria", dif=3, enunciado="Um triângulo retângulo tem catetos de 6 cm e 8 cm. Qual é a medida da hipotenusa?",
         alts=[("A","10 cm"),("B","12 cm"),("C","14 cm"),("D","9 cm")], correta="A",
         exp="Pitágoras: √(6²+8²) = √(36+64) = √100 = 10 cm."),
    dict(eixo="Geometria", dif=4, enunciado="Uma caixa d'água cilíndrica tem raio de 2 m e altura de 3 m. Qual é o volume aproximado (use π ≈ 3,14)?",
         alts=[("A","18,84 m³"),("B","37,68 m³"),("C","12,56 m³"),("D","24 m³")], correta="B",
         exp="V = π r² h = 3,14 × 4 × 3 = 37,68 m³."),
    dict(eixo="Geometria", dif=5, enunciado="Um cone tem raio 3 cm e altura 4 cm. Qual é a área da superfície lateral (use π ≈ 3,14 e geratriz g)?",
         alts=[("A","37,68 cm²"),("B","47,1 cm²"),("C","62,8 cm²"),("D","28,26 cm²")], correta="B",
         exp="g = √(3²+4²) = 5; Área lateral = π r g = 3,14 × 3 × 5 = 47,1 cm²."),

    # ---- Grandezas e Medidas ----
    dict(eixo="Grandezas e Medidas", dif=1, enunciado="Quantos centímetros há em 2,5 metros?",
         alts=[("A","25 cm"),("B","250 cm"),("C","2.500 cm"),("D","0,25 cm")], correta="B", exp="1 m = 100 cm, então 2,5 m = 250 cm."),
    dict(eixo="Grandezas e Medidas", dif=2, enunciado="Um carro percorre 240 km em 4 horas, com velocidade constante. Qual é a velocidade média?",
         alts=[("A","40 km/h"),("B","60 km/h"),("C","80 km/h"),("D","96 km/h")], correta="B", exp="240 ÷ 4 = 60 km/h."),
    dict(eixo="Grandezas e Medidas", dif=3, enunciado="Uma receita usa 250 g de farinha para 4 pessoas. Quantos gramas são necessários para 10 pessoas, mantendo a proporção?",
         alts=[("A","500 g"),("B","625 g"),("C","750 g"),("D","1.000 g")], correta="B",
         exp="Regra de três: 250/4 = x/10 → x = 2500/4 = 625 g."),
    dict(eixo="Grandezas e Medidas", dif=4, enunciado="Uma torneira enche um tanque de 900 litros em 3 horas. Trabalhando junto com uma segunda torneira que sozinha levaria 6 horas, em quanto tempo enchem o tanque juntas?",
         alts=[("A","1 hora"),("B","1,5 hora"),("C","2 horas"),("D","2,5 horas")], correta="C",
         exp="Vazão conjunta = 1/3 + 1/6 = 1/2 do tanque por hora → 2 horas para encher."),
    dict(eixo="Grandezas e Medidas", dif=5, enunciado="Uma escala de mapa é 1:50.000. Uma distância de 3,4 cm no mapa corresponde a quantos km na realidade?",
         alts=[("A","1,7 km"),("B","17 km"),("C","0,17 km"),("D","170 km")], correta="A",
         exp="3,4 cm × 50.000 = 170.000 cm = 1.700 m = 1,7 km."),

    # ---- Probabilidade e Estatística ----
    dict(eixo="Probabilidade e Estatística", dif=1, enunciado="Em um lançamento de um dado comum, qual a probabilidade de sair o número 4?",
         alts=[("A","1/2"),("B","1/6"),("C","1/4"),("D","1/3")], correta="B", exp="O dado tem 6 faces igualmente prováveis: 1/6."),
    dict(eixo="Probabilidade e Estatística", dif=2, enunciado="As notas de 5 alunos foram: 6, 7, 8, 7, 7. Qual é a média?",
         alts=[("A","6,8"),("B","7"),("C","7,2"),("D","7,4")], correta="B", exp="(6+7+8+7+7)/5 = 35/5 = 7."),
    dict(eixo="Probabilidade e Estatística", dif=3, enunciado="Em uma urna há 4 bolas vermelhas e 6 azuis. Qual a probabilidade de tirar uma bola vermelha?",
         alts=[("A","0,4"),("B","0,6"),("C","0,25"),("D","0,1")], correta="A", exp="4 vermelhas de 10 total = 4/10 = 0,4."),
    dict(eixo="Probabilidade e Estatística", dif=4, enunciado="Qual é a mediana do conjunto de dados: 2, 4, 4, 6, 9, 12, 15?",
         alts=[("A","4"),("B","6"),("C","9"),("D","7,5")], correta="B",
         exp="Com 7 valores ordenados, a mediana é o 4º valor: 6."),
    dict(eixo="Probabilidade e Estatística", dif=5, enunciado="Duas moedas honestas são lançadas. Qual a probabilidade de sair pelo menos uma cara?",
         alts=[("A","1/4"),("B","1/2"),("C","3/4"),("D","1")], correta="C",
         exp="P(nenhuma cara) = 1/4; P(pelo menos uma) = 1 − 1/4 = 3/4."),
]

EIXOS_PORTUGUES = ["Leitura e Interpretação de Textos", "Gramática e Norma Culta", "Literatura e Interpretação", "Produção Textual e Coesão"]

# (eixo, dificuldade) -> item. Uma questão por combinação = 20 itens no total.
ITENS_PORTUGUES = [
    # ---- Leitura e Interpretação de Textos ----
    dict(eixo="Leitura e Interpretação de Textos", dif=1,
         enunciado="Na frase \"No trabalho, às vezes preciso engolir sapos\", a expressão \"engolir sapos\" significa:",
         alts=[("A","comer algo desagradável"),("B","suportar calado situações desagradáveis"),
               ("C","ter medo de anfíbios"),("D","cometer um erro grave")], correta="B",
         exp="\"Engolir sapos\" é expressão idiomática para suportar calado algo desagradável."),
    dict(eixo="Leitura e Interpretação de Textos", dif=2,
         enunciado="O provérbio \"Em terra de cego, quem tem um olho é rei\" quer dizer que:",
         alts=[("A","pessoas com deficiência visual são respeitadas"),
               ("B","quem tem pouca vantagem se destaca onde os outros têm menos ainda"),
               ("C","é preciso ter os dois olhos para liderar"),("D","reis eram frequentemente cegos")],
         correta="B", exp="O provérbio indica que uma pequena vantagem já basta para se destacar num grupo com menos ainda."),
    dict(eixo="Leitura e Interpretação de Textos", dif=3,
         enunciado="\"O uso excessivo de agrotóxicos vem contaminando lençóis freáticos em diversas regiões do país, "
                    "afetando tanto a qualidade da água consumida pela população quanto a biodiversidade local.\" "
                    "Qual é a ideia central do texto?",
         alts=[("A","a agricultura brasileira é a mais produtiva do mundo"),
               ("B","o uso excessivo de agrotóxicos contamina a água e prejudica a biodiversidade"),
               ("C","lençóis freáticos não afetam a saúde humana"),
               ("D","a biodiversidade brasileira é irrelevante para a agricultura")],
         correta="B", exp="O texto liga diretamente o uso excessivo de agrotóxicos à contaminação da água e ao prejuízo à biodiversidade."),
    dict(eixo="Leitura e Interpretação de Textos", dif=4,
         enunciado="\"Claro, mais um feriado prolongado bem no meio do projeto — que sorte a nossa.\" O tom predominante da frase é:",
         alts=[("A","comemorativo"),("B","irônico"),("C","neutro e informativo"),("D","formal e técnico")],
         correta="B", exp="O contexto (feriado atrapalhando o projeto) associado a \"que sorte a nossa\" indica ironia, não comemoração real."),
    dict(eixo="Leitura e Interpretação de Textos", dif=5,
         enunciado="\"Embora os defensores do projeto afirmem que ele trará empregos, os dados apresentados não "
                    "detalham nem o número nem a qualidade desses postos de trabalho, o que sugere que o argumento é "
                    "mais retórico do que fundamentado.\" A crítica do autor está baseada principalmente:",
         alts=[("A","na discordância com a criação de empregos em si"),
               ("B","na ausência de dados concretos que sustentem o argumento apresentado"),
               ("C","na comparação com outros projetos semelhantes"),
               ("D","na opinião pessoal do autor sobre o tema")],
         correta="B", exp="O autor não nega os empregos; aponta a falta de dados que comprovem a afirmação, tornando o argumento retórico."),

    # ---- Gramática e Norma Culta ----
    dict(eixo="Gramática e Norma Culta", dif=1, enunciado="\"Os alunos ___ para a prova ontem.\" Qual forma completa corretamente a frase?",
         alts=[("A","estudou"),("B","estudaram"),("C","estuda"),("D","estudam")], correta="B",
         exp="Sujeito plural (\"os alunos\") exige verbo no plural: estudaram."),
    dict(eixo="Gramática e Norma Culta", dif=2, enunciado="\"Cheguei ___ escola às 7h.\" Qual opção está correta?",
         alts=[("A","a"),("B","à"),("C","há"),("D","as")], correta="B",
         exp="\"À\" = a (preposição) + a (artigo feminino antes de \"escola\"), indicando crase."),
    dict(eixo="Gramática e Norma Culta", dif=3, enunciado="Qual frase segue a norma culta quanto à colocação pronominal em início de frase?",
         alts=[("A","Me diga a verdade."),("B","Diga-me a verdade."),("C","Se diga a verdade."),("D","Dizem-me a verdade sempre.")],
         correta="B", exp="A norma culta formal evita iniciar frase com pronome oblíquo átono; usa-se \"Diga-me\"."),
    dict(eixo="Gramática e Norma Culta", dif=4, enunciado="\"Prefiro café ___ chá.\" Qual preposição a norma culta exige com o verbo \"preferir\"?",
         alts=[("A","que"),("B","do que"),("C","a"),("D","com")], correta="C",
         exp="O verbo \"preferir\", na norma culta, rege a preposição \"a\": \"prefiro X a Y\", sem \"que\"/\"do que\"."),
    dict(eixo="Gramática e Norma Culta", dif=5,
         enunciado="\"Seguem ___ à carta os documentos solicitados.\" Qual forma de \"anexo\" concorda corretamente com \"os documentos\"?",
         alts=[("A","anexo"),("B","anexos"),("C","anexa"),("D","anexas")], correta="B",
         exp="\"Anexo\" funciona como adjetivo e concorda com \"os documentos\" (masculino plural): \"seguem anexos à carta...\"."),

    # ---- Literatura e Interpretação ----
    dict(eixo="Literatura e Interpretação", dif=1, enunciado="Qual característica é mais associada ao Romantismo brasileiro (1ª metade do século XIX)?",
         alts=[("A","objetividade científica e realismo cru"),
               ("B","idealização do amor, da natureza e do herói nacional (indianismo)"),
               ("C","linguagem hermética e antirracionalista"),("D","foco exclusivo em temas urbanos industriais")],
         correta="B", exp="O Romantismo brasileiro idealiza o amor, a natureza e cria o herói nacional, sobretudo no indianismo."),
    dict(eixo="Literatura e Interpretação", dif=2, enunciado="\"Ela tem um coração de gelo\" é um exemplo de:",
         alts=[("A","metonímia"),("B","metáfora"),("C","hipérbole"),("D","eufemismo")], correta="B",
         exp="Há comparação implícita (coração comparado a algo frio, sem \"como\"), o que caracteriza a metáfora."),
    dict(eixo="Literatura e Interpretação", dif=3, enunciado="A Semana de Arte Moderna de 1922 é associada a qual proposta estética?",
         alts=[("A","retomar rigidamente as formas clássicas parnasianas"),
               ("B","romper com o passado por meio de linguagem coloquial, verso livre e valorização da cultura nacional"),
               ("C","imitar integralmente os modelos europeus românticos"),
               ("D","abandonar completamente qualquer referência ao Brasil")],
         correta="B", exp="O Modernismo de 1922 propôs ruptura com o passado, linguagem coloquial, verso livre e valorização do nacional."),
    dict(eixo="Literatura e Interpretação", dif=4,
         enunciado="Num romance narrado em terceira pessoa que revela pensamentos e sentimentos de vários personagens, o narrador é chamado de:",
         alts=[("A","narrador-personagem"),("B","narrador onisciente"),("C","narrador testemunha"),("D","narrador limitado à primeira pessoa")],
         correta="B", exp="Um narrador em 3ª pessoa que acessa a mente de vários personagens é onisciente."),
    dict(eixo="Literatura e Interpretação", dif=5, enunciado="Em Dom Casmurro, de Machado de Assis, a ambiguidade central da obra está relacionada a:",
         alts=[("A","a certeza da traição de Capitu, comprovada por provas concretas de Bentinho"),
               ("B","a impossibilidade de o leitor saber com certeza se Capitu traiu Bentinho, pois o narrador não é confiável"),
               ("C","a disputa de terras entre as famílias de Bentinho e Capitu"),
               ("D","o conflito religioso entre Bentinho e o seminário")],
         correta="B", exp="A obra é célebre justamente por deixar em aberto, via narrador não confiável, se Capitu realmente traiu Bentinho."),

    # ---- Produção Textual e Coesão ----
    dict(eixo="Produção Textual e Coesão", dif=1, enunciado="\"Estudou bastante; portanto, foi bem na prova.\" A palavra \"portanto\" estabelece relação de:",
         alts=[("A","oposição"),("B","conclusão ou consequência"),("C","adição"),("D","comparação")], correta="B",
         exp="\"Portanto\" é conectivo conclusivo, introduzindo a consequência do que foi dito antes."),
    dict(eixo="Produção Textual e Coesão", dif=2, enunciado="\"Maria comprou um carro novo. Ela está muito feliz com ele.\" A que \"ele\" se refere?",
         alts=[("A","a Maria"),("B","ao carro"),("C","à felicidade"),("D","a nada, é apenas estilístico")], correta="B",
         exp="\"Ele\" retoma \"um carro novo\" por coesão referencial (anáfora)."),
    dict(eixo="Produção Textual e Coesão", dif=3,
         enunciado="Num parágrafo de desenvolvimento de uma dissertação-argumentativa, a estrutura mais recomendada é:",
         alts=[("A","apenas uma opinião pessoal, sem justificativa"),
               ("B","tópico frasal seguido de argumentação e, se possível, exemplificação"),
               ("C","uma lista de frases soltas sem conexão"),("D","repetir a introdução com outras palavras")],
         correta="B", exp="O parágrafo padrão de desenvolvimento apresenta um tópico frasal, argumenta e, quando possível, exemplifica."),
    dict(eixo="Produção Textual e Coesão", dif=4,
         enunciado="Em uma redação dissertativa-argumentativa no modelo ENEM, o registro linguístico esperado é:",
         alts=[("A","informal, com gírias e abreviações"),("B","formal, seguindo a norma culta da língua"),
               ("C","técnico-científico com jargões de uma área específica"),("D","poético, com muitas figuras de linguagem")],
         correta="B", exp="O ENEM exige registro formal, dentro da norma culta, na redação dissertativa-argumentativa."),
    dict(eixo="Produção Textual e Coesão", dif=5,
         enunciado="\"Todo mundo sabe que essa política é ruim, então não precisa nem discutir.\" Esse trecho tem um problema argumentativo porque:",
         alts=[("A","apresenta dados estatísticos em excesso"),
               ("B","recorre ao senso comum (\"todo mundo sabe\") como se fosse prova suficiente, sem evidências"),
               ("C","usa linguagem excessivamente técnica"),("D","não usa conectivos suficientes")],
         correta="B", exp="Apelar ao senso comum sem apresentar evidências é uma falha argumentativa (apelo à opinião geral)."),
]


def run():
    app = create_app()
    with app.app_context():
        db = get_db()

        if db.execute("select count(*) c from escolas").fetchone()["c"] == 0:
            escola_id = new_id()
            db.execute("insert into escolas (id, nome) values (?,?)", (escola_id, "Escola A"))

            serie_id = new_id()
            db.execute("insert into series (id, escola_id, nome, etapa, ordem) values (?,?,?,?,?)",
                       (serie_id, escola_id, "3º ano EM", "medio", 15))

            turma_id = new_id()
            db.execute("insert into turmas (id, serie_id, nome, ano_letivo) values (?,?,?,?)",
                       (turma_id, serie_id, "3º EM A", 2027))

            def add_usuario(nome, email, papel):
                uid = new_id()
                db.execute(
                    "insert into usuarios (id, escola_id, nome, email, senha_hash, papel) values (?,?,?,?,?,?)",
                    (uid, escola_id, nome, email, hash_senha("123456"), papel),
                )
                return uid

            aluno_uid = add_usuario("Ana Souza", "aluno@escolaa.com.br", "aluno")
            add_usuario("Coordenação Escola A", "coordenacao@escolaa.com.br", "coordenador")
            add_usuario("Prof. Carlos Lima", "professor@escolaa.com.br", "professor")

            db.execute("insert into alunos (id, usuario_id, turma_id) values (?,?,?)",
                       (new_id(), aluno_uid, turma_id))

            print("Escola, turma e usuários de demonstração criados.")
            print("  aluno@escolaa.com.br / 123456")
            print("  coordenacao@escolaa.com.br / 123456")
            print("  professor@escolaa.com.br / 123456")
        else:
            print("Já existem dados — pulando criação de escola/usuários.")

        # Bloco independente (adicionado depois do primeiro deploy): cria um usuário de
        # família e vincula à aluna de demonstração. Roda mesmo que o bloco acima já
        # tenha sido pulado — é o padrão que qualquer novo dado de demonstração deve
        # seguir daqui pra frente, em vez de expandir o "if escolas count == 0" acima.
        if db.execute("select count(*) c from usuarios where papel = 'familia'").fetchone()["c"] == 0:
            aluno_usuario = db.execute(
                "select id, escola_id from usuarios where email = 'aluno@escolaa.com.br'"
            ).fetchone()
            if aluno_usuario:
                familia_uid = new_id()
                db.execute(
                    "insert into usuarios (id, escola_id, nome, email, senha_hash, papel) values (?,?,?,?,?,?)",
                    (familia_uid, aluno_usuario["escola_id"], "Família de Ana Souza",
                     "familia@escolaa.com.br", hash_senha("123456"), "familia"),
                )
                db.execute(
                    "update alunos set responsavel_usuario_id = ? where usuario_id = ?",
                    (familia_uid, aluno_usuario["id"]),
                )
                print("Usuário de família criado e vinculado à aluna de demonstração.")
                print("  familia@escolaa.com.br / 123456")
            else:
                print("Aluno de demonstração não encontrado — pulando criação da família.")
        else:
            print("Usuário de família já existe — pulando.")

        # Bloco independente: vincula o professor de demonstração à turma via
        # professor_turma — sem isso, o módulo de Inclusão não teria como
        # mostrar nenhum aluno para o papel "professor" testar. Mesmo padrão
        # de idempotência independente dos blocos acima.
        if db.execute("select count(*) c from professores").fetchone()["c"] == 0:
            professor_usuario = db.execute(
                "select id from usuarios where email = 'professor@escolaa.com.br'"
            ).fetchone()
            turma = db.execute("select id from turmas limit 1").fetchone()
            if professor_usuario and turma:
                professor_id = new_id()
                db.execute(
                    "insert into professores (id, usuario_id, disciplina) values (?,?,?)",
                    (professor_id, professor_usuario["id"], "Matemática"),
                )
                db.execute(
                    "insert into professor_turma (professor_id, turma_id) values (?,?)",
                    (professor_id, turma["id"]),
                )
                print("Professor de demonstração vinculado à turma.")
            else:
                print("Professor ou turma de demonstração não encontrados — pulando vínculo.")
        else:
            print("Registro de professor já existe — pulando.")

        # Bloco independente: cria uma segunda professora, de Português, e
        # vincula à mesma turma — é o que prova, na demonstração, que o
        # Diagnóstico Adaptativo e o Coordenador de Professores por IA
        # funcionam com mais de uma disciplina ao mesmo tempo, não só
        # Matemática (cada professor só vê o Diagnóstico Adaptativo na
        # própria disciplina).
        if db.execute("select count(*) c from usuarios where email = 'professor2@escolaa.com.br'").fetchone()["c"] == 0:
            escola = db.execute("select id from escolas limit 1").fetchone()
            turma = db.execute("select id from turmas limit 1").fetchone()
            if escola and turma:
                professora_uid = new_id()
                db.execute(
                    "insert into usuarios (id, escola_id, nome, email, senha_hash, papel) values (?,?,?,?,?,?)",
                    (professora_uid, escola["id"], "Profa. Beatriz Nunes", "professor2@escolaa.com.br",
                     hash_senha("123456"), "professor"),
                )
                professora_id = new_id()
                db.execute(
                    "insert into professores (id, usuario_id, disciplina) values (?,?,?)",
                    (professora_id, professora_uid, "Português"),
                )
                db.execute(
                    "insert into professor_turma (professor_id, turma_id) values (?,?)",
                    (professora_id, turma["id"]),
                )
                print("Professora de Português de demonstração criada e vinculada à turma.")
                print("  professor2@escolaa.com.br / 123456")
            else:
                print("Escola ou turma de demonstração não encontradas — pulando criação da professora de Português.")
        else:
            print("Professora de Português de demonstração já existe — pulando.")

        # Bloco independente: cadastro de inclusão de demonstração para a aluna
        # de demonstração, para o módulo já nascer com algo visível.
        if db.execute("select count(*) c from inclusao_cadastro").fetchone()["c"] == 0:
            aluno_row = db.execute(
                "select al.id from alunos al join usuarios us on us.id = al.usuario_id "
                "where us.email = 'aluno@escolaa.com.br'"
            ).fetchone()
            coordenacao = db.execute(
                "select id from usuarios where email = 'coordenacao@escolaa.com.br'"
            ).fetchone()
            if aluno_row and coordenacao:
                db.execute(
                    "insert into inclusao_cadastro "
                    "(id, aluno_id, categoria, diagnostico_formal, adaptacoes, apoio_especializado, observacoes, criado_por_usuario_id) "
                    "values (?,?,?,?,?,?,?,?)",
                    (new_id(), aluno_row["id"], "TDAH", True,
                     "Tempo adicional de 25% em provas; instruções repetidas por escrito; sentar nas primeiras carteiras.",
                     "Acompanhamento psicopedagógico quinzenal (fora da escola).",
                     "Cadastro de demonstração — dados fictícios.",
                     coordenacao["id"]),
                )
                print("Cadastro de inclusão de demonstração criado.")
            else:
                print("Aluno ou coordenação de demonstração não encontrados — pulando cadastro de inclusão.")
        else:
            print("Cadastro de inclusão já existe — pulando.")

        # Bloco independente: cria a conta de direção (o "admin" do sistema —
        # não é um papel novo, é o papel 'direcao' que já existia no schema,
        # só que nunca tinha sido semeado). Sem isso não existe nenhuma conta
        # com acesso total (inclusive exclusão definitiva de usuário) para
        # logar e testar/usar.
        if db.execute("select count(*) c from usuarios where papel = 'direcao'").fetchone()["c"] == 0:
            escola = db.execute("select id from escolas limit 1").fetchone()
            if escola:
                db.execute(
                    "insert into usuarios (id, escola_id, nome, email, senha_hash, papel) values (?,?,?,?,?,?)",
                    (new_id(), escola["id"], "Direção Escola A", "direcao@escolaa.com.br", hash_senha("123456"), "direcao"),
                )
                print("Usuário de direção (admin) criado.")
                print("  direcao@escolaa.com.br / 123456")
            else:
                print("Escola de demonstração não encontrada — pulando criação da direção.")
        else:
            print("Usuário de direção já existe — pulando.")

        # Bloco independente: cria a conta de psicopedagoga — o papel
        # responsável por editar o cadastro de inclusão e o PEI dos alunos
        # (professor só consulta essas informações na ficha do aluno).
        if db.execute("select count(*) c from usuarios where papel = 'psicopedagoga'").fetchone()["c"] == 0:
            escola = db.execute("select id from escolas limit 1").fetchone()
            if escola:
                db.execute(
                    "insert into usuarios (id, escola_id, nome, email, senha_hash, papel) values (?,?,?,?,?,?)",
                    (new_id(), escola["id"], "Psicopedagoga Escola A", "psicopedagoga@escolaa.com.br",
                     hash_senha("123456"), "psicopedagoga"),
                )
                print("Usuário de psicopedagoga criado.")
                print("  psicopedagoga@escolaa.com.br / 123456")
            else:
                print("Escola de demonstração não encontrada — pulando criação da psicopedagoga.")
        else:
            print("Usuário de psicopedagoga já existe — pulando.")

        # Bancos de itens: cada disciplina é um bloco independente, gatilhado
        # pela contagem de itens DAQUELA disciplina — não pela contagem geral
        # de itens_banco. Assim, adicionar o banco de Português não fica
        # bloqueado por Matemática já estar populada (e o mesmo vale para
        # qualquer disciplina futura).
        if db.execute("select count(*) c from itens_banco where disciplina = 'matematica'").fetchone()["c"] == 0:
            for item in ITENS_MATEMATICA:
                alternativas = [{"letra": l, "texto": t} for l, t in item["alts"]]
                db.execute(
                    "insert into itens_banco (id, disciplina, eixo_bncc, dificuldade, enunciado, alternativas, correta, explicacao) "
                    "values (?,?,?,?,?,?,?,?)",
                    (new_id(), "matematica", item["eixo"], item["dif"], item["enunciado"],
                     json.dumps(alternativas, ensure_ascii=False), item["correta"], item["exp"]),
                )
            print(f"{len(ITENS_MATEMATICA)} questões de Matemática cadastradas no banco de itens.")
        else:
            print("Banco de itens de Matemática já populado — pulando.")

        if db.execute("select count(*) c from itens_banco where disciplina = 'portugues'").fetchone()["c"] == 0:
            for item in ITENS_PORTUGUES:
                alternativas = [{"letra": l, "texto": t} for l, t in item["alts"]]
                db.execute(
                    "insert into itens_banco (id, disciplina, eixo_bncc, dificuldade, enunciado, alternativas, correta, explicacao) "
                    "values (?,?,?,?,?,?,?,?)",
                    (new_id(), "portugues", item["eixo"], item["dif"], item["enunciado"],
                     json.dumps(alternativas, ensure_ascii=False), item["correta"], item["exp"]),
                )
            print(f"{len(ITENS_PORTUGUES)} questões de Português cadastradas no banco de itens.")
        else:
            print("Banco de itens de Português já populado — pulando.")

        db.commit()


if __name__ == "__main__":
    run()
