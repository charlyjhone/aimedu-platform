"""
Módulo do AIM.Edu: Coordenador de Professores por IA.

Junta, num só lugar, tudo que os outros módulos pedagógicos já gravam sobre
uma turma — Diagnóstico Adaptativo, Redação e Radar da Coordenação — e
devolve isso em 4 formatos, todos usando app.ai_engine (mesma camada de IA de
todo o projeto, hoje por regras locais):

  1. Acompanhamento de desempenho da turma — o professor abre a própria
     turma e vê o Diagnóstico Adaptativo NA DISCIPLINA DELE (eixos da BNCC
     mais fracos, nível médio), a nota média de redação, as competências do
     ENEM mais fracas e os alertas pendentes.
  2. Sugestões pedagógicas — a partir dos mesmos dados, uma lista curta de
     ações práticas para o professor.
  3. Assistente de dúvidas — um FAQ simples onde o professor pergunta sobre
     o próprio sistema (PEI, Inclusão, senha, etc.) e recebe uma resposta na
     hora, com histórico salvo.
  4. Relatório da coordenação sobre os professores — só coordenação/direção:
     adesão de cada professor às ferramentas (não desempenho dos alunos em
     si), turma por turma, com o Diagnóstico Adaptativo já filtrado pela
     disciplina de cada professor.

Sobre disciplinas: o Diagnóstico Adaptativo (app.modules.diagnostico) só
existe para as disciplinas que já têm itens cadastrados em itens_banco (hoje
Matemática e Português — ver seed_data.py). O campo professores.disciplina é
texto livre ("Matemática", "Português"...) preenchido na Gestão de Usuários;
_normalizar_disciplina() abaixo tira acentos/caixa para comparar com o slug
salvo em itens_banco/diagnosticos ("matematica", "portugues"). Um professor
de uma disciplina sem banco de itens ainda (ex.: História) simplesmente não
vê o bloco de Diagnóstico Adaptativo — vê normalmente Redação e Radar, que
são gerais. A coordenação/direção, ao abrir uma turma, vê um bloco por
disciplina que já tiver diagnóstico ali, não só a de um professor.

Nenhuma tabela nova de dado pedagógico é criada aqui além de
duvidas_professor (histórico do assistente) — os números vêm de tabelas que
app.modules.diagnostico, redacao.py e radar_coordenacao.py já preenchem,
prova de que é um projeto único e interligado, não um módulo isolado.
"""
import unicodedata

from flask import Blueprint, render_template, redirect, url_for, request, flash

from ..db import get_db, new_id
from ..auth import login_obrigatorio, usuario_logado, escopo_etapa, PAPEIS_DIRECAO
from ..ai_engine import (
    resumo_desempenho_turma,
    sugestoes_pedagogicas_turma,
    responder_duvida_professor,
    resumo_engajamento_professor,
    NOMES_COMPETENCIA_REDACAO,
)

bp = Blueprint("coordenador_professores", __name__, url_prefix="/professores/coordenador-ia")

PAPEIS_ACESSO = ("professor", "coordenador") + PAPEIS_DIRECAO
PAPEIS_DUVIDAS = ("professor", "coordenador", "psicopedagoga") + PAPEIS_DIRECAO

LIMIAR_MINIMO_EIXO = 2  # só considera um eixo "fraco" se já foram respondidas pelo menos N questões dele
LIMIAR_TAXA_EIXO_FRACO = 0.7  # eixo só entra como "fraco" se a taxa de acerto for menor que isso
LIMIAR_NOTA_COMPETENCIA_FRACA = 160  # competência (0-200) só entra como "fraca" se a média for menor que isso


def _normalizar_disciplina(texto):
    """'Matemática' -> 'matematica', 'Português' -> 'portugues' — para
    comparar o texto livre de professores.disciplina com o slug salvo em
    itens_banco.disciplina/diagnosticos.disciplina, sem exigir que a
    coordenação digite exatamente igual ao slug."""
    if not texto:
        return None
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return sem_acento.strip().lower() or None


def _escola_id_atual():
    return usuario_logado()["escola_id"]


def _professor_do_usuario(db, usuario_id):
    return db.execute("select * from professores where usuario_id = ?", (usuario_id,)).fetchone()


def _turmas_do_professor(db, professor_id, segmento=None):
    """'segmento' só é usado quando quem está olhando é um coordenador
    escopado vendo a turma de OUTRA pessoa (professor) — a visão do próprio
    professor sobre as turmas dele nunca é restringida por segmento, já que
    o segmento é um recorte de coordenação, não do professor."""
    if segmento:
        return db.execute(
            "select t.id, t.nome from turmas t "
            "join professor_turma pt on pt.turma_id = t.id "
            "join series s on s.id = t.serie_id "
            "where pt.professor_id = ? and s.etapa = ? order by t.nome",
            (professor_id, segmento),
        ).fetchall()
    return db.execute(
        "select t.id, t.nome from turmas t "
        "join professor_turma pt on pt.turma_id = t.id "
        "where pt.professor_id = ? order by t.nome",
        (professor_id,),
    ).fetchall()


def _turmas_da_escola(db, escola_id, segmento=None):
    if segmento:
        return db.execute(
            "select t.id, t.nome from turmas t "
            "join series s on s.id = t.serie_id "
            "where s.escola_id = ? and s.etapa = ? order by t.nome",
            (escola_id, segmento),
        ).fetchall()
    return db.execute(
        "select t.id, t.nome from turmas t "
        "join series s on s.id = t.serie_id "
        "where s.escola_id = ? order by t.nome",
        (escola_id,),
    ).fetchall()


def _professores_visiveis(db, escola_id, segmento=None):
    """Coordenação/direção sem segmento veem todos os professores da escola;
    coordenador escopado só vê professores que lecionam ao menos uma turma
    do próprio segmento (o mesmo professor pode aparecer pra mais de uma
    coordenação, se leciona em mais de um segmento — cada uma só enxerga o
    pedaço que é seu)."""
    if segmento:
        return db.execute(
            "select distinct p.id, us.nome, p.disciplina from professores p "
            "join usuarios us on us.id = p.usuario_id "
            "join professor_turma pt on pt.professor_id = p.id "
            "join turmas t on t.id = pt.turma_id join series s on s.id = t.serie_id "
            "where us.escola_id = ? and s.etapa = ? order by us.nome",
            (escola_id, segmento),
        ).fetchall()
    return db.execute(
        "select p.id, us.nome, p.disciplina from professores p "
        "join usuarios us on us.id = p.usuario_id "
        "where us.escola_id = ? order by us.nome",
        (escola_id,),
    ).fetchall()


def _turma_da_escola(db, turma_id, escola_id, segmento=None):
    if segmento:
        return db.execute(
            "select t.id, t.nome from turmas t "
            "join series s on s.id = t.serie_id "
            "where t.id = ? and s.escola_id = ? and s.etapa = ?",
            (turma_id, escola_id, segmento),
        ).fetchone()
    return db.execute(
        "select t.id, t.nome from turmas t "
        "join series s on s.id = t.serie_id "
        "where t.id = ? and s.escola_id = ?",
        (turma_id, escola_id),
    ).fetchone()


def _professor_pode_ver_turma(db, usuario, turma_id):
    if usuario["papel"] == "coordenador" or usuario["papel"] in PAPEIS_DIRECAO:
        return _turma_da_escola(db, turma_id, usuario["escola_id"], escopo_etapa(usuario)) is not None
    if usuario["papel"] == "professor":
        professor = _professor_do_usuario(db, usuario["id"])
        if not professor:
            return False
        return db.execute(
            "select 1 from professor_turma where professor_id = ? and turma_id = ?",
            (professor["id"], turma_id),
        ).fetchone() is not None
    return False


def _disciplinas_disponiveis(db):
    """Disciplinas com pelo menos 1 item no banco (as mesmas que o módulo de
    Diagnóstico Adaptativo oferece ao aluno)."""
    linhas = db.execute("select distinct disciplina from itens_banco").fetchall()
    return {linha["disciplina"] for linha in linhas}


def _disciplinas_com_diagnostico_na_turma(db, turma_id):
    """Disciplinas em que pelo menos um aluno da turma já finalizou um
    Diagnóstico Adaptativo — é isso que decide quantos blocos a coordenação
    vê na página da turma."""
    linhas = db.execute(
        "select distinct d.disciplina from diagnosticos d join alunos a on a.id = d.aluno_id "
        "where a.turma_id = ? and d.finalizado_em is not null",
        (turma_id,),
    ).fetchall()
    return [linha["disciplina"] for linha in linhas]


def _stats_gerais_turma(db, turma_id):
    """Números da turma que não dependem de disciplina: total de alunos,
    Redação e Radar."""
    total_alunos = db.execute(
        "select count(*) c from alunos where turma_id = ?", (turma_id,)
    ).fetchone()["c"]

    red = db.execute(
        "select count(*) n, avg(r.nota_c1) c1, avg(r.nota_c2) c2, avg(r.nota_c3) c3, "
        "avg(r.nota_c4) c4, avg(r.nota_c5) c5, "
        "count(distinct r.aluno_id) alunos_com_red "
        "from redacoes r join alunos a on a.id = r.aluno_id "
        "where a.turma_id = ?",
        (turma_id,),
    ).fetchone()
    alunos_com_redacao = red["alunos_com_red"] or 0
    media_nota_redacao = None
    competencias_fracas = []
    if red["n"]:
        medias = {"nota_c1": red["c1"], "nota_c2": red["c2"], "nota_c3": red["c3"],
                  "nota_c4": red["c4"], "nota_c5": red["c5"]}
        media_nota_redacao = sum(v or 0 for v in medias.values())
        piores = sorted(
            ((c, v) for c, v in medias.items() if v is not None and v < LIMIAR_NOTA_COMPETENCIA_FRACA),
            key=lambda kv: kv[1],
        )[:2]
        competencias_fracas = [NOMES_COMPETENCIA_REDACAO[c] for c, _ in piores]

    alertas_pendentes = db.execute(
        "select count(*) c from alertas_radar where turma_id = ? and resolvido = false", (turma_id,)
    ).fetchone()["c"]

    return {
        "total_alunos": total_alunos,
        "alunos_com_redacao": alunos_com_redacao,
        "media_nota_redacao": media_nota_redacao,
        "competencias_fracas": competencias_fracas,
        "alertas_pendentes": alertas_pendentes,
    }


def _stats_diagnostico_turma(db, turma_id, disciplina):
    """Números do Diagnóstico Adaptativo de UMA disciplina, para os alunos
    de uma turma: quantos já fizeram, nível médio e eixos da BNCC mais
    fracos (a mesma conta que antes misturava todas as disciplinas — agora
    sempre filtrada por 'disciplina')."""
    diag = db.execute(
        "select count(distinct a.id) alunos_com_diag, avg(d.nivel_final) media_nivel "
        "from alunos a join diagnosticos d on d.aluno_id = a.id "
        "where a.turma_id = ? and d.disciplina = ? and d.finalizado_em is not null",
        (turma_id, disciplina),
    ).fetchone()

    eixos_raw = db.execute(
        "select i.eixo_bncc eixo, "
        "sum(case when dr.correta then 1 else 0 end) acertos, count(*) total "
        "from alunos a "
        "join diagnosticos d on d.aluno_id = a.id "
        "join diagnostico_respostas dr on dr.diagnostico_id = d.id "
        "join itens_banco i on i.id = dr.item_id "
        "where a.turma_id = ? and d.disciplina = ? "
        "group by i.eixo_bncc",
        (turma_id, disciplina),
    ).fetchall()
    eixos_com_taxa = [
        (linha["eixo"] or "geral", linha["acertos"] / linha["total"])
        for linha in eixos_raw
        if linha["total"] >= LIMIAR_MINIMO_EIXO
    ]
    eixos_fracos = sorted(
        (et for et in eixos_com_taxa if et[1] < LIMIAR_TAXA_EIXO_FRACO),
        key=lambda et: et[1],
    )[:2]

    return {
        "alunos_com_diagnostico": diag["alunos_com_diag"] or 0,
        "media_nivel": diag["media_nivel"],
        "eixos_fracos": eixos_fracos,
    }


@bp.route("/")
@login_obrigatorio(papeis=PAPEIS_ACESSO)
def index():
    db = get_db()
    u = usuario_logado()

    if u["papel"] == "professor":
        professor = _professor_do_usuario(db, u["id"])
        turmas = _turmas_do_professor(db, professor["id"]) if professor else []
        return render_template("coordenador_professores_index.html", turmas=turmas, professores=None)

    escola_id = _escola_id_atual()
    segmento = escopo_etapa(u)
    turmas = _turmas_da_escola(db, escola_id, segmento)
    professores = _professores_visiveis(db, escola_id, segmento)
    return render_template("coordenador_professores_index.html", turmas=turmas, professores=professores)


@bp.route("/turma/<turma_id>")
@login_obrigatorio(papeis=PAPEIS_ACESSO)
def turma(turma_id):
    db = get_db()
    u = usuario_logado()

    if not _professor_pode_ver_turma(db, u, turma_id):
        flash("Você não tem acesso a esta turma.", "erro")
        return redirect(url_for("coordenador_professores.index"))

    turma_row = db.execute("select * from turmas where id = ?", (turma_id,)).fetchone()
    gerais = _stats_gerais_turma(db, turma_id)

    if u["papel"] == "professor":
        # Só a disciplina dele/dela — é isso que resolve um professor de
        # outra matéria não ver "eixos fracos" de uma disciplina que não é a
        # sua (o problema que esta versão corrige).
        professor = _professor_do_usuario(db, u["id"])
        disciplina_slug = _normalizar_disciplina(professor["disciplina"]) if professor else None
        if disciplina_slug and disciplina_slug in _disciplinas_disponiveis(db):
            diagnosticos_por_disciplina = {disciplina_slug: _stats_diagnostico_turma(db, turma_id, disciplina_slug)}
        else:
            diagnosticos_por_disciplina = {}
    else:
        # Coordenação/direção vê todas as disciplinas com dado nesta turma.
        disciplinas_presentes = _disciplinas_com_diagnostico_na_turma(db, turma_id)
        diagnosticos_por_disciplina = {d: _stats_diagnostico_turma(db, turma_id, d) for d in disciplinas_presentes}

    resumo = resumo_desempenho_turma(
        turma_row["nome"], gerais["total_alunos"], diagnosticos_por_disciplina,
        gerais["alunos_com_redacao"], gerais["media_nota_redacao"], gerais["competencias_fracas"],
        gerais["alertas_pendentes"],
    )
    sugestoes = sugestoes_pedagogicas_turma(
        diagnosticos_por_disciplina, gerais["competencias_fracas"], gerais["alertas_pendentes"]
    )

    return render_template(
        "coordenador_professores_turma.html", turma=turma_row, gerais=gerais,
        diagnosticos_por_disciplina=diagnosticos_por_disciplina, resumo=resumo, sugestoes=sugestoes,
    )


@bp.route("/duvidas", methods=["GET", "POST"])
@login_obrigatorio(papeis=PAPEIS_DUVIDAS)
def duvidas():
    db = get_db()
    u = usuario_logado()

    if request.method == "POST":
        pergunta = request.form.get("pergunta", "").strip()
        if not pergunta:
            flash("Escreva sua dúvida antes de enviar.", "erro")
            return redirect(url_for("coordenador_professores.duvidas"))

        resposta = responder_duvida_professor(pergunta)
        db.execute(
            "insert into duvidas_professor (id, usuario_id, pergunta, resposta_ia) values (?,?,?,?)",
            (new_id(), u["id"], pergunta, resposta),
        )
        db.commit()
        return redirect(url_for("coordenador_professores.duvidas"))

    historico = db.execute(
        "select * from duvidas_professor where usuario_id = ? order by criado_em desc",
        (u["id"],),
    ).fetchall()
    return render_template("coordenador_professores_duvidas.html", historico=historico)


@bp.route("/relatorio-professores")
@login_obrigatorio(papeis=["coordenador"] + list(PAPEIS_DIRECAO))
def relatorio_professores():
    db = get_db()
    escola_id = _escola_id_atual()
    segmento = escopo_etapa(usuario_logado())
    disciplinas_disponiveis = _disciplinas_disponiveis(db)

    professores = _professores_visiveis(db, escola_id, segmento)

    relatorios = []
    for prof in professores:
        disciplina_slug = _normalizar_disciplina(prof["disciplina"])
        tem_banco = disciplina_slug is not None and disciplina_slug in disciplinas_disponiveis

        # Um coordenador escopado só vê, dentro do relatório de cada
        # professor, as turmas do PRÓPRIO segmento — se o professor também
        # leciona em outro segmento, aquela parte é assunto da outra coordenação.
        turmas_do_prof = _turmas_do_professor(db, prof["id"], segmento)
        turmas_info = []
        for t in turmas_do_prof:
            gerais = _stats_gerais_turma(db, t["id"])
            alunos_com_diagnostico = None
            if tem_banco:
                diag = _stats_diagnostico_turma(db, t["id"], disciplina_slug)
                alunos_com_diagnostico = diag["alunos_com_diagnostico"]
            turmas_info.append({
                "nome": t["nome"],
                "total_alunos": gerais["total_alunos"],
                "alunos_com_diagnostico": alunos_com_diagnostico,
                "alunos_com_redacao": gerais["alunos_com_redacao"],
                "alertas_pendentes": gerais["alertas_pendentes"],
            })
        resumo = resumo_engajamento_professor(prof["nome"], prof["disciplina"], turmas_info)
        relatorios.append({"professor": prof, "turmas_info": turmas_info, "resumo": resumo})

    return render_template("coordenador_professores_relatorio.html", relatorios=relatorios)
