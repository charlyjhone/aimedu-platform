import os
from flask import Flask

from .db import init_db
from . import auth
from .modules import diagnostico, radar_coordenacao, bussola_vocacional, redacao, relatorios_familia, inclusao, gestao_usuarios, coordenador_professores, turmas
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


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-troque-em-producao")
    app.jinja_env.filters["data"] = _fmt_data
    app.jinja_env.filters["disciplina"] = _fmt_disciplina
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
    return app
