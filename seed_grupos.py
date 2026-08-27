from app import create_app
from app.extensions import db
from app.models import Grupo

app = create_app()

grupos_reales = [
    {"profesor": "Marcos", "dia": "lunes", "horario": "07:00", "categoria": "3RA", "cupo_max": 4},
    {"profesor": "Alejo", "dia": "lunes", "horario": "07:00", "categoria": "5TA", "cupo_max": 4},
    {"profesor": "Paolo", "dia": "lunes", "horario": "07:00", "categoria": "5TA", "cupo_max": 4},
    {"profesor": "Gero", "dia": "lunes", "horario": "07:00", "categoria": "5TA", "cupo_max": 4},
    {"profesor": "Franco", "dia": "lunes", "horario": "07:00", "categoria": "7MA", "cupo_max": 4},
    {"profesor": "Tincho", "dia": "lunes", "horario": "07:00", "categoria": "7MA", "cupo_max": 4},
    {"profesor": "Marcos", "dia": "lunes", "horario": "08:00", "categoria": "7MA", "cupo_max": 4},
    {"profesor": "Paolo", "dia": "lunes", "horario": "08:00", "categoria": "PARTICULAR DE 2", "cupo_max": 2},
    {"profesor": "Nora Robles", "dia": "lunes", "horario": "09:00", "categoria": "7MA", "cupo_max": 4},
    {"profesor": "Sol Pascolatti", "dia": "lunes", "horario": "09:00", "categoria": "PRINCIPIANTES", "cupo_max": 4},
]

with app.app_context():
    for g in grupos_reales:
        db.session.add(Grupo(**g))
    db.session.commit()
    print(f"Se cargaron {len(grupos_reales)} grupos.")