import os
from flask import Flask

from .db import init_db
from . import auth
from .modules import diagnostico_matematica, radar_coordenacao, bussola_vocacional


def _fmt_data(valor):
    """Formata datas iguais para SQLite (texto) e Postgres (datetime já
    decodificado pelo psycopg2) — usado nos templates como filtro |data."""
    if not valor:
        return "—"
    return str(valor)[:16].replace("T", " ")


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-troque-em-producao")
    app.jinja_env.filters["data"] = _fmt_data
    init_db(app)
    app.register_blueprint(auth.bp)
    app.register_blueprint(diagnostico_matematica.bp)
    app.register_blueprint(radar_coordenacao.bp)
    app.register_blueprint(bussola_vocacional.bp)
    return app
