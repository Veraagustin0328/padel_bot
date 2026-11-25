"""Tarifa por hora de cada profe (valores_hora) y alta de profes. Solo el dueño (lo frena la ruta).

- Una tarifa nueva es una fila nueva con su "desde": nunca se pisa ni se borra una anterior.
  Rige la de "desde" más nuevo que ya empezó (horas_profes.tarifa_en), así cada clase se paga con
  la tarifa de su fecha y una tarifa futura no cambia lo que ya pasó.
- No puede haber dos tarifas del mismo profe con el mismo "desde".
- Una tarifa con "desde" en un mes ya pasado cambia lo calculado de esos meses: hay que confirmarlo.
- Todo queda en Auditoria con quién lo hizo. El commit lo hace quien llama.
"""
import json
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from app import horas_profes
from app.extensions import db
from app.models_academia import Auditoria
from app.models_plataforma import Profesor, ValorHora

MONTO_MAX = Decimal("10000000")
NOMBRE_MAX = 120


class ErrorTarifa(ValueError):
    """No se puede así: el panel muestra el mensaje. .pedir_confirmacion = hay que confirmar y reenviar."""

    def __init__(self, mensaje, pedir_confirmacion=False):
        super().__init__(mensaje)
        self.pedir_confirmacion = pedir_confirmacion


def _auditar(entidad, entidad_id, accion, antes, despues, usuario_id):
    db.session.add(Auditoria(entidad=entidad, entidad_id=entidad_id, accion=accion, usuario_id=usuario_id,
                             antes=json.dumps(antes, ensure_ascii=False, default=str) if antes is not None else None,
                             despues=json.dumps(despues, ensure_ascii=False, default=str)))


def leer_monto(valor) -> Decimal:
    """'15000', 15000, '15.000', '15000,50' -> Decimal. Tiene que ser mayor que cero."""
    texto = str(valor if valor is not None else "").strip().replace("$", "").replace(" ", "")
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d{1,2})?", texto):  # 15.000 o 15.000,50
        texto = texto.replace(".", "").replace(",", ".")
    else:
        texto = texto.replace(",", ".")
    try:
        monto = Decimal(texto)
    except InvalidOperation:
        raise ErrorTarifa("Poné el monto por hora en números (ej. 15000)")
    if not monto.is_finite() or monto <= 0:
        raise ErrorTarifa("El monto por hora tiene que ser mayor que cero")
    if monto > MONTO_MAX:
        raise ErrorTarifa("Ese monto es demasiado grande: revisalo")
    return monto.quantize(Decimal("0.01"))


def leer_fecha(valor) -> date:
    try:
        return date.fromisoformat(str(valor or "").strip())
    except ValueError:
        raise ErrorTarifa("Elegí la fecha desde la que rige (día, mes y año)")


def historial(profesor_id) -> list[dict]:
    """Todas sus tarifas, de la más nueva a la más vieja, con hasta cuándo rige cada una."""
    filas = (ValorHora.query.filter_by(profesor_id=profesor_id)
             .order_by(ValorHora.vigente_desde.desc(), ValorHora.id.desc()).all())
    hoy = horas_profes.ahora_ar().date()
    salida, siguiente = [], None
    for v in filas:
        # rige hasta el día antes de la siguiente (o su propio "hasta" si lo cerraron antes)
        hasta = v.vigente_hasta
        if siguiente is not None:
            corte = siguiente - timedelta(days=1)
            hasta = corte if hasta is None else min(hasta, corte)
        salida.append({"id": v.id, "monto": float(v.monto), "desde": v.vigente_desde.isoformat(),
                       "hasta": hasta.isoformat() if hasta else None,
                       "estado": "futura" if v.vigente_desde > hoy
                       else "vencida" if hasta is not None and hasta < hoy else "vigente"})
        siguiente = v.vigente_desde
    return salida


def agregar_tarifa(profe, monto, desde, usuario_id, confirmar_pasado=False) -> ValorHora:
    """Fila nueva de tarifa. No toca las anteriores. Desde un mes pasado: pide confirmar."""
    monto = leer_monto(monto)
    desde = leer_fecha(desde)
    if desde.year < 2000 or desde.year > 2100:
        raise ErrorTarifa("Esa fecha no parece bien: revisá el año")
    if ValorHora.query.filter_by(profesor_id=profe.id, vigente_desde=desde).first():
        raise ErrorTarifa(f"{profe.nombre} ya tiene una tarifa desde el {desde:%d/%m/%Y}. "
                          "Elegí otra fecha (las tarifas no se pisan)")
    inicio_mes = horas_profes.ahora_ar().date().replace(day=1)
    if desde < inicio_mes and not confirmar_pasado:
        raise ErrorTarifa(f"Rige desde el {desde:%d/%m/%Y}, un mes que ya pasó: cambia lo calculado para "
                          f"{profe.nombre} desde esa fecha. ¿Seguro?", pedir_confirmacion=True)
    v = ValorHora(profesor_id=profe.id, monto=monto, vigente_desde=desde)
    db.session.add(v)
    db.session.flush()
    _auditar("valor_hora", v.id, "alta", None,
             {"profesor_id": profe.id, "profe": profe.nombre, "monto": monto, "desde": desde,
              "mes_pasado": desde < inicio_mes}, usuario_id)
    return v


def _norm(nombre):
    return re.sub(r"\s+", " ", str(nombre or "")).strip()


def crear_profe(nombre, head_coach, monto, desde, usuario_id, confirmar_pasado=False) -> Profesor:
    """Profe nuevo, activo. La primera tarifa es opcional (monto y desde juntos)."""
    nombre = _norm(nombre)
    if len(nombre) < 2 or len(nombre) > NOMBRE_MAX or not re.search(r"[^\W\d_]", nombre):
        raise ErrorTarifa(f"Poné el nombre del profe (hasta {NOMBRE_MAX} letras)")
    if not isinstance(head_coach, bool):
        raise ErrorTarifa("Head Coach tiene que ser sí o no")
    clave = nombre.lower()
    if any(_norm(p.nombre).lower() == clave for p in Profesor.query.filter(Profesor.activo.is_(True))):
        raise ErrorTarifa(f"Ya hay un profe activo que se llama {nombre}")
    con_tarifa = str(monto or "").strip() != "" or str(desde or "").strip() != ""
    if con_tarifa and (str(monto or "").strip() == "" or str(desde or "").strip() == ""):
        raise ErrorTarifa("Para cargar la primera tarifa poné el monto y la fecha desde la que rige")
    if con_tarifa:  # que valide antes de crear nada
        leer_monto(monto)
        leer_fecha(desde)
    profe = Profesor(nombre=nombre, activo=True, es_head_coach=head_coach)
    db.session.add(profe)
    db.session.flush()
    _auditar("profesor", profe.id, "alta", None, {"nombre": nombre, "head_coach": head_coach}, usuario_id)
    if con_tarifa:
        agregar_tarifa(profe, monto, desde, usuario_id, confirmar_pasado=confirmar_pasado)
    return profe


def marcar_head_coach(profe, activo, usuario_id) -> None:
    if bool(profe.es_head_coach) != activo:
        _auditar("profesor", profe.id, "head_coach", {"head_coach": bool(profe.es_head_coach)},
                 {"head_coach": activo}, usuario_id)
        profe.es_head_coach = activo
