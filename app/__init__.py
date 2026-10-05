import os
from flask import Flask
from dotenv import load_dotenv
from app.extensions import db

load_dotenv()


def create_app():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL", "sqlite:///padel_bot.db"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Neon corta las conexiones que quedan paradas y despues tiraba
    # "SSL error: decryption failed". Con esto prueba la conexion antes de
    # usarla y las renueva cada 280 segundos.
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
        "pool_recycle": 280,
    }

    db.init_app(app)

    from app.routes.whatsapp import whatsapp_bp
    app.register_blueprint(whatsapp_bp)

    with app.app_context():
        from app import models
        db.create_all()

    return app