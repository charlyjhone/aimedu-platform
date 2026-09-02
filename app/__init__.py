import os
from flask import Flask, session

from .db import init_db, get_db
from . import auth
from .auth import escopo_etapa, PAPEIS_DIRECAO
from .modules import diagnostico, radar_coordenacao, bussola_vocacional, redacao, relatorios_familia, inclusao, gestao_usuarios, coordenador_professores, turmas
from .modules.gestao_usuarios import PAPEIS_LABEL, SEGMENTOS_LABEL
from .ai_engine import NOMES_DISCIPLINA


def _fmt_data(valor):
    """Formata datas iguais para SQLite (texto) e Postgres (datetime já
    decodificado pelo psycopg2) — usado nos templates como filtro |data."""
    if not valor:
        return "—"
    return str(valor)[:16].replace("T", " ")


def _fmt_disciplina(slug):
    """Rótulo de exibição de uma disciplina (slug salvo no banco -> nome
    acentuado) — usado nos templates como filtro |disciplina, para não
    espalhar NOMES_DISCIPLINA em cada template."""
    if not slug:
        return "—"
    return NOMES_DISCIPLINA.get(slug, slug.capitalize())


def _fmt_iniciais(nome):
    """Iniciais pro avatar do menu lateral (ex: 'Shirley Dayanna' -> 'SD')."""
    partes = (nome or "").split()
    if not partes:
        return "?"
    if len(partes) == 1:
        return partes[0][0].upper()
    return (partes[0][0] + partes[-1][0]).upper()


# ---------------------------------------------------------------------------
# Menu lateral (Opção A do redesign visual, aprovada em set/2026): a navegação
# por papel mora aqui, num único lugar, em vez de espalhada pelos templates —
# mesma filosofia de "fonte única" já usada em NOMES_DISCIPLINA/PAPEIS_LABEL.
# Cada item aponta pro endpoint real do Flask; se um endpoint mudar de nome,
# só precisa atualizar aqui.
# ---------------------------------------------------------------------------
ICONES_SVG = {
    "home": "<path d='M3 12l9-9 9 9M5 10v10h14V10'/>",
    "grid": "<rect x='3' y='4' width='18' height='16' rx='2'/><path d='M3 9h18M8 4v5'/>",
    "activity": "<path d='M13 2L3 14h8l-1 8 10-12h-8l1-8z'/>",
    "users": "<circle cx='9' cy='8' r='3'/><path d='M2 20c0-3.5 3-6 7-6s7 2.5 7 6M16 10.5c1.9.3 3.3 1.6 3.3 3'/>",
    "layers": "<path d='M12 3l8 4-8 4-8-4 8-4zM4 11l8 4 8-4M4 15l8 4 8-4'/>",
    "shield": "<path d='M9 12l2 2 4-4M12 22c5-2 8-6 8-11V5l-8-3-8 3v6c0 5 3 9 8 11z'/>",
    "help": "<circle cx='12' cy='12' r='9'/><path d='M9.5 9a2.5 2.5 0 015 0c0 2-2.5 2-2.5 4M12 17h.01'/>",
    "bar-chart": "<path d='M3 3v18h18M8 17V10M13 17V6M18 17v-4'/>",
    "target": "<circle cx='12' cy='12' r='9'/><circle cx='12' cy='12' r='5'/><circle cx='12' cy='12' r='1'/>",
    "file-text": "<path d='M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z'/><path d='M14 2v6h6'/><path d='M8 13h8M8 17h8M8 9h2'/>",
    "compass": "<circle cx='12' cy='12' r='9'/><path d='M16 8l-3 6-6 3 3-6z'/>",
}

_MENU_COORDENACAO = [
    {"nome": "Pedagógico", "itens": [
        {"label": "Turmas", "endpoint": "turmas.index", "icone": "grid"},
        {"label": "Radar da Coordenação", "endpoint": "radar_coordenacao.index", "icone": "activity"},
        {"label": "Coordenador de Professores", "endpoint": "coordenador_professores.index", "icone": "layers"},
        {"label": "Relatório de Professores", "endpoint": "coordenador_professores.relatorio_professores", "icone": "bar-chart"},
    ]},
    {"nome": "Pessoas", "itens": [
        {"label": "Gestão de Usuários", "endpoint": "gestao_usuarios.index", "icone": "users"},
        {"label": "Inclusão", "endpoint": "inclusao.index", "icone": "shield"},
    ]},
    {"nome": "Apoio", "itens": [
        {"label": "Dúvidas", "endpoint": "coordenador_professores.duvidas", "icone": "help"},
    ]},
]

# Direção (e direção pedagógica — mesmo alcance, ver PAPEIS_DIRECAO em
# app/auth.py) usa o mesmo menu da coordenação, mais "Gestão de Turmas" — a
# tela que cria/edita a estrutura de séries e turmas da escola. Só quem tem
# esse alcance vê esse item porque a estrutura de turmas atravessa todos os
# segmentos ao mesmo tempo, enquanto uma coordenação é escopada a um
# segmento só (ver escopo_etapa em app/auth.py); mostrar o link pra ela
# levaria a uma tela que o próprio login_obrigatorio bloquearia em seguida.
# Direção pedagógica enxerga o mesmo item e pode criar/editar série e turma
# normalmente — só não vê os botões de exclusão dentro da tela (ver
# app/modules/turmas.py:PAPEIS_EXCLUSAO_TURMAS).
_MENU_DIRECAO = [
    {"nome": "Pedagógico", "itens": _MENU_COORDENACAO[0]["itens"] + [
        {"label": "Gestão de Turmas", "endpoint": "turmas.gestao", "icone": "layers"},
    ]},
] + _MENU_COORDENACAO[1:]

MENU_POR_PAPEL = {
    "aluno": [
        {"nome": "Minha jornada", "itens": [
            {"label": "Diagnóstico Adaptativo", "endpoint": "diagnostico.index", "icone": "target"},
            {"label": "Redação", "endpoint": "redacao.index", "icone": "file-text"},
            {"label": "Bússola Vocacional", "endpoint": "bussola_vocacional.index", "icone": "compass"},
        ]},
    ],
    "professor": [
        {"nome": "Turmas", "itens": [
            {"label": "Turmas", "endpoint": "turmas.index", "icone": "grid"},
            {"label": "Coordenador de Professores", "endpoint": "coordenador_professores.index", "icone": "layers"},
        ]},
        {"nome": "Apoio", "itens": [
            {"label": "Inclusão", "endpoint": "inclusao.index", "icone": "shield"},
            {"label": "Dúvidas", "endpoint": "coordenador_professores.duvidas", "icone": "help"},
        ]},
    ],
    "coordenador": _MENU_COORDENACAO,
    "direcao": _MENU_DIRECAO,
    "direcao_pedagogica": _MENU_DIRECAO,
    "psicopedagoga": [
        {"nome": "Pedagógico", "itens": [
            {"label": "Turmas", "endpoint": "turmas.index", "icone": "grid"},
            {"label": "Inclusão", "endpoint": "inclusao.index", "icone": "shield"},
        ]},
        {"nome": "Apoio", "itens": [
            {"label": "Dúvidas", "endpoint": "coordenador_professores.duvidas", "icone": "help"},
        ]},
    ],
    "familia": [
        {"nome": "Acompanhamento", "itens": [
            {"label": "Relatórios", "endpoint": "relatorios_familia.index", "icone": "file-text"},
        ]},
    ],
}


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-troque-em-producao")
    app.jinja_env.filters["data"] = _fmt_data
    app.jinja_env.filters["disciplina"] = _fmt_disciplina
    app.jinja_env.filters["iniciais"] = _fmt_iniciais
    init_db(app)
    app.register_blueprint(auth.bp)
    app.register_blueprint(diagnostico.bp)
    app.register_blueprint(radar_coordenacao.bp)
    app.register_blueprint(bussola_vocacional.bp)
    app.register_blueprint(redacao.bp)
    app.register_blueprint(relatorios_familia.bp)
    app.register_blueprint(inclusao.bp)
    app.register_blueprint(gestao_usuarios.bp)
    app.register_blueprint(coordenador_professores.bp)
    app.register_blueprint(turmas.bp)

    @app.context_processor
    def _injetar_layout():
        """Disponibiliza pro base.html, em toda página logada: o menu lateral
        certo pro papel de quem está vendo, o rótulo bonito do papel e o nome
        da escola — sem precisar que cada rota de cada módulo passe isso."""
        u = session.get("usuario")
        if not u:
            return {}
        db = get_db()
        escola = db.execute("select nome from escolas where id = ?", (u["escola_id"],)).fetchone()
        segmento = escopo_etapa(u)
        return {
            "menu_lateral": MENU_POR_PAPEL.get(u["papel"], []),
            "papel_label": PAPEIS_LABEL.get(u["papel"], u["papel"].capitalize()),
            "escola_atual": escola["nome"] if escola else None,
            "segmento_atual": SEGMENTOS_LABEL.get(segmento) if segmento else None,
            "icones_svg": ICONES_SVG,
        }

    return app
