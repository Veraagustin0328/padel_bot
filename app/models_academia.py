"""Tablas de la academia: clases con sus alumnos, asistencia, faltas y recuperaciones,
tutores de kids, links de registro, promos y reglas.

No toca las tablas viejas (alumnos, usuarios, profesores...): lo nuevo de cada alumno
o usuario va en una tabla "perfil" aparte, así el agente actual sigue andando igual.
"""
from datetime import date, datetime

from app.extensions import db

# valores posibles (se validan en el código, no en la base)
TIPOS_CLASE = ("grupal", "particular", "particular_2", "otro", "fisico")  # fisico: no se cobra, se paga la hora
AMBITOS = ("adultos", "adultos_tarde", "sabados", "kids", "kids_pro")
ROLES = ("dueno", "encargado", "profe", "jugador", "tutor", "jugador_tutor")  # jugador_tutor = ambos
# el profe marca solo vino / no vino; el aviso de falta lo carga el agente o el encargado
ESTADOS_ASISTENCIA = ("presente", "ausente")


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
    # primer ingreso o clave reseteada: tiene que cambiarla antes de usar el panel (migrar_debe_cambiar_clave.py)
    debe_cambiar_clave = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())


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
    tipo = db.Column(db.String(12), nullable=False, default="grupal")  # grupal / particular / particular_2 / otro / fisico
    nivel = db.Column(db.String(20), nullable=True)               # 5TA, 6TA/7MA, PRINCIPIANTES...
    rama = db.Column(db.String(10), nullable=True)                # damas / caballeros / mixto
    columna_color = db.Column(db.SmallInteger, nullable=True)     # elegida a mano; vacía = la automática
    cupo = db.Column(db.SmallInteger, nullable=False, default=4)
    activa = db.Column(db.Boolean, nullable=False, default=True)
    # temporada (ej. kids tarde / kids mañana): desde = primer día que se da, hasta = primer día que ya no
    vigente_desde = db.Column(db.Date, nullable=True)  # vacío = desde siempre
    vigente_hasta = db.Column(db.Date, nullable=True)  # vacío = sin fin
    # fila de apoyo: otro profe en el mismo grupo. Los alumnos se anotan solo en la titular;
    # el de apoyo marca "di la clase" y cobra su hora según la titular. Vacío = clase normal
    apoyo_de_clase_id = db.Column(db.Integer, db.ForeignKey("clases.id", ondelete="SET NULL"),
                                  nullable=True, index=True)
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)

    def vigente_en(self, fecha):
        """True si la clase se da en esa fecha según su temporada (no mira 'activa' ni el día)."""
        return ((self.vigente_desde is None or self.vigente_desde <= fecha)
                and (self.vigente_hasta is None or self.vigente_hasta > fecha))


def problema_apoyo(apoyo, titular, anotados_apoyo=0):
    """Por qué 'apoyo' no puede ser fila de apoyo de 'titular', o None si se puede.
    anotados_apoyo: alumnos vigentes en la fila de apoyo (tienen que estar en la titular).
    Sirve para cualquier clase y cualquier club: no mira ámbito, nivel ni tipo."""
    if titular is None:
        return "la clase titular no existe"
    if apoyo.id is not None and apoyo.id == titular.id:
        return "una clase no puede ser apoyo de sí misma"
    if titular.apoyo_de_clase_id is not None:
        return "la titular ya es apoyo de otra clase: tiene que ser una clase normal"
    if apoyo.id is not None and Clase.query.filter(Clase.apoyo_de_clase_id == apoyo.id).first():
        return "esta clase tiene filas de apoyo propias: no puede ser apoyo de otra"
    if not titular.activa:
        return "la clase titular no está activa"
    if apoyo.profesor_id is None:
        return "la fila de apoyo necesita un profe"
    if apoyo.profesor_id == titular.profesor_id:
        return "el profe de apoyo es el mismo que el de la titular"
    if apoyo.dia_semana != titular.dia_semana:
        return "la fila de apoyo tiene que ser el mismo día que la titular"
    ini_a = apoyo.hora_inicio.hour * 60 + apoyo.hora_inicio.minute
    ini_t = titular.hora_inicio.hour * 60 + titular.hora_inicio.minute
    if ini_a < ini_t or ini_a + (apoyo.duracion_min or 60) > ini_t + (titular.duracion_min or 60):
        return "el horario de la fila de apoyo tiene que estar dentro del de la titular"
    if anotados_apoyo:
        return f"la fila de apoyo tiene {anotados_apoyo} alumno(s) anotados: se anotan solo en la titular"
    return None


def clase_vigente_en(fecha):
    """Filtro SQL: clases cuya temporada incluye esa fecha. Se suma a Clase.activa."""
    return db.and_(db.or_(Clase.vigente_desde.is_(None), Clase.vigente_desde <= fecha),
                   db.or_(Clase.vigente_hasta.is_(None), Clase.vigente_hasta > fecha))


def clase_no_terminada(fecha):
    """Filtro SQL: clases que no terminaron su temporada (las que arrancan más adelante entran)."""
    return db.or_(Clase.vigente_hasta.is_(None), Clase.vigente_hasta > fecha)


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
    estado = db.Column(db.String(15), nullable=False)             # presente (vino) / ausente (no vino)
    origen = db.Column(db.String(15), nullable=False, default="fija")  # fija / recuperacion / suelta / panel
    marcado_en = db.Column(db.DateTime, default=datetime.utcnow)
    nota = db.Column(db.String(255), nullable=True)


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
    avisada_en = db.Column(db.DateTime, nullable=True)            # cuándo avisó (UTC); vacío = la marcó el profe
    a_tiempo = db.Column(db.Boolean, nullable=True)               # avisó con la anticipación de la regla
    creada_en = db.Column(db.DateTime, default=datetime.utcnow)


class AusenciaLapso(db.Model):
    """Alumno que no viene un rango de fechas (viaje). Si hay reemplazo, ocupa su lugar solo en ese rango."""
    __tablename__ = "ausencias_lapso"

    id = db.Column(db.Integer, primary_key=True)
    alumno_id = db.Column(db.Integer, db.ForeignKey("alumnos.id"), nullable=False, index=True)
    clase_id = db.Column(db.Integer, db.ForeignKey("clases.id"), nullable=True)   # vacío = todas sus clases
    desde = db.Column(db.Date, nullable=False, index=True)
    hasta = db.Column(db.Date, nullable=False, index=True)        # inclusive
    motivo = db.Column(db.String(255), nullable=True)
    reemplazo_alumno_id = db.Column(db.Integer, db.ForeignKey("alumnos.id"), nullable=True)
    estado = db.Column(db.String(12), nullable=False, default="confirmado")  # confirmado / pendiente / cancelado
    origen = db.Column(db.String(12), nullable=False, default="encargado")   # encargado / agente
    creado_por = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=True)
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)


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

# ---------- novedades del panel ----------

TIPOS_NOVEDAD = ("aviso", "evento", "promo", "importante")
# para quién es: todos, equipo (dueño, encargado, profe) o alumnos (jugador, tutor, ambos)
AUDIENCIAS_NOVEDAD = ("todos", "equipo", "alumnos")


class Novedad(db.Model):
    """Novedad que se ve en el Inicio. Las vencidas no se muestran, pero quedan en la base."""
    __tablename__ = "novedades"

    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(120), nullable=False)
    texto = db.Column(db.Text, nullable=False)
    tipo = db.Column(db.String(20), nullable=False, default="aviso")
    publicada_desde = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    visible_hasta = db.Column(db.Date, nullable=True, index=True)  # inclusive; vacío = sin vencimiento
    creada_por = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=True)
    # default "equipo": si algo la crea sin decir para quién, no le llega a los padres (migrar_novedades_audiencia.py)
    audiencia = db.Column(db.String(10), nullable=False, default="equipo", server_default="equipo")


class Nota(db.Model):
    """Notas internas de dueño y encargado. Pueden ir atadas a un alumno o sueltas.
    visible_profes: la ven (solo lectura) los profes del alumno en Mis clases. Por defecto no.
    Nunca le llegan al alumno ni al padre."""
    __tablename__ = "notas"

    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(120), nullable=False)
    texto = db.Column(db.Text, nullable=True)
    alumno_id = db.Column(db.Integer, db.ForeignKey("alumnos.id"), nullable=True, index=True)
    creada_por = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=True)
    fijada = db.Column(db.Boolean, nullable=False, default=False)
    # la marca solo dueño o encargado (también en menores); la columna la agrega migrar_notas_visibles.py
    visible_profes = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    creada_en = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    actualizada_en = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
