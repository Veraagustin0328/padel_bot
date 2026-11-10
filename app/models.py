from datetime import datetime
from app.extensions import db


class Alumno(db.Model):
    __tablename__ = "alumnos"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(120), nullable=False)
    telefono = db.Column(db.String(20), unique=True, nullable=False, index=True)
    categoria = db.Column(db.String(20), nullable=False)
    planilla = db.Column(db.String(30), nullable=False)  # adultos, kids, kids_pro, etc.
    estado = db.Column(db.String(20), default="activo")  # activo / baja
    fecha_inscripcion = db.Column(db.DateTime, default=datetime.utcnow)
    motivo_baja = db.Column(db.String(20), nullable=True)


class Grupo(db.Model):
    __tablename__ = "grupos"

    id = db.Column(db.Integer, primary_key=True)
    profesor = db.Column(db.String(80), nullable=False)
    dia = db.Column(db.String(15), nullable=False)
    horario = db.Column(db.String(10), nullable=False)
    categoria = db.Column(db.String(20), nullable=True)
    cupo_max = db.Column(db.Integer, default=4)
    
class ClaseSuelta(db.Model):
    __tablename__ = "clases_sueltas"

    id = db.Column(db.Integer, primary_key=True)
    telefono = db.Column(db.String(20), nullable=False)
    tipo = db.Column(db.String(20), nullable=False)  # particular / grupal
    dia = db.Column(db.String(15), nullable=False)
    horario = db.Column(db.String(10), nullable=False)
    profesor = db.Column(db.String(80), nullable=True)  # opcional, si lo pidieron
    estado = db.Column(db.String(20), default="pendiente")
    
from datetime import datetime

class Conversacion(db.Model):
    __tablename__ = "conversaciones"

    id = db.Column(db.Integer, primary_key=True)
    telefono = db.Column(db.String(20), nullable=False, index=True)
    rol = db.Column(db.String(20), nullable=False)  # user / assistant
    contenido = db.Column(db.Text, nullable=False)
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)
    
class Pago(db.Model):
    __tablename__ = "pagos"

    id = db.Column(db.Integer, primary_key=True)
    telefono = db.Column(db.String(20), nullable=False, index=True)
    mes = db.Column(db.String(20), nullable=False)
    monto = db.Column(db.Numeric(10, 2), nullable=False)
    estado = db.Column(db.String(20), default="pendiente") 

class CambioPendiente(db.Model):
    """Cambios que dependen de alguien más. Dos casos:
    - reasignacion: propuesta en texto libre del encargado (lo viejo), espera al alumno.
    - cambio_dias: deja unas clases fijas y pasa a otras desde vigente_desde.
      Si lo pide el alumno espera al encargado; si lo propone el encargado espera al alumno.
    Las columnas nuevas las agrega migrar_cambios.py.
    """
    __tablename__ = "cambios_pendientes"

    id = db.Column(db.Integer, primary_key=True)
    alumno_telefono = db.Column(db.String(20), nullable=False, index=True)
    tipo = db.Column(db.String(30), nullable=False)  # reasignacion / cambio_dias
    propuesta = db.Column(db.Text, nullable=False)  # descripción en texto de qué se propone
    # pendiente / aceptado (lo viejo) / aprobado / rechazado / cancelado
    estado = db.Column(db.String(20), default="pendiente")
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)

    alumno_id = db.Column(db.Integer, db.ForeignKey("alumnos.id"), nullable=True, index=True)
    clases_deja = db.Column(db.Text, nullable=True)     # JSON con ids de clase
    clases_nuevas = db.Column(db.Text, nullable=True)   # JSON con ids de clase
    vigente_desde = db.Column(db.Date, nullable=True)
    origen = db.Column(db.String(15), nullable=True)    # alumno / encargado / panel
    espera = db.Column(db.String(15), nullable=True)    # mientras está pendiente: alumno / encargado
    pedido_por = db.Column(db.String(120), nullable=True)  # teléfono o nombre de quien lo pidió
    precio_estimado = db.Column(db.Integer, nullable=True)  # cuota nueva; vacío = sin tarifa exacta
    motivo_rechazo = db.Column(db.Text, nullable=True)
    resuelto_en = db.Column(db.DateTime, nullable=True)
    resuelto_por = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=True)
    
    
class Recuperacion(db.Model):
    __tablename__ = "recuperaciones"

    id = db.Column(db.Integer, primary_key=True)
    telefono = db.Column(db.String(20), nullable=False, index=True)
    mes = db.Column(db.String(20), nullable=False)
    dia_nuevo = db.Column(db.String(15), nullable=False)
    horario_nuevo = db.Column(db.String(10), nullable=False)
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)
    
    
class Notificacion(db.Model):
    __tablename__ = "notificaciones"

    id = db.Column(db.Integer, primary_key=True)
    mensaje = db.Column(db.Text, nullable=False)
    tipo = db.Column(db.String(30), nullable=False)  # alta_alumno, cambio_resuelto, etc.
    leida = db.Column(db.Boolean, default=False)
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)
    
class EstadoChat(db.Model):
    __tablename__ = "estados_chat"

    id = db.Column(db.Integer, primary_key=True)
    telefono = db.Column(db.String(20), unique=True, nullable=False, index=True)
    modo = db.Column(db.String(10), default="bot")  # "bot" o "humano"