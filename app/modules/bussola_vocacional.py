"""
Módulo do AIM.Edu: Bússola Vocacional.

O aluno responde um questionário curto de interesses (2 afirmações por área,
escala de 1 a 5) e recebe uma orientação vocacional. O diferencial em relação
a um teste vocacional genérico: quando o aluno já tem um Diagnóstico
Adaptativo de Matemática registrado, a Bússola cruza os dois na hora de
gerar o texto (via app.ai_engine.perfil_vocacional) — de novo, é o mesmo
banco de dados sendo lido por dois módulos diferentes, sem integração
especial entre eles.
"""
import json
from flask import Blueprint, render_template, redirect, url_for, request, flash

from ..db import get_db, new_id
from ..auth import login_obrigatorio, usuario_logado
from ..ai_engine import perfil_vocacional

bp = Blueprint("bussola_vocacional", __name__, url_prefix="/bussola/vocacional")

# Cada área tem 2 afirmações (chaves "0" e "1"); a pontuação da área vai de 2 a 10.
QUESTIONARIO = [
    ("Exatas e Tecnologia", [
        "Gosto de resolver problemas de lógica ou matemática.",
        "Tenho curiosidade sobre como as coisas funcionam (tecnologia, engenharia, programação).",
    ]),
    ("Humanas e Sociais", [
        "Gosto de entender comportamentos, sociedade e cultura.",
        "Tenho interesse em política, história ou direitos humanos.",
    ]),
    ("Biológicas e Saúde", [
        "Tenho interesse em saúde, corpo humano ou natureza.",
        "Gostaria de cuidar de pessoas, animais ou do meio ambiente.",
    ]),
    ("Linguagens e Comunicação", [
        "Gosto de ler, escrever ou aprender idiomas.",
        "Me comunico bem e gosto de explicar ou convencer os outros sobre algo.",
    ]),
    ("Artes e Criatividade", [
        "Gosto de atividades criativas (desenho, música, teatro, design).",
        "Prefiro atividades em que posso me expressar livremente.",
    ]),
    ("Negócios e Gestão", [
        "Tenho interesse em empreender ou administrar algo.",
        "Gosto de organizar, planejar e liderar projetos ou equipes.",
    ]),
]


def _aluno_atual(db):
    u = usuario_logado()
    return db.execute("select * from alunos where usuario_id = ?", (u["id"],)).fetchone()


@bp.route("/")
@login_obrigatorio(papeis=["aluno"])
def index():
    db = get_db()
    aluno = _aluno_atual(db)
    resultados = db.execute(
        "select * from bussola_respostas where aluno_id = ? order by criado_em desc",
        (aluno["id"],),
    ).fetchall()
    return render_template("bussola_index.html", resultados=resultados)


@bp.route("/iniciar")
@login_obrigatorio(papeis=["aluno"])
def iniciar():
    return render_template("bussola_form.html", questionario=QUESTIONARIO)


@bp.route("/responder", methods=["POST"])
@login_obrigatorio(papeis=["aluno"])
def responder():
    db = get_db()
    aluno = _aluno_atual(db)

    pontuacoes = {}
    for area, afirmacoes in QUESTIONARIO:
        total_area = 0
        for indice in range(len(afirmacoes)):
            valor = request.form.get(f"{area}|{indice}")
            total_area += int(valor) if valor else 3  # neutro se faltou responder
        pontuacoes[area] = total_area

    # Cruza com o diagnóstico de Matemática mais recente já finalizado, se existir —
    # é essa consulta que faz a Bússola "conversar" com o outro módulo.
    ultimo_diag = db.execute(
        "select nivel_final from diagnosticos "
        "where aluno_id = ? and disciplina = 'matematica' and finalizado_em is not null "
        "order by finalizado_em desc limit 1",
        (aluno["id"],),
    ).fetchone()
    nivel_matematica = ultimo_diag["nivel_final"] if ultimo_diag else None

    resumo = perfil_vocacional(pontuacoes, nivel_matematica)

    ordenado = sorted(pontuacoes.items(), key=lambda kv: kv[1], reverse=True)
    topo_valor = ordenado[0][1]
    perfil_top = ", ".join(area for area, valor in ordenado if valor >= topo_valor - 1 and valor > 0)

    resposta_id = new_id()
    db.execute(
        "insert into bussola_respostas (id, aluno_id, pontuacoes, perfil_top, resumo_ia) "
        "values (?,?,?,?,?)",
        (resposta_id, aluno["id"], json.dumps(pontuacoes), perfil_top, resumo),
    )
    db.commit()

    return redirect(url_for("bussola_vocacional.resultado", resposta_id=resposta_id))


@bp.route("/resultado/<resposta_id>")
@login_obrigatorio(papeis=["aluno"])
def resultado(resposta_id):
    db = get_db()
    aluno = _aluno_atual(db)
    resposta = db.execute(
        "select * from bussola_respostas where id = ? and aluno_id = ?",
        (resposta_id, aluno["id"]),
    ).fetchone()
    if not resposta:
        flash("Resultado não encontrado.", "erro")
        return redirect(url_for("bussola_vocacional.index"))

    raw_pontuacoes = resposta["pontuacoes"]
    pontuacoes = json.loads(raw_pontuacoes) if isinstance(raw_pontuacoes, str) else raw_pontuacoes

    return render_template("bussola_resultado.html", resposta=resposta, pontuacoes=pontuacoes)
