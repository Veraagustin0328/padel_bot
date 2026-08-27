from flask import Flask
from dotenv import load_dotenv
from app.extensions import db

load_dotenv()


def create_app():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///padel_bot.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    from app.routes.whatsapp import whatsapp_bp
    app.register_blueprint(whatsapp_bp)

    with app.app_context():
        from app import models
        db.create_all()

    return app