"""
Módulo do AIM.Edu: Gestão de Usuários — permissões por papel e cadastro em
lote.

Regra de permissão adotada (mais simples do que permissões granulares por
módulo, de propósito): continua tudo baseado no papel do usuário (aluno,
professor, coordenador, direção, família, psicopedagoga) — o que muda aqui
é que agora existe uma tela para coordenação/direção administrar essas
contas, em vez de só o seed_data.py de demonstração. "Admin" não é um papel
novo no banco: é a própria "direção", só chamada assim quando faz sentido
na conversa.

Os níveis de acesso, na prática:
- Direção ("admin"): acesso completo — cria e edita qualquer papel, e é a
  única que pode excluir uma conta definitivamente (ver abaixo).
- Direção Pedagógica: mesmo acesso completo da direção (cria e edita
  qualquer papel, define segmento de coordenador etc. — ver PAPEIS_DIRECAO
  em app/auth.py) — a única coisa que ela NÃO pode fazer é excluir uma conta
  definitivamente. A rota excluir() abaixo continua checando só "direcao",
  de propósito, para essa conta nunca ganhar esse poder.
- Coordenação: pode criar e editar aluno, professor, família e
  psicopedagoga — não pode criar nem editar outro coordenador nem uma conta
  de direção (evita que um coordenador se autopromova ou mexa em contas
  acima da sua própria) — e NÃO tem acesso à exclusão definitiva de conta
  nenhuma, só à ativação e desativação. Isso é decidido em
  _pode_gerenciar_papel() e checado em toda rota que cria ou edita conta; a
  exclusão é checada à parte, só para direção (ver excluir()).
- Psicopedagoga: sem acesso a esta tela de gestão de usuários — o papel
  existe para o módulo de Inclusão (app/modules/inclusao.py), onde ela é
  quem edita o cadastro de inclusão e o PEI de qualquer aluno da escola
  (mesmo nível de edição que coordenação/direção nesse módulo específico).
  Aqui em Gestão de Usuários ela só usa a mesma rota self-service de todo
  mundo, /usuarios/perfil.
- Professor e aluno: não têm acesso a esta tela de gestão — só à rota
  self-service /usuarios/perfil, onde qualquer pessoa logada edita o
  próprio nome e troca a própria senha (informações básicas). Família,
  psicopedagoga e coordenação/direção também usam essa mesma tela para o
  próprio perfil.

Exclusão definitiva x desativação: excluir() apaga a conta e a linha ligada
a ela (alunos/professores) de vez — só a direção pode chamar essa rota, e
mesmo assim só quando a conta não tem histórico vinculado (diagnóstico,
redação, cadastro de inclusão, PEI, etc. — ver _bloqueios_exclusao()).
Havendo qualquer histórico, a exclusão é bloqueada e a recomendação é
desativar a conta em vez de excluir — dado acadêmico não deveria sumir do
sistema por engano. Desativar (o checkbox "ativo" em salvar()) continua
disponível para coordenação e direção, sem essa restrição, já que é
reversível.

O que NÃO dá pra fazer aqui, de propósito: trocar o papel de um usuário já
existente (ex.: transformar um aluno em professor). O papel define quais
outras tabelas têm uma linha ligada a esse usuário (alunos, professores) —
permitir a troca abriria uma porta de inconsistência de dados que não vale
a pena para um caso de uso raro. Pra isso, é mais simples desativar a conta
antiga e criar uma nova com o papel certo.

Cadastro em lote: upload de um arquivo CSV separado para alunos
(nome,email,turma) e para professores (nome,email,disciplina,turmas — com
múltiplas turmas separadas por ";"). Cada linha é processada de forma
independente — uma linha com erro (e-mail duplicado, turma não encontrada)
não derruba as outras, o resultado mostra o status linha a linha. Cada tela
de importação também oferece um modelo .csv em branco pra baixar, preencher
e já subir de volta. Toda conta criada (individual ou em lote) recebe uma
senha temporária aleatória, mostrada uma única vez logo após a criação — o
sistema não guarda senha em texto puro em nenhum momento.
"""
import csv
import io

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, Response

from ..db import get_db, new_id
from ..auth import login_obrigatorio, usuario_logado, hash_senha, escopo_etapa, PAPEIS_DIRECAO

bp = Blueprint("gestao_usuarios", __name__, url_prefix="/usuarios")

PAPEIS_LABEL = {
    "aluno": "Aluno",
    "professor": "Professor",
    "coordenador": "Coordenador",
    "direcao": "Direção (admin)",
    "direcao_pedagogica": "Direção Pedagógica",
    "familia": "Família",
    "psicopedagoga": "Psicopedagoga",
}

# Lista fixa de disciplinas para o campo "Disciplina" do professor — antes era
# texto livre (a coordenação digitava "Matemática", "matemática", "MATEMATICA"...
# cada um do seu jeito), o que exigia normalizar acentos/caixa toda vez que o
# valor precisava ser comparado com o slug do banco de itens (ver
# app.modules.coordenador_professores._normalizar_disciplina, que continua
# existindo e é usada do mesmo jeito — só que agora recebendo sempre um valor
# desta lista, nunca mais um texto digitado à mão). Matemática e Português já
# têm banco de itens no Diagnóstico Adaptativo (ver seed_data.py); as demais
# disciplinas ficam prontas para quando um banco de itens for cadastrado para
# elas — até lá, o professor aparece normalmente no sistema, só sem o bloco de
# Diagnóstico Adaptativo no Coordenador de Professores.
DISCIPLINAS_DISPONIVEIS = [
    "Artes",
    "Biologia",
    "Educação Física",
    "Filosofia",
    "Física",
    "Geografia",
    "História",
    "Inglês",
    "Matemática",
    "Português",
    "Química",
    "Sociologia",
]

# Segmentos que um coordenador pode ter (campo usuarios.segmento) — reaproveita
# os mesmos slugs de series.etapa, na mesma ordem pedagógica, em vez de criar
# uma lista paralela. Só a direção pode definir/trocar o segmento de um
# coordenador (ver _pode_gerenciar_papel: coordenador não gerencia coordenador).
# Um coordenador sem segmento definido continua vendo a escola inteira —
# é o que preserva o comportamento de contas já existentes antes deste campo.
SEGMENTOS_DISPONIVEIS = [
    ("infantil", "Educação Infantil"),
    ("fund1", "Fundamental I (Anos Iniciais)"),
    ("fund2", "Fundamental II (Anos Finais)"),
    ("medio", "Ensino Médio"),
]
SEGMENTOS_LABEL = dict(SEGMENTOS_DISPONIVEIS)


def _escola_id_atual():
    return usuario_logado()["escola_id"]


def _pode_gerenciar_papel(papel_ator: str, papel_alvo: str) -> bool:
    if papel_ator in PAPEIS_DIRECAO:
        return True
    return papel_alvo in ("aluno", "professor", "familia", "psicopedagoga")


def _turma_no_segmento(db, turma_id, segmento):
    if not segmento or not turma_id:
        return not segmento
    return db.execute(
        "select 1 from turmas t join series s on s.id = t.serie_id where t.id = ? and s.etapa = ?",
        (turma_id, segmento),
    ).fetchone() is not None


def _professor_tem_turma_no_segmento(db, professor_id, segmento):
    return db.execute(
        "select 1 from professor_turma pt join turmas t on t.id = pt.turma_id "
        "join series s on s.id = t.serie_id where pt.professor_id = ? and s.etapa = ?",
        (professor_id, segmento),
    ).fetchone() is not None


def _familia_tem_aluno_no_segmento(db, familia_usuario_id, segmento):
    return db.execute(
        "select 1 from alunos al join turmas t on t.id = al.turma_id "
        "join series s on s.id = t.serie_id where al.responsavel_usuario_id = ? and s.etapa = ?",
        (familia_usuario_id, segmento),
    ).fetchone() is not None


def _usuario_no_escopo(db, ator: dict, alvo) -> bool:
    """Um coordenador com segmento definido só enxerga/gerencia aluno,
    professor e família ligados ao próprio segmento (etapa) — direção e
    coordenador sem segmento não são restringidos por esta função. Um aluno
    ou professor sem vínculo de turma ainda visível (caso raro) fica de fora
    do escopo, por segurança (nega por padrão)."""
    segmento = escopo_etapa(ator)
    if not segmento or not alvo:
        return True
    if alvo["papel"] == "aluno":
        aluno = db.execute("select turma_id from alunos where usuario_id = ?", (alvo["id"],)).fetchone()
        return bool(aluno) and _turma_no_segmento(db, aluno["turma_id"], segmento)
    if alvo["papel"] == "professor":
        professor = db.execute("select id from professores where usuario_id = ?", (alvo["id"],)).fetchone()
        return bool(professor) and _professor_tem_turma_no_segmento(db, professor["id"], segmento)
    if alvo["papel"] == "familia":
        return _familia_tem_aluno_no_segmento(db, alvo["id"], segmento)
    return True


def _pode_gerenciar_usuario(ator: dict, alvo, db=None) -> bool:
    """Além da regra por papel, todo usuário pode sempre gerenciar a própria
    conta (ex.: redefinir a própria senha) — sem isso, um coordenador
    ficaria travado para mexer no próprio cadastro, já que coordenador não
    pode gerenciar papel 'coordenador' de terceiros. Quando db é informado,
    também aplica o escopo por segmento (_usuario_no_escopo) — passar db
    sempre que possível; sem ele, a checagem de segmento é pulada (usado só
    onde o escopo já foi resolvido de outra forma)."""
    if not alvo:
        return False
    if alvo["id"] == ator["id"]:
        return True
    if not _pode_gerenciar_papel(ator["papel"], alvo["papel"]):
        return False
    if db is not None and not _usuario_no_escopo(db, ator, alvo):
        return False
    return True


def _gerar_senha_temporaria(tamanho: int = 8) -> str:
    import secrets
    import string

    alfabeto = "".join(c for c in string.ascii_letters + string.digits if c not in "0O1lI")
    return "".join(secrets.choice(alfabeto) for _ in range(tamanho))


def _bloqueios_exclusao(db, alvo):
    """Verifica se a conta tem qualquer histórico vinculado a ela. Se tiver,
    a exclusão definitiva é bloqueada — dado acadêmico não deveria sumir do
    sistema por engano — e a recomendação é desativar a conta em vez de
    excluir. Retorna a lista de motivos do bloqueio; lista vazia = pode
    excluir."""
    motivos = []
    uid = alvo["id"]

    if alvo["papel"] == "aluno":
        aluno = db.execute("select id from alunos where usuario_id = ?", (uid,)).fetchone()
        if aluno:
            aluno_id = aluno["id"]
            tabelas_aluno = [
                ("diagnosticos", "diagnósticos"),
                ("redacoes", "redações"),
                ("alertas_radar", "alertas do radar"),
                ("relatorios_familia", "relatórios para a família"),
                ("bussola_respostas", "respostas da bússola vocacional"),
                ("inclusao_cadastro", "cadastro de inclusão"),
                ("pei_metas", "metas de PEI"),
                ("pei_revisoes", "revisões de PEI"),
            ]
            for tabela, rotulo in tabelas_aluno:
                if db.execute(f"select 1 from {tabela} where aluno_id = ?", (aluno_id,)).fetchone():
                    motivos.append(rotulo)

    if alvo["papel"] == "familia":
        if db.execute("select 1 from alunos where responsavel_usuario_id = ?", (uid,)).fetchone():
            motivos.append("vínculo como responsável de aluno(s) — desvincule antes de excluir")

    tabelas_autoria = [
        ("inclusao_cadastro", "cadastro(s) de inclusão criado(s) por essa conta"),
        ("pei_metas", "meta(s) de PEI criada(s) por essa conta"),
        ("pei_revisoes", "revisão/revisões de PEI criada(s) por essa conta"),
    ]
    for tabela, rotulo in tabelas_autoria:
        if db.execute(f"select 1 from {tabela} where criado_por_usuario_id = ?", (uid,)).fetchone():
            motivos.append(rotulo)

    return motivos


def _turmas_da_escola(db, segmento=None):
    """Turmas da escola — quando 'segmento' é informado (coordenador
    escopado), só as turmas da etapa correspondente, para que ela nem veja a
    opção de matricular um aluno ou vincular um professor fora do seu
    segmento."""
    if segmento:
        return db.execute(
            "select t.id, t.nome from turmas t join series s on s.id = t.serie_id "
            "where s.escola_id = ? and s.etapa = ? order by t.nome",
            (_escola_id_atual(), segmento),
        ).fetchall()
    return db.execute(
        "select t.id, t.nome from turmas t join series s on s.id = t.serie_id "
        "where s.escola_id = ? order by t.nome",
        (_escola_id_atual(),),
    ).fetchall()


def _usuarios_visiveis(db):
    """Lista de usuários da escola pra tela de Gestão de Usuários — direção,
    e coordenador sem segmento definido, veem todo mundo. Um coordenador COM
    segmento só vê aluno/professor/família ligados ao próprio segmento
    (etapa) — outras contas de coordenador/direção/psicopedagoga ficam fora
    da lista dela, já que ela nunca poderia gerenciá-las mesmo (ver
    _pode_gerenciar_papel)."""
    escola_id = _escola_id_atual()
    segmento = escopo_etapa(usuario_logado())
    if not segmento:
        return db.execute(
            "select * from usuarios where escola_id = ? order by papel, nome", (escola_id,)
        ).fetchall()
    return db.execute(
        "select distinct us.* from usuarios us "
        "left join alunos al on al.usuario_id = us.id "
        "left join turmas t_al on t_al.id = al.turma_id "
        "left join series s_al on s_al.id = t_al.serie_id "
        "left join professores p on p.usuario_id = us.id "
        "left join professor_turma pt on pt.professor_id = p.id "
        "left join turmas t_pt on t_pt.id = pt.turma_id "
        "left join series s_pt on s_pt.id = t_pt.serie_id "
        "left join alunos al_resp on al_resp.responsavel_usuario_id = us.id "
        "left join turmas t_resp on t_resp.id = al_resp.turma_id "
        "left join series s_resp on s_resp.id = t_resp.serie_id "
        "where us.escola_id = ? and ("
        "(us.papel = 'aluno' and s_al.etapa = ?) or "
        "(us.papel = 'professor' and s_pt.etapa = ?) or "
        "(us.papel = 'familia' and s_resp.etapa = ?)"
        ") order by us.papel, us.nome",
        (escola_id, segmento, segmento, segmento),
    ).fetchall()


@bp.route("/")
@login_obrigatorio(papeis=["coordenador", "direcao", "direcao_pedagogica"])
def index():
    db = get_db()
    usuarios = _usuarios_visiveis(db)
    return render_template(
        "gestao_usuarios_index.html", usuarios=usuarios, papeis_label=PAPEIS_LABEL, segmentos_label=SEGMENTOS_LABEL
    )


@bp.route("/novo", methods=["GET", "POST"])
@login_obrigatorio(papeis=["coordenador", "direcao", "direcao_pedagogica"])
def novo():
    db = get_db()
    escola_id = _escola_id_atual()
    ator = usuario_logado()
    papel_ator = ator["papel"]
    segmento_ator = escopo_etapa(ator)
    pode_definir_segmento = papel_ator in PAPEIS_DIRECAO
    papeis_disponiveis = {p: rotulo for p, rotulo in PAPEIS_LABEL.items() if _pode_gerenciar_papel(papel_ator, p)}
    turmas = _turmas_da_escola(db, segmento_ator)
    turma_ids_permitidos = {t["id"] for t in turmas}
    alunos_sem_familia_query = (
        "select al.id, us.nome as nome from alunos al "
        "join usuarios us on us.id = al.usuario_id "
        "join turmas t on t.id = al.turma_id join series s on s.id = t.serie_id "
        "where s.escola_id = ? and al.responsavel_usuario_id is null "
    )
    params_af = [escola_id]
    if segmento_ator:
        alunos_sem_familia_query += "and s.etapa = ? "
        params_af.append(segmento_ator)
    alunos_sem_familia = db.execute(
        alunos_sem_familia_query + "order by us.nome", tuple(params_af)
    ).fetchall()

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        email = request.form.get("email", "").strip().lower()
        papel = request.form.get("papel", "")
        turma_id = request.form.get("turma_id") or None
        disciplina = request.form.get("disciplina", "").strip()
        turmas_professor = [t for t in request.form.getlist("turmas_professor") if t in turma_ids_permitidos]
        aluno_vinculado_id = request.form.get("aluno_vinculado_id") or None
        segmento_novo = request.form.get("segmento") or None

        erro = None
        if not nome or not email or papel not in PAPEIS_LABEL:
            erro = "Preencha nome, e-mail e papel corretamente."
        elif not _pode_gerenciar_papel(papel_ator, papel):
            erro = "Você não tem permissão para criar um usuário com esse papel."
        elif db.execute("select id from usuarios where email = ?", (email,)).fetchone():
            erro = "Já existe um usuário com esse e-mail."
        elif papel == "aluno" and not turma_id:
            erro = "Selecione a turma do aluno."
        elif papel == "aluno" and turma_id not in turma_ids_permitidos:
            erro = "Turma inválida ou fora do seu segmento."
        elif papel == "professor" and disciplina and disciplina not in DISCIPLINAS_DISPONIVEIS:
            erro = "Selecione a disciplina na lista."
        elif papel == "coordenador" and segmento_novo and segmento_novo not in SEGMENTOS_LABEL:
            erro = "Segmento inválido — selecione uma opção da lista."

        if erro:
            flash(erro, "erro")
            return render_template(
                "gestao_usuarios_form.html", turmas=turmas, alunos_sem_familia=alunos_sem_familia,
                papeis_disponiveis=papeis_disponiveis, disciplinas=DISCIPLINAS_DISPONIVEIS,
                segmentos=SEGMENTOS_DISPONIVEIS, pode_definir_segmento=pode_definir_segmento, form=request.form,
            )

        senha_temp = _gerar_senha_temporaria()
        uid = new_id()
        segmento_salvo = segmento_novo if (papel == "coordenador" and pode_definir_segmento) else None
        db.execute(
            "insert into usuarios (id, escola_id, nome, email, senha_hash, papel, ativo, segmento) "
            "values (?,?,?,?,?,?,?,?)",
            (uid, escola_id, nome, email, hash_senha(senha_temp), papel, True, segmento_salvo),
        )
        if papel == "aluno":
            db.execute("insert into alunos (id, usuario_id, turma_id) values (?,?,?)", (new_id(), uid, turma_id))
        elif papel == "professor":
            professor_id = new_id()
            db.execute(
                "insert into professores (id, usuario_id, disciplina) values (?,?,?)",
                (professor_id, uid, disciplina or None),
            )
            for turma_id_prof in turmas_professor:
                db.execute(
                    "insert into professor_turma (professor_id, turma_id) values (?,?)", (professor_id, turma_id_prof)
                )
        elif papel == "familia" and aluno_vinculado_id:
            db.execute("update alunos set responsavel_usuario_id = ? where id = ?", (uid, aluno_vinculado_id))

        db.commit()
        flash(
            f"Usuário {nome} criado. E-mail: {email} — senha temporária: {senha_temp} "
            "(anote agora, ela não será mostrada de novo).",
            "credenciais",
        )
        return redirect(url_for("gestao_usuarios.index"))

    return render_template(
        "gestao_usuarios_form.html", turmas=turmas, alunos_sem_familia=alunos_sem_familia,
        papeis_disponiveis=papeis_disponiveis, disciplinas=DISCIPLINAS_DISPONIVEIS,
        segmentos=SEGMENTOS_DISPONIVEIS, pode_definir_segmento=pode_definir_segmento, form={},
    )


@bp.route("/<usuario_id>")
@login_obrigatorio(papeis=["coordenador", "direcao", "direcao_pedagogica"])
def editar(usuario_id):
    db = get_db()
    ator = usuario_logado()
    alvo = db.execute(
        "select * from usuarios where id = ? and escola_id = ?", (usuario_id, _escola_id_atual())
    ).fetchone()
    if not _pode_gerenciar_usuario(ator, alvo, db):
        flash("Usuário não encontrado ou fora do seu acesso.", "erro")
        return redirect(url_for("gestao_usuarios.index"))

    segmento_ator = escopo_etapa(ator)
    turmas = _turmas_da_escola(db, segmento_ator)
    turma_atual_id = None
    professor_row = None
    turmas_vinculadas = []

    if alvo["papel"] == "aluno":
        aluno_row = db.execute("select * from alunos where usuario_id = ?", (usuario_id,)).fetchone()
        turma_atual_id = aluno_row["turma_id"] if aluno_row else None

    if alvo["papel"] == "professor":
        professor_row = db.execute("select * from professores where usuario_id = ?", (usuario_id,)).fetchone()
        if professor_row:
            turmas_vinculadas = [
                r["turma_id"]
                for r in db.execute(
                    "select turma_id from professor_turma where professor_id = ?", (professor_row["id"],)
                ).fetchall()
            ]

    # Exclusão continua checando só "direcao" (nunca PAPEIS_DIRECAO) — é a
    # única ação que a direção pedagógica não tem, de propósito.
    pode_excluir = ator["papel"] == "direcao" and alvo["id"] != ator["id"]
    pode_definir_segmento = ator["papel"] in PAPEIS_DIRECAO and alvo["papel"] == "coordenador"

    return render_template(
        "gestao_usuarios_editar.html", alvo=alvo, turmas=turmas, turma_atual_id=turma_atual_id,
        professor_row=professor_row, turmas_vinculadas=turmas_vinculadas, papeis_label=PAPEIS_LABEL,
        disciplinas=DISCIPLINAS_DISPONIVEIS, pode_excluir=pode_excluir,
        segmentos=SEGMENTOS_DISPONIVEIS, pode_definir_segmento=pode_definir_segmento,
    )


@bp.route("/<usuario_id>/salvar", methods=["POST"])
@login_obrigatorio(papeis=["coordenador", "direcao", "direcao_pedagogica"])
def salvar(usuario_id):
    db = get_db()
    ator = usuario_logado()
    alvo = db.execute(
        "select * from usuarios where id = ? and escola_id = ?", (usuario_id, _escola_id_atual())
    ).fetchone()
    if not _pode_gerenciar_usuario(ator, alvo, db):
        flash("Usuário não encontrado ou fora do seu acesso.", "erro")
        return redirect(url_for("gestao_usuarios.index"))

    segmento_ator = escopo_etapa(ator)
    turma_ids_permitidos = {t["id"] for t in _turmas_da_escola(db, segmento_ator)}

    ativo = True if request.form.get("ativo") == "on" else False
    if alvo["id"] == ator["id"] and not ativo:
        flash("Você não pode desativar sua própria conta.", "erro")
        return redirect(url_for("gestao_usuarios.editar", usuario_id=usuario_id))

    db.execute("update usuarios set ativo = ? where id = ?", (ativo, usuario_id))

    if alvo["papel"] == "coordenador" and ator["papel"] in PAPEIS_DIRECAO:
        segmento_novo = request.form.get("segmento") or None
        if segmento_novo and segmento_novo not in SEGMENTOS_LABEL:
            flash("Segmento inválido — selecione uma opção da lista.", "erro")
            return redirect(url_for("gestao_usuarios.editar", usuario_id=usuario_id))
        db.execute("update usuarios set segmento = ? where id = ?", (segmento_novo, usuario_id))

    if alvo["papel"] == "aluno":
        turma_id = request.form.get("turma_id")
        if turma_id and turma_id in turma_ids_permitidos:
            db.execute("update alunos set turma_id = ? where usuario_id = ?", (turma_id, usuario_id))

    if alvo["papel"] == "professor":
        disciplina = request.form.get("disciplina", "").strip()
        if disciplina and disciplina not in DISCIPLINAS_DISPONIVEIS:
            flash("Disciplina inválida — selecione uma opção da lista.", "erro")
            return redirect(url_for("gestao_usuarios.editar", usuario_id=usuario_id))
        professor_row = db.execute("select id from professores where usuario_id = ?", (usuario_id,)).fetchone()
        if professor_row:
            db.execute("update professores set disciplina = ? where id = ?", (disciplina or None, professor_row["id"]))
            # Quando quem salva é um coordenador escopado, só mexe nos vínculos
            # do próprio segmento — as turmas de outros segmentos que esse
            # professor já lecionava (cuidadas por outra coordenação) ficam
            # intactas, em vez de apagar tudo e recriar só com o que veio no form.
            turmas_form = [t for t in request.form.getlist("turmas_professor") if t in turma_ids_permitidos]
            if segmento_ator:
                db.execute(
                    "delete from professor_turma where professor_id = ? and turma_id in ("
                    "select t.id from turmas t join series s on s.id = t.serie_id where s.etapa = ?)",
                    (professor_row["id"], segmento_ator),
                )
            else:
                db.execute("delete from professor_turma where professor_id = ?", (professor_row["id"],))
            for turma_id_prof in turmas_form:
                db.execute(
                    "insert into professor_turma (professor_id, turma_id) values (?,?)",
                    (professor_row["id"], turma_id_prof),
                )

    db.commit()
    flash("Usuário atualizado.", "ok")
    return redirect(url_for("gestao_usuarios.editar", usuario_id=usuario_id))


@bp.route("/<usuario_id>/redefinir-senha", methods=["POST"])
@login_obrigatorio(papeis=["coordenador", "direcao", "direcao_pedagogica"])
def redefinir_senha(usuario_id):
    db = get_db()
    alvo = db.execute(
        "select * from usuarios where id = ? and escola_id = ?", (usuario_id, _escola_id_atual())
    ).fetchone()
    if not _pode_gerenciar_usuario(usuario_logado(), alvo, db):
        flash("Usuário não encontrado ou fora do seu acesso.", "erro")
        return redirect(url_for("gestao_usuarios.index"))

    nova_senha = _gerar_senha_temporaria()
    db.execute("update usuarios set senha_hash = ? where id = ?", (hash_senha(nova_senha), usuario_id))
    db.commit()
    flash(
        f"Nova senha temporária de {alvo['nome']}: {nova_senha} (anote agora, ela não será mostrada de novo).",
        "credenciais",
    )
    return redirect(url_for("gestao_usuarios.editar", usuario_id=usuario_id))


@bp.route("/<usuario_id>/excluir", methods=["POST"])
@login_obrigatorio(papeis=["direcao"])
def excluir(usuario_id):
    db = get_db()
    alvo = db.execute(
        "select * from usuarios where id = ? and escola_id = ?", (usuario_id, _escola_id_atual())
    ).fetchone()
    if not alvo:
        flash("Usuário não encontrado ou fora do seu acesso.", "erro")
        return redirect(url_for("gestao_usuarios.index"))
    if alvo["id"] == usuario_logado()["id"]:
        flash("Você não pode excluir a própria conta.", "erro")
        return redirect(url_for("gestao_usuarios.editar", usuario_id=usuario_id))

    motivos = _bloqueios_exclusao(db, alvo)
    if motivos:
        flash(
            f"Não é possível excluir {alvo['nome']} definitivamente — a conta tem histórico vinculado "
            f"({', '.join(motivos)}). Desative a conta em vez de excluir.",
            "erro",
        )
        return redirect(url_for("gestao_usuarios.editar", usuario_id=usuario_id))

    if alvo["papel"] == "aluno":
        db.execute("delete from alunos where usuario_id = ?", (usuario_id,))
    elif alvo["papel"] == "professor":
        professor = db.execute("select id from professores where usuario_id = ?", (usuario_id,)).fetchone()
        if professor:
            db.execute("delete from professor_turma where professor_id = ?", (professor["id"],))
            db.execute("delete from professores where id = ?", (professor["id"],))

    nome_excluido = alvo["nome"]
    db.execute("delete from usuarios where id = ?", (usuario_id,))
    db.commit()
    flash(f"Usuário {nome_excluido} excluído definitivamente.", "ok")
    return redirect(url_for("gestao_usuarios.index"))


@bp.route("/perfil", methods=["GET", "POST"])
@login_obrigatorio()
def perfil():
    """Autoatendimento: qualquer pessoa logada (aluno, professor,
    coordenador, direção ou família) edita o próprio nome e troca a própria
    senha aqui — sem precisar de acesso à tela de Gestão de Usuários."""
    db = get_db()
    uid = usuario_logado()["id"]
    usuario = db.execute("select * from usuarios where id = ?", (uid,)).fetchone()

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        senha_atual = request.form.get("senha_atual", "")
        nova_senha = request.form.get("nova_senha", "")
        confirmar_senha = request.form.get("confirmar_senha", "")

        if not nome:
            flash("Informe seu nome.", "erro")
            return redirect(url_for("gestao_usuarios.perfil"))

        db.execute("update usuarios set nome = ? where id = ?", (nome, uid))

        if senha_atual or nova_senha or confirmar_senha:
            if usuario["senha_hash"] != hash_senha(senha_atual):
                db.commit()
                flash("Nome atualizado. A senha não foi alterada: a senha atual informada está incorreta.", "erro")
                return redirect(url_for("gestao_usuarios.perfil"))
            if len(nova_senha) < 4:
                db.commit()
                flash("Nome atualizado. A senha não foi alterada: a nova senha precisa ter pelo menos 4 caracteres.", "erro")
                return redirect(url_for("gestao_usuarios.perfil"))
            if nova_senha != confirmar_senha:
                db.commit()
                flash("Nome atualizado. A senha não foi alterada: a confirmação não bateu com a nova senha.", "erro")
                return redirect(url_for("gestao_usuarios.perfil"))
            db.execute("update usuarios set senha_hash = ? where id = ?", (hash_senha(nova_senha), uid))

        db.commit()

        sessao = session.get("usuario")
        if sessao:
            sessao["nome"] = nome
            session["usuario"] = sessao

        flash("Perfil atualizado.", "ok")
        return redirect(url_for("gestao_usuarios.perfil"))

    return render_template("gestao_usuarios_perfil.html", usuario=usuario)


@bp.route("/importar/alunos/modelo.csv")
@login_obrigatorio(papeis=["coordenador", "direcao", "direcao_pedagogica"])
def modelo_csv_alunos():
    conteudo = "﻿nome,email,turma\n"
    return Response(
        conteudo, mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=modelo_importar_alunos.csv"},
    )


@bp.route("/importar/professores/modelo.csv")
@login_obrigatorio(papeis=["coordenador", "direcao", "direcao_pedagogica"])
def modelo_csv_professores():
    conteudo = "﻿nome,email,disciplina,turmas\n"
    return Response(
        conteudo, mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=modelo_importar_professores.csv"},
    )


@bp.route("/importar/alunos", methods=["GET", "POST"])
@login_obrigatorio(papeis=["coordenador", "direcao", "direcao_pedagogica"])
def importar_alunos():
    db = get_db()
    escola_id = _escola_id_atual()
    segmento_ator = escopo_etapa(usuario_logado())
    resultados = None

    if request.method == "POST":
        arquivo = request.files.get("arquivo")
        if not arquivo or not arquivo.filename:
            flash("Selecione um arquivo CSV.", "erro")
            return redirect(url_for("gestao_usuarios.importar_alunos"))

        try:
            texto = arquivo.stream.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            flash("Não consegui ler o arquivo — salve-o como CSV UTF-8 e tente de novo.", "erro")
            return redirect(url_for("gestao_usuarios.importar_alunos"))

        linhas = [linha for linha in csv.reader(io.StringIO(texto)) if any(c.strip() for c in linha)]
        if linhas and [c.strip().lower() for c in linhas[0][:3]] == ["nome", "email", "turma"]:
            linhas = linhas[1:]

        resultados = []
        for i, linha in enumerate(linhas, start=1):
            if len(linha) < 3:
                resultados.append({
                    "linha": i, "nome": linha[0].strip() if linha else "-", "status": "erro",
                    "motivo": "linha com menos de 3 colunas (esperado: nome,email,turma)",
                })
                continue

            nome, email, turma_nome = (c.strip() for c in linha[:3])
            email = email.lower()
            if not nome or not email or not turma_nome:
                resultados.append({"linha": i, "nome": nome or "-", "status": "erro", "motivo": "nome, e-mail ou turma em branco"})
                continue
            if db.execute("select id from usuarios where email = ?", (email,)).fetchone():
                resultados.append({"linha": i, "nome": nome, "status": "erro", "motivo": f"e-mail {email} já cadastrado"})
                continue
            if segmento_ator:
                turma = db.execute(
                    "select t.id from turmas t join series s on s.id = t.serie_id "
                    "where s.escola_id = ? and s.etapa = ? and lower(t.nome) = lower(?)",
                    (escola_id, segmento_ator, turma_nome),
                ).fetchone()
            else:
                turma = db.execute(
                    "select t.id from turmas t join series s on s.id = t.serie_id "
                    "where s.escola_id = ? and lower(t.nome) = lower(?)",
                    (escola_id, turma_nome),
                ).fetchone()
            if not turma:
                resultados.append({"linha": i, "nome": nome, "status": "erro", "motivo": f"turma '{turma_nome}' não encontrada ou fora do seu segmento"})
                continue

            senha_temp = _gerar_senha_temporaria()
            uid = new_id()
            db.execute(
                "insert into usuarios (id, escola_id, nome, email, senha_hash, papel, ativo) values (?,?,?,?,?,?,?)",
                (uid, escola_id, nome, email, hash_senha(senha_temp), "aluno", True),
            )
            db.execute("insert into alunos (id, usuario_id, turma_id) values (?,?,?)", (new_id(), uid, turma["id"]))
            resultados.append({"linha": i, "nome": nome, "email": email, "senha": senha_temp, "status": "criado"})

        db.commit()

    return render_template("gestao_usuarios_importar_alunos.html", resultados=resultados)


@bp.route("/importar/professores", methods=["GET", "POST"])
@login_obrigatorio(papeis=["coordenador", "direcao", "direcao_pedagogica"])
def importar_professores():
    db = get_db()
    escola_id = _escola_id_atual()
    segmento_ator = escopo_etapa(usuario_logado())
    resultados = None

    if request.method == "POST":
        arquivo = request.files.get("arquivo")
        if not arquivo or not arquivo.filename:
            flash("Selecione um arquivo CSV.", "erro")
            return redirect(url_for("gestao_usuarios.importar_professores"))

        try:
            texto = arquivo.stream.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            flash("Não consegui ler o arquivo — salve-o como CSV UTF-8 e tente de novo.", "erro")
            return redirect(url_for("gestao_usuarios.importar_professores"))

        linhas = [linha for linha in csv.reader(io.StringIO(texto)) if any(c.strip() for c in linha)]
        if linhas and [c.strip().lower() for c in linhas[0][:4]] == ["nome", "email", "disciplina", "turmas"]:
            linhas = linhas[1:]

        resultados = []
        for i, linha in enumerate(linhas, start=1):
            if len(linha) < 2:
                resultados.append({
                    "linha": i, "nome": linha[0].strip() if linha else "-", "status": "erro",
                    "motivo": "linha com menos de 2 colunas (esperado: nome,email,disciplina,turmas)",
                })
                continue

            nome = linha[0].strip()
            email = linha[1].strip().lower()
            disciplina = linha[2].strip() if len(linha) > 2 else ""
            turmas_texto = linha[3].strip() if len(linha) > 3 else ""

            if not nome or not email:
                resultados.append({"linha": i, "nome": nome or "-", "status": "erro", "motivo": "nome ou e-mail em branco"})
                continue
            if db.execute("select id from usuarios where email = ?", (email,)).fetchone():
                resultados.append({"linha": i, "nome": nome, "status": "erro", "motivo": f"e-mail {email} já cadastrado"})
                continue

            nomes_turma = [t.strip() for t in turmas_texto.split(";") if t.strip()]
            turma_ids = []
            turmas_nao_encontradas = []
            for nome_turma in nomes_turma:
                if segmento_ator:
                    turma = db.execute(
                        "select t.id from turmas t join series s on s.id = t.serie_id "
                        "where s.escola_id = ? and s.etapa = ? and lower(t.nome) = lower(?)",
                        (escola_id, segmento_ator, nome_turma),
                    ).fetchone()
                else:
                    turma = db.execute(
                        "select t.id from turmas t join series s on s.id = t.serie_id "
                        "where s.escola_id = ? and lower(t.nome) = lower(?)",
                        (escola_id, nome_turma),
                    ).fetchone()
                if turma:
                    turma_ids.append(turma["id"])
                else:
                    turmas_nao_encontradas.append(nome_turma)

            senha_temp = _gerar_senha_temporaria()
            uid = new_id()
            db.execute(
                "insert into usuarios (id, escola_id, nome, email, senha_hash, papel, ativo) values (?,?,?,?,?,?,?)",
                (uid, escola_id, nome, email, hash_senha(senha_temp), "professor", True),
            )
            professor_id = new_id()
            db.execute(
                "insert into professores (id, usuario_id, disciplina) values (?,?,?)",
                (professor_id, uid, disciplina or None),
            )
            for turma_id in turma_ids:
                db.execute("insert into professor_turma (professor_id, turma_id) values (?,?)", (professor_id, turma_id))

            motivo = None
            if turmas_nao_encontradas:
                motivo = "turma(s) não encontrada(s), ignoradas: " + ", ".join(turmas_nao_encontradas)
            resultados.append({"linha": i, "nome": nome, "email": email, "senha": senha_temp, "status": "criado", "motivo": motivo})

        db.commit()

    return render_template("gestao_usuarios_importar_professores.html", resultados=resultados)
