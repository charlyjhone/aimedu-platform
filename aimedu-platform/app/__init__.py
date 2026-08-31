from flask import Flask

from .db import init_db
from . import auth
from .modules import diagnostico_matematica


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "dev-secret-troque-em-producao"
    init_db(app)
    app.register_blueprint(auth.bp)
    app.register_blueprint(diagnostico_matematica.bp)
    return app
