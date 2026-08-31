"""
Módulo do AIM.Edu: Coordenador de Professores por IA.

Junta, num só lugar, tudo que os outros módulos pedagógicos já gravam sobre
uma turma — Diagnóstico Adaptativo de Matemática, Redação e Radar da
Coordenação — e devolve isso em 4 formatos, todos usando app.ai_engine
(mesma camada de IA de todo o projeto, hoje por regras locais):

  1. Acompanhamento de desempenho da turma — o professor abre a própria
     turma e vê nível médio de matemática, eixos da BNCC mais fracos, nota
     média de redação, competências do ENEM mais fracas e alertas pendentes.
  2. Sugestões pedagógicas — a partir dos mesmos dados, uma lista curta de
     ações práticas para o professor.
  3. Assistente de dúvidas — um FAQ simples onde o professor pergunta sobre
     o próprio sistema (PEI, Inclusão, senha, etc.) e recebe uma resposta na
     hora, com histórico salvo.
  4. Relatório da coordenação sobre os professores — só coordenação/direção:
     adesão de cada professor às ferramentas (não desempenho dos alunos em
     si), turma por turma.

Nenhuma tabela nova de dado pedagógico é criada aqui além de
duvidas_professor (histórico do assistente) — os números vêm de tabelas que
diagnostico_matematica.py, redacao.py e radar_coordenacao.py já preenchem,
prova de que é um projeto único e interligado, não um módulo isolado.
"""
from flask import Blueprint, render_template, redirect, url_for, request, flash

from ..db import get_db, new_id
from ..auth import login_obrigatorio, usuario_logado
from ..ai_engine import (
    resumo_desempenho_turma,
    sugestoes_pedagogicas_turma,
    responder_duvida_professor,
    resumo_engajamento_professor,
    NOMES_COMPETENCIA_REDACAO,
)

bp = Blueprint("coordenador_professores", __name__, url_prefix="/professores/coordenador-ia")

PAPEIS_ACESSO = ("professor", "coordenador", "direcao")
PAPEIS_DUVIDAS = ("professor", "coordenador", "direcao", "psicopedagoga")

LIMIAR_MINIMO_EIXO = 2  # só considera um eixo "fraco" se já foram respondidas pelo menos N questões dele
LIMIAR_TAXA_EIXO_FRACO = 0.7  # eixo só entra como "fraco" se a taxa de acerto for menor que isso
LIMIAR_NOTA_COMPETENCIA_FRACA = 160  # competência (0-200) só entra como "fraca" se a média for menor que isso


def _escola_id_atual():
    return usuario_logado()["escola_id"]


def _professor_do_usuario(db, usuario_id):
    return db.execute("select * from professores where usuario_id = ?", (usuario_id,)).fetchone()


def _turmas_do_professor(db, professor_id):
    return db.execute(
        "select t.id, t.nome from turmas t "
        "join professor_turma pt on pt.turma_id = t.id "
        "where pt.professor_id = ? order by t.nome",
        (professor_id,),
    ).fetchall()


def _turmas_da_escola(db, escola_id):
    return db.execute(
        "select t.id, t.nome from turmas t "
        "join series s on s.id = t.serie_id "
        "where s.escola_id = ? order by t.nome",
        (escola_id,),
    ).fetchall()


def _turma_da_escola(db, turma_id, escola_id):
    return db.execute(
        "select t.id, t.nome from turmas t "
        "join series s on s.id = t.serie_id "
        "where t.id = ? and s.escola_id = ?",
        (turma_id, escola_id),
    ).fetchone()


def _professor_pode_ver_turma(db, usuario, turma_id):
    if usuario["papel"] in ("coordenador", "direcao"):
        return _turma_da_escola(db, turma_id, usuario["escola_id"]) is not None
    if usuario["papel"] == "professor":
        professor = _professor_do_usuario(db, usuario["id"])
        if not professor:
            return False
        return db.execute(
            "select 1 from professor_turma where professor_id = ? and turma_id = ?",
            (professor["id"], turma_id),
        ).fetchone() is not None
    return False


def _stats_turma(db, turma_id):
    """Calcula, a partir das tabelas de diagnóstico/redação/radar, tudo que
    resumo_desempenho_turma e sugestoes_pedagogicas_turma precisam."""
    total_alunos = db.execute(
        "select count(*) c from alunos where turma_id = ?", (turma_id,)
    ).fetchone()["c"]

    diag = db.execute(
        "select count(distinct a.id) alunos_com_diag, avg(d.nivel_final) media_nivel "
        "from alunos a join diagnosticos d on d.aluno_id = a.id "
        "where a.turma_id = ? and d.finalizado_em is not null",
        (turma_id,),
    ).fetchone()
    alunos_com_diagnostico = diag["alunos_com_diag"] or 0
    media_nivel_diag = diag["media_nivel"]

    eixos_raw = db.execute(
        "select i.eixo_bncc eixo, "
        "sum(case when dr.correta then 1 else 0 end) acertos, count(*) total "
        "from alunos a "
        "join diagnosticos d on d.aluno_id = a.id "
        "join diagnostico_respostas dr on dr.diagnostico_id = d.id "
        "join itens_banco i on i.id = dr.item_id "
        "where a.turma_id = ? "
        "group by i.eixo_bncc",
        (turma_id,),
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
        "alunos_com_diagnostico": alunos_com_diagnostico,
        "media_nivel_diag": media_nivel_diag,
        "eixos_fracos": eixos_fracos,
        "alunos_com_redacao": alunos_com_redacao,
        "media_nota_redacao": media_nota_redacao,
        "competencias_fracas": competencias_fracas,
        "alertas_pendentes": alertas_pendentes,
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
    turmas = _turmas_da_escola(db, escola_id)
    professores = db.execute(
        "select p.id, us.nome, p.disciplina from professores p "
        "join usuarios us on us.id = p.usuario_id "
        "where us.escola_id = ? order by us.nome",
        (escola_id,),
    ).fetchall()
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
    stats = _stats_turma(db, turma_id)

    resumo = resumo_desempenho_turma(
        turma_row["nome"], stats["total_alunos"], stats["alunos_com_diagnostico"],
        stats["media_nivel_diag"], stats["eixos_fracos"], stats["alunos_com_redacao"],
        stats["media_nota_redacao"], stats["competencias_fracas"], stats["alertas_pendentes"],
    )
    sugestoes = sugestoes_pedagogicas_turma(
        stats["eixos_fracos"], stats["competencias_fracas"], stats["alertas_pendentes"]
    )

    return render_template(
        "coordenador_professores_turma.html", turma=turma_row, stats=stats,
        resumo=resumo, sugestoes=sugestoes,
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
@login_obrigatorio(papeis=["coordenador", "direcao"])
def relatorio_professores():
    db = get_db()
    escola_id = _escola_id_atual()

    professores = db.execute(
        "select p.id, us.nome, p.disciplina from professores p "
        "join usuarios us on us.id = p.usuario_id "
        "where us.escola_id = ? order by us.nome",
        (escola_id,),
    ).fetchall()

    relatorios = []
    for prof in professores:
        turmas_do_prof = _turmas_do_professor(db, prof["id"])
        turmas_info = []
        for t in turmas_do_prof:
            stats = _stats_turma(db, t["id"])
            turmas_info.append({
                "nome": t["nome"],
                "total_alunos": stats["total_alunos"],
                "alunos_com_diagnostico": stats["alunos_com_diagnostico"],
                "alunos_com_redacao": stats["alunos_com_redacao"],
                "alertas_pendentes": stats["alertas_pendentes"],
            })
        resumo = resumo_engajamento_professor(prof["nome"], prof["disciplina"], turmas_info)
        relatorios.append({"professor": prof, "turmas_info": turmas_info, "resumo": resumo})

    return render_template("coordenador_professores_relatorio.html", relatorios=relatorios)
