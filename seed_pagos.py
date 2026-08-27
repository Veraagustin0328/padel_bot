from app import create_app
from app.extensions import db
from app.models import Pago

app = create_app()

pagos = [
    {"telefono": "5492611234599", "mes": "agosto", "monto": 92000, "estado": "confirmado"},
    {"telefono": "5492611234567", "mes": "agosto", "monto": 92000, "estado": "pendiente"},
]

with app.app_context():
    for p in pagos:
        db.session.add(Pago(**p))
    db.session.commit()
    print(f"Se cargaron {len(pagos)} pagos.")