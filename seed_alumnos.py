from app import create_app
from app.extensions import db
from app.models import Alumno

app = create_app()

with app.app_context():
    db.session.add(Alumno(nombre="Agustin Vera", telefono="5492611234599", categoria="5ta", planilla="adultos"))
    db.session.commit()
    print("Alumno cargado.")