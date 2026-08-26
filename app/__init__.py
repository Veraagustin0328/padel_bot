from flask import Flask
from app.extensions import db


def create_app():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///padel_bot.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    with app.app_context():
        from app import models  # importa los modelos para que SQLAlchemy los registre
        db.create_all()

    return app