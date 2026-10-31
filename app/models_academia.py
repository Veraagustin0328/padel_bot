"""Tablas de la academia: clases con sus alumnos, asistencia, faltas y recuperaciones,
tutores de kids, links de registro, promos y reglas.

No toca las tablas viejas (alumnos, usuarios, profesores...): lo nuevo de cada alumno
o usuario va en una tabla "perfil" aparte, así el agente actual sigue andando igual.
"""
from datetime import date, datetime

from app.extensions import db

# valores posibles (se validan en el código, no en la base)
TIPOS_CLASE = ("grupal", "particular", "particular_2", "otro")
AMBITOS = ("adultos", "adultos_tarde", "sabados", "kids", "kids_pro")
ROLES = ("admin", "encargado", "profe", "jugador", "tutor")


# ---------- personas ----------

class AlumnoPerfil(db.Model):
    """Datos nuevos del alumno: nivel (lo que dice él y lo que confirma el profe), rama y si es menor."""
    __tablename__ = "alumno_perfil"

    alumno_id = db.Column(db.Integer, db.ForeignKey("alumnos.id", ondelete="CASCADE"), primary_key=True)
    nivel_declarado = db.Column(db.String(20), nullable=True)   # lo que dijo el alumno (ej. 5TA)
    nivel_confirmado = db.Column(db.String(20), nullable=True)  # lo que confirmó un profe
    nivel_confirmado_por = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=True)
    nivel_confirmado_en = db.Column(db.DateTime, nullable=True)
    rama = db.Column(db.String(10), nullable=True)              # damas / caballeros / mixto
    es_menor = db.Column(db.Boolean, nullable=False, default=False)
    fecha_nacimiento = db.Column(db.Date, nullable=True)
    email = db.Column(db.String(160), nullable=True)


class UsuarioPerfil(db.Model):
    """Estado de la cuenta: los profes que se registran por link quedan 'pendiente' hasta que Gabi los aprueba."""
    __tablename__ = "usuario_perfil"

    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id", ondelete="CASCADE"), primary_key=True)
    estado = db.Column(db.String(12), nullable=False, default="activo")  # pendiente / activo / rechazado
    creado_via = db.Column(db.String(20), nullable=True)                 # panel / link_profe / link_jugador / link_tutor
    aprobado_por = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=True)
    aprobado_en = db.Column(db.DateTime, nullable=True)


class AlumnoUsuario(db.Model):
    """Qué usuario ve a qué alumno: el jugador se ve a sí mismo; un padre o madre ve a cada hijo (máx. 2 tutores por chico)."""
    __tablename__ = "alumno_usuario"
    __table_args__ = (db.UniqueConstraint("alumno_id", "usuario_id", name="uq_alumno_usuario"),)

    id = db.Column(db.Integer, primary_key=True)
    alumno_id = db.Column(db.Integer, db.ForeignKey("alumnos.id", ondelete="CASCADE"), nullable=False, index=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True)
    relacion = db.Column(db.String(10), nullable=False)  # jugador / padre / madre / tutor
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)


class LinkRegistro(db.Model):
    """Link de registro con código. Se puede desactivar y generar otro si se filtra."""
    __tablename__ = "links_registro"

    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(10), nullable=False)  # profe / jugador / tutor
    codigo = db.Column(db.String(40), nullable=False, unique=True)
    activo = db.Column(db.Boolean, nullable=False, default=True)
    vence_en = db.Column(db.DateTime, nullable=True)
    creado_por = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=True)
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)


class TokenClave(db.Model):
    """Pedido de 'olvidé mi contraseña'. Se guarda el hash del token, nunca el token."""
    __tablename__ = "tokens_clave"

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = db.Column(db.String(64), nullable=False, unique=True)
    vence_en = db.Column(db.DateTime, nullable=False)
    usado_en = db.Column(db.DateTime, nullable=True)
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)


# ---------- clases ----------

class Clase(db.Model):
    """Una clase del horario fijo: día + hora + profe + tipo + nivel."""
    __tablename__ = "clases"

    id = db.Column(db.Integer, primary_key=True)
    ambito = db.Column(db.String(15), nullable=False)             # adultos / adultos_tarde / sabados / kids / kids_pro
    dia_semana = db.Column(db.SmallInteger, nullable=False)       # 0 = lunes ... 5 = sábado
    hora_inicio = db.Column(db.Time, nullable=False)
    duracion_min = db.Column(db.SmallInteger, nullable=False, default=60)
    profesor_id = db.Column(db.Integer, db.ForeignKey("profesores.id"), nullable=True, index=True)
    tipo = db.Column(db.String(12), nullable=False, default="grupal")  # grupal / particular / particular_2 / otro
    nivel = db.Column(db.String(20), nullable=True)               # 5TA, 6TA/7MA, PRINCIPIANTES...
    rama = db.Column(db.String(10), nullable=True)                # damas / caballeros / mixto
    cupo = db.Column(db.SmallInteger, nullable=False, default=4)
    activa = db.Column(db.Boolean, nullable=False, default=True)
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)


class Inscripcion(db.Model):
    """Un alumno anotado en una clase fija. 'hasta' vacío = sigue anotado."""
    __tablename__ = "inscripciones"
    __table_args__ = (
        # un alumno no puede estar dos veces vigente en la misma clase
        db.Index("uq_inscripcion_vigente", "clase_id", "alumno_id", unique=True,
                 postgresql_where=db.text("hasta IS NULL")),
    )

    id = db.Column(db.Integer, primary_key=True)
    clase_id = db.Column(db.Integer, db.ForeignKey("clases.id", ondelete="CASCADE"), nullable=False, index=True)
    alumno_id = db.Column(db.Integer, db.ForeignKey("alumnos.id", ondelete="CASCADE"), nullable=False, index=True)
    desde = db.Column(db.Date, nullable=False, default=date.today)
    hasta = db.Column(db.Date, nullable=True)


# ---------- asistencia ----------

class ClaseDictada(db.Model):
    """Prueba de que una clase se dio en una fecha: quién la marcó y cuándo. De acá salen las horas del profe."""
    __tablename__ = "clases_dictadas"
    __table_args__ = (db.UniqueConstraint("clase_id", "fecha", name="uq_clase_dictada"),)

    id = db.Column(db.Integer, primary_key=True)
    clase_id = db.Column(db.Integer, db.ForeignKey("clases.id"), nullable=False, index=True)
    fecha = db.Column(db.Date, nullable=False, index=True)
    profesor_id = db.Column(db.Integer, db.ForeignKey("profesores.id"), nullable=True)  # quien la dio de verdad
    marcada_por = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=True)
    marcada_en = db.Column(db.DateTime, default=datetime.utcnow)
    nota = db.Column(db.String(255), nullable=True)


class Asistencia(db.Model):
    """Presente o ausente de cada alumno en una clase dictada."""
    __tablename__ = "asistencias"
    __table_args__ = (db.UniqueConstraint("clase_dictada_id", "alumno_id", name="uq_asistencia"),)

    id = db.Column(db.Integer, primary_key=True)
    clase_dictada_id = db.Column(db.Integer, db.ForeignKey("clases_dictadas.id", ondelete="CASCADE"),
                                 nullable=False, index=True)
    alumno_id = db.Column(db.Integer, db.ForeignKey("alumnos.id"), nullable=False, index=True)
    estado = db.Column(db.String(10), nullable=False)             # presente / ausente
    origen = db.Column(db.String(15), nullable=False, default="fija")  # fija / recuperacion / suelta
    marcado_en = db.Column(db.DateTime, default=datetime.utcnow)


class Ausencia(db.Model):
    """Falta de un alumno en una clase y fecha, avisada o marcada. Es lo que habilita una recuperación."""
    __tablename__ = "ausencias"
    __table_args__ = (db.UniqueConstraint("alumno_id", "clase_id", "fecha", name="uq_ausencia"),)

    id = db.Column(db.Integer, primary_key=True)
    alumno_id = db.Column(db.Integer, db.ForeignKey("alumnos.id"), nullable=False, index=True)
    clase_id = db.Column(db.Integer, db.ForeignKey("clases.id"), nullable=False)
    fecha = db.Column(db.Date, nullable=False, index=True)
    origen = db.Column(db.String(12), nullable=False)             # alumno / profe / encargado / agente
    motivo = db.Column(db.String(255), nullable=True)
    creada_en = db.Column(db.DateTime, default=datetime.utcnow)


class RecuperacionClase(db.Model):
    """Un alumno que recupera en otra clase, solo ese día. Si se sale de la regla queda 'pendiente' para Gabi."""
    __tablename__ = "recuperaciones_clase"

    id = db.Column(db.Integer, primary_key=True)
    alumno_id = db.Column(db.Integer, db.ForeignKey("alumnos.id"), nullable=False, index=True)
    ausencia_id = db.Column(db.Integer, db.ForeignKey("ausencias.id"), nullable=True)  # vacío si Gabi lo mete a mano
    clase_id = db.Column(db.Integer, db.ForeignKey("clases.id"), nullable=False)       # la clase donde recupera
    fecha = db.Column(db.Date, nullable=False, index=True)
    estado = db.Column(db.String(12), nullable=False, default="confirmada")  # confirmada / pendiente / rechazada / cancelada
    fuera_de_regla = db.Column(db.String(255), nullable=True)   # por qué se salió de la regla
    pedida_por = db.Column(db.String(12), nullable=False, default="agente")  # agente / alumno / encargado
    resuelta_por = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=True)
    resuelta_en = db.Column(db.DateTime, nullable=True)
    creada_en = db.Column(db.DateTime, default=datetime.utcnow)


# ---------- promos ----------

class Promo(db.Model):
    __tablename__ = "promos"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(80), nullable=False)
    descripcion = db.Column(db.String(255), nullable=True)
    tipo = db.Column(db.String(12), nullable=False)               # porcentaje / monto_fijo
    valor = db.Column(db.Numeric(12, 2), nullable=False)
    duracion_meses = db.Column(db.SmallInteger, nullable=True)    # vacío = sin vencimiento
    acumulable = db.Column(db.Boolean, nullable=False, default=False)
    activa = db.Column(db.Boolean, nullable=False, default=True)
    creada_en = db.Column(db.DateTime, default=datetime.utcnow)


class PromoAlumno(db.Model):
    """Promo aplicada a un alumno, con desde y hasta."""
    __tablename__ = "promo_alumno"

    id = db.Column(db.Integer, primary_key=True)
    promo_id = db.Column(db.Integer, db.ForeignKey("promos.id"), nullable=False, index=True)
    alumno_id = db.Column(db.Integer, db.ForeignKey("alumnos.id"), nullable=False, index=True)
    desde = db.Column(db.Date, nullable=False, default=date.today)
    hasta = db.Column(db.Date, nullable=True)
    aplicada_por = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=True)
    creada_en = db.Column(db.DateTime, default=datetime.utcnow)


# ---------- reglas y registro de cambios ----------

class ConfigAcademia(db.Model):
    """Reglas y datos de cada academia (clave -> valor en JSON). Lo que cambia entre clientes va acá."""
    __tablename__ = "config_academia"

    clave = db.Column(db.String(60), primary_key=True)
    valor = db.Column(db.Text, nullable=False)


class Auditoria(db.Model):
    """Quién cambió qué y cuándo (asistencia, nivel, promos...)."""
    __tablename__ = "auditoria"

    id = db.Column(db.Integer, primary_key=True)
    entidad = db.Column(db.String(30), nullable=False, index=True)
    entidad_id = db.Column(db.Integer, nullable=True)
    accion = db.Column(db.String(30), nullable=False)
    antes = db.Column(db.Text, nullable=True)
    despues = db.Column(db.Text, nullable=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=True)
    en = db.Column(db.DateTime, default=datetime.utcnow, index=True)