import os
import calendar as calendar_stdlib
from datetime import datetime, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo
from flask import Flask, session, request

from .db import init_db, get_db
from . import auth
from .auth import escopo_etapa, PAPEIS_DIRECAO
from .modules import diagnostico, radar_coordenacao, bussola_vocacional, redacao, relatorios_familia, inclusao, gestao_usuarios, coordenador_professores, turmas, observacoes_infantil, calendario, trilha_adaptativa
from .modules.gestao_usuarios import PAPEIS_LABEL, SEGMENTOS_LABEL
from .modules.calendario import _publicos_visiveis, _segmento_do_usuario, _eventos_visiveis, _dias_do_mes_com_evento, PAPEIS_GERENCIA
from .ai_engine import NOMES_DISCIPLINA

_DIAS_SEMANA = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
_MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
          "agosto", "setembro", "outubro", "novembro", "dezembro"]

# Ambas as escolas do usuário ficam em horário UTC-3 sem horário de verão
# (Brasil não usa mais DST desde 2019) — usar isso em vez de UTC puro
# importa pra dois cálculos: a saudação ("bom dia"/"boa tarde"/"boa noite")
# e a virada do dia à meia-noite local, que em UTC aconteceria 3h "adiantada"
# (ex.: 21h de Macapá já seria "amanhã" se calculado em UTC puro).
_FUSO_BRASIL = ZoneInfo("America/Sao_Paulo")


def _agora_brasil() -> datetime:
    return datetime.now(_FUSO_BRASIL)


def _saudacao(agora: datetime) -> str:
    """Saudação de acordo com a hora local — parte do cabeçalho de
    boas-vindas mais 'legal' pedido pelo usuário em 2026-09-09 (antes era
    sempre 'Olá', não importava a hora)."""
    hora = agora.hour
    if 5 <= hora < 12:
        return "Bom dia"
    if 12 <= hora < 18:
        return "Boa tarde"
    return "Boa noite"


def _data_extensa(agora: datetime) -> str:
    """Data por extenso em português, sem depender de locale do sistema
    operacional (que pode não ter pt_BR instalado) — usada no cabeçalho de
    boas-vindas de todo painel inicial (ver _painel_topo.html)."""
    return f"{_DIAS_SEMANA[agora.weekday()]}, {agora.day} de {_MESES[agora.month - 1]} de {agora.year}"


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
    "camera": "<path d='M23 19a2 2 0 01-2 2H3a2 2 0 01-2-2V8a2 2 0 012-2h4l2-3h6l2 3h4a2 2 0 012 2z'/><circle cx='12' cy='13' r='4'/>",
    "calendar": "<rect x='3' y='4' width='18' height='18' rx='2'/><path d='M16 2v4M8 2v4M3 10h18'/>",
}

_MENU_COORDENACAO = [
    {"nome": "Pedagógico", "itens": [
        {"label": "Turmas", "endpoint": "turmas.index", "icone": "grid"},
        {"label": "Educação Infantil", "endpoint": "observacoes_infantil.index", "icone": "camera"},
        {"label": "Radar da Coordenação", "endpoint": "radar_coordenacao.index", "icone": "activity"},
        {"label": "Coordenador de Professores", "endpoint": "coordenador_professores.index", "icone": "layers"},
        {"label": "Relatório de Professores", "endpoint": "coordenador_professores.relatorio_professores", "icone": "bar-chart"},
        {"label": "Diagnósticos p/ Revisar", "endpoint": "coordenador_professores.pendencias", "icone": "target"},
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
            {"label": "Trilha Adaptativa", "endpoint": "trilha_adaptativa.index", "icone": "layers"},
            {"label": "Redação", "endpoint": "redacao.index", "icone": "file-text"},
            {"label": "Bússola Vocacional", "endpoint": "bussola_vocacional.index", "icone": "compass"},
        ]},
    ],
    "professor": [
        {"nome": "Turmas", "itens": [
            {"label": "Turmas", "endpoint": "turmas.index", "icone": "grid"},
            {"label": "Educação Infantil", "endpoint": "observacoes_infantil.index", "icone": "camera"},
            {"label": "Coordenador de Professores", "endpoint": "coordenador_professores.index", "icone": "layers"},
            {"label": "Diagnósticos p/ Revisar", "endpoint": "coordenador_professores.pendencias", "icone": "target"},
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
            {"label": "Educação Infantil", "endpoint": "observacoes_infantil.index", "icone": "camera"},
            {"label": "Inclusão", "endpoint": "inclusao.index", "icone": "shield"},
        ]},
        {"nome": "Apoio", "itens": [
            {"label": "Dúvidas", "endpoint": "coordenador_professores.duvidas", "icone": "help"},
        ]},
    ],
    "familia": [
        {"nome": "Acompanhamento", "itens": [
            {"label": "Relatórios", "endpoint": "relatorios_familia.index", "icone": "file-text"},
            {"label": "Educação Infantil", "endpoint": "observacoes_infantil.familia_index", "icone": "camera"},
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
    app.register_blueprint(observacoes_infantil.bp)
    app.register_blueprint(calendario.bp)
    app.register_blueprint(trilha_adaptativa.bp)

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
        # Segmento do próprio usuário (só resolve pra aluno e coordenador —
        # ver docstring de _segmento_do_usuario em app/modules/calendario.py)
        # calculado uma vez só aqui e reaproveitado tanto pros filtros de
        # menu abaixo quanto pro calendário mais adiante.
        segmento_eventos = _segmento_do_usuario(db, u)
        menu = MENU_POR_PAPEL.get(u["papel"], [])
        # Uma coordenação escopada a um segmento que não é infantil não deve
        # nem ver o item "Educação Infantil" no menu — a rota já bloqueia o
        # acesso (ver _turmas_infantil_visiveis em
        # app/modules/observacoes_infantil.py), mas escondê-lo aqui evita um
        # link que sempre levaria a uma lista vazia.
        if u["papel"] == "coordenador" and segmento and segmento != "infantil":
            menu = [
                {**secao, "itens": [i for i in secao["itens"] if i["endpoint"] != "observacoes_infantil.index"]}
                for secao in menu
            ]
        # Redação (correção por IA) e Trilha Adaptativa são só para o Ensino
        # Médio (decisão do usuário em 2026-09-09) — somem do menu de quem
        # não é do médio, e a própria rota de cada módulo bloqueia o acesso
        # direto por URL, mesmo padrão do item acima.
        if u["papel"] == "aluno" and segmento_eventos != "medio":
            menu = [
                {**secao, "itens": [i for i in secao["itens"]
                                     if i["endpoint"] not in ("redacao.index", "trilha_adaptativa.index")]}
                for secao in menu
            ]
        # Próximos eventos do calendário (ver app/modules/calendario.py) —
        # calculado aqui, uma vez só, pra alimentar o widget "Próximos
        # eventos" no topo de todo painel inicial (_painel_topo.html) sem
        # que auth.painel() nem cada módulo precisem saber desse cálculo.
        publicos = _publicos_visiveis(u["papel"])
        eventos_proximos = _eventos_visiveis(db, u["escola_id"], publicos, segmento_eventos, limite=5)

        # Mini calendário visual (topo de todo painel inicial — ver
        # _painel_topo.html). Antes sempre mostrava só o mês corrente, sem
        # jeito de navegar (pedido do usuário em 2026-09-09: "o calendário
        # está estático, dava pra ver o próximo mês"). Agora lê o mês/ano de
        # 'cal_ano'/'cal_mes' na própria URL da página — como o widget
        # aparece em várias rotas diferentes (painel, familia_index etc.),
        # os links de anterior/próximo simplesmente recarregam a MESMA
        # página trocando só esses dois parâmetros, preservando os demais
        # que já estiverem lá.
        agora = _agora_brasil()
        try:
            cal_ano = int(request.args.get("cal_ano", agora.year))
            cal_mes = int(request.args.get("cal_mes", agora.month))
            if not (1 <= cal_mes <= 12):
                raise ValueError
            # Limite generoso só pra não deixar alguém montar um ano
            # absurdo na URL à mão e estourar o calendar_stdlib.
            if not (1900 <= cal_ano <= 2200):
                raise ValueError
        except (TypeError, ValueError):
            cal_ano, cal_mes = agora.year, agora.month

        def _url_mes(ano, mes):
            params = request.args.to_dict()
            params["cal_ano"] = ano
            params["cal_mes"] = mes
            return f"{request.path}?{urlencode(params)}"

        mes_anterior = (cal_ano - 1, 12) if cal_mes == 1 else (cal_ano, cal_mes - 1)
        mes_seguinte = (cal_ano + 1, 1) if cal_mes == 12 else (cal_ano, cal_mes + 1)

        dias_com_evento = _dias_do_mes_com_evento(
            db, u["escola_id"], publicos, segmento_eventos, cal_ano, cal_mes
        )
        eh_mes_atual = (cal_ano, cal_mes) == (agora.year, agora.month)
        calendario_mes = {
            "ano": cal_ano,
            "mes": cal_mes,
            "nome_mes": f"{_MESES[cal_mes - 1].capitalize()} de {cal_ano}",
            "semanas": calendar_stdlib.Calendar(firstweekday=6).monthdayscalendar(cal_ano, cal_mes),
            # Só destaca "hoje" quando o mês exibido é o mês corrente de
            # verdade — navegando pra outro mês não faz sentido nenhum dia
            # aparecer marcado como "hoje".
            "dia_hoje": agora.day if eh_mes_atual else None,
            "dias_com_evento": dias_com_evento,
            "eh_mes_atual": eh_mes_atual,
            "url_mes_anterior": _url_mes(*mes_anterior),
            "url_mes_seguinte": _url_mes(*mes_seguinte),
            "url_mes_atual": _url_mes(agora.year, agora.month),
        }
        return {
            "menu_lateral": menu,
            "papel_label": PAPEIS_LABEL.get(u["papel"], u["papel"].capitalize()),
            "escola_atual": escola["nome"] if escola else None,
            "segmento_atual": SEGMENTOS_LABEL.get(segmento) if segmento else None,
            "icones_svg": ICONES_SVG,
            "saudacao": _saudacao(agora),
            "hoje_extenso": _data_extensa(agora),
            "hoje_iso": agora.date().isoformat(),
            "amanha_iso": (agora.date() + timedelta(days=1)).isoformat(),
            "pode_gerenciar_eventos": u["papel"] in PAPEIS_GERENCIA,
            "eventos_proximos": eventos_proximos,
            "calendario_mes": calendario_mes,
        }

    return app
