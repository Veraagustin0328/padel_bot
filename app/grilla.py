"""Lee las grillas de clases de la planilla de Gabi (adultos, adultos tarde, sábados).
Solo lectura: devuelve las clases que detecta, no escribe nada.

Una "clase" es: día + hora + profe + tipo (grupal / particular / particular de 2)
+ nivel + los alumnos anotados. Las faltas y recuperaciones con fecha que Gabi anota
en la grilla se devuelven aparte, en "excepciones".
"""
import re
import unicodedata

DIAS = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado")
SUF = r"(?:era|ra|da|ta|ma|va)"
NIVEL = rf"[1-8]\s*{SUF}"
CUPO = {"GRUPAL": 4, "PARTICULAR": 1, "PARTICULAR_2": 2}


def _n(s):
    """Minúsculas, sin tildes y sin espacios de más."""
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s.lower()).strip()


def _celda(fila, i):
    if 0 <= i < len(fila) and fila[i] is not None:
        return str(fila[i]).strip()
    return ""


def _etiqueta(txt):
    """Si el texto es una etiqueta de clase devuelve (tipo, nivel, nota); si no, None."""
    n = _n(txt)
    if not n:
        return None
    if n.startswith("partic"):  # incluye el typo "particluar"
        tipo = "PARTICULAR_2" if re.search(r"de ?2", n) else "PARTICULAR"
        nota = "sin pago" if "sin pago" in n else ""
        return tipo, "", nota
    if "principiante" in n:
        return "GRUPAL", "PRINCIPIANTES", ""
    if "presuriz" in n:
        return "OTRO", "PRESURIZACION", ""
    if re.fullmatch(rf"{NIVEL}(\s*/\s*{NIVEL})*", n):
        return "GRUPAL", re.sub(r"\s+", "", n).upper(), ""
    return None


def _es_ruido(txt):
    """Cosas que no son nombres: fechas sueltas, 'recuperan', 'no viene', números."""
    n = _n(txt)
    if re.fullmatch(r"[\d/\.\-: ]+", n):
        return True
    return n.startswith(("recuper", "no viene", "reunion", "arranc", "falta"))


FECHA = r"\d{1,2}/\d{1,2}(?:/\d{2,4})?|\d{4}-\d{2}-\d{2}"


def _analizar(txt):
    """'Jose Pellicer no viene 02/11' -> ('Jose Pellicer', '02/11', True).
    Si en la celda solo hay una nota ('asiste', '27/10 no') el nombre vuelve vacío."""
    t = str(txt).strip()
    m = re.search(FECHA, t)
    fecha = m.group(0) if m else ""
    t = re.sub(FECHA, " ", t)
    no_viene = bool(re.search(r"\bno\s+viene\b", t, re.I))
    t = re.sub(r"\bno\s+viene\b", " ", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"\s+s[aá]bado$", "", t, flags=re.I).strip()
    if _n(t) in ("", "no", "asiste", "asisten", "viene"):
        return "", fecha, no_viene
    return t, fecha, no_viene


def _armar(tab, dia, hora, profe, celdas):
    """celdas: textos de una columna dentro de un bloque. Devuelve la clase o None.

    Lo que Gabi anota en la grilla para una semana puntual no es horario fijo:
    - 'Nombre no viene 02/11'  -> sigue anotado en la clase y queda una falta con fecha.
    - 'Nombre 03/11' (con fecha) -> recuperación de ese día, no cuenta como clase fija.
    """
    tipo, nivel, notas, alumnos, exc = "", "", [], [], []
    for t in celdas:
        if not t:
            continue
        et = _etiqueta(t)
        if et:
            tipo, nivel = et[0], et[1] or nivel
            if et[2]:
                notas.append(et[2])
            continue
        if _es_ruido(t):
            notas.append(t)
            continue
        nombre, fecha, no_viene = _analizar(t)
        if not nombre:
            notas.append(t)
        elif no_viene:
            alumnos.append(nombre)
            exc.append({"alumno": nombre, "fecha": fecha, "tipo": "falta"})
        elif fecha:
            exc.append({"alumno": nombre, "fecha": fecha, "tipo": "recuperacion"})
        else:
            alumnos.append(nombre)
    if not alumnos and not tipo:
        return None
    return {
        "pestana": tab, "dia": dia.upper(), "hora": hora, "profe": profe,
        "tipo": tipo or "SIN_ETIQUETA", "nivel": nivel,
        "cupo": CUPO.get(tipo, 4), "alumnos": alumnos, "notas": notas,
        "excepciones": exc,
    }


PROFES_ADULTOS = {"felipe", "king", "alejo", "marcos", "paolo", "gero", "franco", "tincho", "gabi"}


def _es_fila_profes(fila):
    """La fila con KING, ALEJO, MARCOS... (hay un alumno que también se llama King)."""
    return sum(1 for c in fila if _n(c) in PROFES_ADULTOS) >= 4


def leer_adultos(filas):
    """Grilla de la mañana: horas en filas, días en columnas, una columna por profe en cada día."""
    dias_col = {}
    for i, c in enumerate(filas[0] if filas else []):
        if _n(c) in DIAS:
            dias_col[i] = _n(c)
    if not dias_col:
        return []
    inicios = [i for i, f in enumerate(filas)
               if re.fullmatch(r"\d{1,2}", _celda(f, 0)) and 7 <= int(_celda(f, 0)) <= 13]
    inicios_dia = sorted(dias_col)
    clases = []
    for s in inicios:
        h = next((r for r in range(s + 1, len(filas)) if _es_fila_profes(filas[r])), None)
        if h is None:
            continue
        hora = f"{int(_celda(filas[s], 0)):02d}:00"
        for k, dc in enumerate(inicios_dia):
            dia = dias_col[dc]
            fin = inicios_dia[k + 1] if k + 1 < len(inicios_dia) else dc + 10
            for col in range(dc, fin):
                profe = _celda(filas[h], col).upper()
                if not profe:
                    continue
                celdas = [_celda(filas[r], col) for r in range(s, h)]
                c = _armar("adultos", dia, hora, profe, celdas)
                if c:
                    clases.append(c)
    return clases


def _leer_por_horas(tab, filas, cols, patron_hora, dia_fijo=None):
    """Para pestañas donde cada bloque va de una fila de hora hasta la siguiente."""
    inicios = [i for i, f in enumerate(filas) if re.fullmatch(patron_hora, _celda(f, 0))]
    clases = []
    for k, s in enumerate(inicios):
        e = inicios[k + 1] if k + 1 < len(inicios) else len(filas)
        hora = _celda(filas[s], 0)
        hora = hora if ":" in hora else f"{int(hora):02d}:00"
        for col, valor in cols.items():
            celdas = [_celda(filas[r], col) for r in range(s, e)]
            dia, profe = (dia_fijo, valor) if dia_fijo else (valor, "")
            c = _armar(tab, dia, hora, profe, celdas)
            if c:
                clases.append(c)
    return clases


def leer_tarde(filas):
    hdr = next((i for i, f in enumerate(filas) if any(_n(c) == "lunes" for c in f)), None)
    if hdr is None:
        return []
    cols = {j: _n(c) for j, c in enumerate(filas[hdr]) if _n(c) in DIAS}
    return _leer_por_horas("adultos tarde", filas[hdr + 1:], cols, r"\d{1,2}:\d{2}")


def leer_sabados(filas):
    hdr = next((i for i, f in enumerate(filas)
                if sum(1 for c in f[1:] if _n(c)) >= 2 and not re.fullmatch(r"\d+", _celda(f, 0))), None)
    if hdr is None:
        return []
    cols = {j: str(c).strip().upper() for j, c in enumerate(filas[hdr]) if j > 0 and str(c).strip()}
    return _leer_por_horas("sábados", filas[hdr + 1:], cols, r"\d{1,2}", dia_fijo="sabado")


def plan_por_alumno(clases):
    """Cuenta en cuántas clases fijas aparece cada alumno por semana.

    Si la clase no tiene etiqueta (Gabi no siempre la escribe) se estima por la cantidad
    de alumnos: 1 = particular, 2 = particular de 2, 3 o más = grupal. Esas quedan marcadas
    con (?) y se cuentan en "estimadas", para que Gabi las confirme.
    """
    por = {}
    for c in clases:
        for a in c["alumnos"]:
            d = por.setdefault(_n(a), {"nombre": a, "grupales": 0, "particulares": 0,
                                       "particulares_de_2": 0, "otras": 0, "estimadas": 0,
                                       "clases": []})
            tipo, dudosa = c["tipo"], False
            if tipo == "SIN_ETIQUETA":
                cant = len(c["alumnos"])
                tipo = "PARTICULAR" if cant == 1 else "PARTICULAR_2" if cant == 2 else "GRUPAL"
                dudosa = True
                d["estimadas"] += 1
            if tipo == "PARTICULAR":
                d["particulares"] += 1
            elif tipo == "PARTICULAR_2":
                d["particulares_de_2"] += 1
            elif tipo == "OTRO":
                d["otras"] += 1
            else:
                d["grupales"] += 1
            d["clases"].append(f"{c['dia'][:3]} {c['hora']} {c['profe']}".strip() + (" (?)" if dudosa else ""))
    return sorted(por.values(), key=lambda d: _n(d["nombre"]))