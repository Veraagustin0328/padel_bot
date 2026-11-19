import os
from flask import Flask
from flask_cors import CORS
from app import entorno

# antes que nada: elige .env o .env.simulacion y frena si algo apunta a lo real sin confirmar.
# Va aca (al importar el paquete) para cubrir tambien los scripts que no usan create_app
try:
    entorno.preparar()
except entorno.EntornoError as e:
    print(f"\n[entorno] {e}\n", flush=True)
    raise SystemExit(1)

from app.extensions import db


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

    from app.routes.whatsapp import whatsapp_bp, avisar_firma_al_arrancar
    from app.routes.auth import auth_bp
    from app.routes.planes import planes_bp
    from app.routes.cuotas import cuotas_bp
    from app.routes.clases import clases_bp
    from app.routes.alumnos import alumnos_bp
    from app.routes.comprobantes import comprobantes_bp
    from app.routes.asistencia import asistencia_bp
    from app.routes.solicitudes import solicitudes_bp
    from app.routes.novedades import novedades_bp
    from app.routes.recuperaciones import recuperaciones_bp
    from app.routes.notas import notas_bp
    from app.routes.cambios import cambios_bp
    from app.routes.consultas import consultas_bp
    from app.routes.horas_profes import horas_profes_bp
    from app.routes.estadistica_horas import estadistica_horas_bp
    app.register_blueprint(whatsapp_bp)
    avisar_firma_al_arrancar()  # grita en el log si falta META_APP_SECRET
    app.register_blueprint(auth_bp)
    app.register_blueprint(planes_bp)
    app.register_blueprint(cuotas_bp)
    app.register_blueprint(clases_bp)
    app.register_blueprint(alumnos_bp)
    app.register_blueprint(comprobantes_bp)
    app.register_blueprint(asistencia_bp)
    app.register_blueprint(solicitudes_bp)
    app.register_blueprint(novedades_bp)
    app.register_blueprint(recuperaciones_bp)
    app.register_blueprint(notas_bp)
    app.register_blueprint(cambios_bp)
    app.register_blueprint(consultas_bp)
    app.register_blueprint(horas_profes_bp)
    app.register_blueprint(estadistica_horas_bp)

    # en produccion esto no existe: ni la ruta del cartel ni el simulador
    if entorno.es_simulacion():
        from app.routes.simulacion import simulacion_bp
        app.register_blueprint(simulacion_bp)

    # para pingers y para que Render no se duerma: sin login, no toca la base ni devuelve datos
    @app.get("/salud")
    def salud():
        return {"ok": True}

    with app.app_context():
        from app import models
        from app import models_plataforma  # tablas de la plataforma (planes, cuotas, profes, etc.)
        from app import models_academia  # clases, asistencia, promos, reglas
        _tablas(app)

    return app


def _tablas(app):
    """create_all tarda ~10 s al despertar (una consulta por tabla contra Neon), asi que va
    solo con CREATE_ALL=1: hay que prenderlo una vez cuando se suma un modelo nuevo.
    Si no, una sola consulta mira que esten todas y grita en el log si falta alguna."""
    if os.environ.get("CREATE_ALL") == "1":
        db.create_all()
        return
    try:
        from sqlalchemy import inspect
        hay = set(inspect(db.engine).get_table_names())
    except Exception as e:  # si la base no contesta, que lo diga el primer pedido, no el arranque
        app.logger.warning("No pude revisar las tablas al arrancar: %s", e)
        return
    faltan = sorted(set(db.metadata.tables) - hay)
    if faltan:
        print(f"[arranque] FALTAN TABLAS: {', '.join(faltan)}. Arranca con CREATE_ALL=1 una vez.", flush=True)
        app.logger.error("Faltan tablas: %s (correr con CREATE_ALL=1)", ", ".join(faltan))