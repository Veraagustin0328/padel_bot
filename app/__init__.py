import os
from flask import Flask
from flask_cors import CORS
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

    # El panel en React corre en otro puerto mientras desarrollamos (Vite usa 5173).
    # En produccion se cambia con la variable CORS_ORIGINS (separadas por coma).
    origenes = os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",")
    CORS(app, resources={r"/api/*": {"origins": origenes}})

    from app.routes.whatsapp import whatsapp_bp
    from app.routes.auth import auth_bp
    from app.routes.planes import planes_bp
    from app.routes.comprobantes import comprobantes_bp
    app.register_blueprint(whatsapp_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(planes_bp)
    app.register_blueprint(comprobantes_bp)

    with app.app_context():
        from app import models
        from app import models_plataforma  # tablas de la plataforma (planes, cuotas, profes, etc.)
        db.create_all()

    return app