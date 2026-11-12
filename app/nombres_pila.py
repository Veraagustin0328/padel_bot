"""Sugerir la rama de una clase (damas / caballeros / mixto) por los nombres de pila de sus alumnos.

Es solo una ayuda: el panel muestra "sugerido: Damas" y alguien lo confirma con un toque.
Los apodos (Agus, Fede, Coti...) y los nombres que pueden ser de los dos (Andrea, Rosario...)
no cuentan. Las listas son nombres comunes en castellano, nada de un club en particular.
"""
import unicodedata

DAMAS = {
    "abril", "adriana", "agostina", "agustina", "aldana", "alejandra", "alicia", "alma", "amalia",
    "ana", "analia", "angela", "antonella", "antonia", "aylen", "barbara", "beatriz",
    "belen", "bianca", "brenda", "camila", "candela", "carla", "carina", "carmen", "carolina",
    "catalina", "cecilia", "celeste", "clara", "claudia", "constanza", "cristina", "daiana", "dana",
    "daniela", "debora", "delfina", "diana", "dolores", "elena", "eliana", "elisa", "emilia", "estefania",
    "eugenia", "eva", "fabiana", "fernanda", "florencia", "gabriela", "gimena", "gisela", "graciela",
    "guillermina", "ines", "irene", "isabel", "jaqueline", "jazmin", "jesica", "jessica", "jimena",
    "josefina", "juana", "judith", "julia", "juliana", "julieta", "karina", "laura", "lara", "lorena",
    "lourdes", "lucia", "luciana", "ludmila", "luisa", "luz", "macarena", "magdalena", "malena",
    "marcela", "margarita", "maria", "mariana", "maribel", "marina", "marisa", "marta", "martina",
    "melina", "mercedes", "micaela", "milagros", "milena", "mirta", "monica", "morena", "nadia",
    "natalia", "nicole", "noelia", "norma", "olivia", "paola", "patricia", "paula", "paulina", "pilar",
    "rocio", "romina", "rosa", "ruth", "sabrina", "sandra", "silvana", "silvia", "sofia", "soledad",
    "susana", "tamara", "valentina", "valeria", "vanesa", "vanina", "veronica", "victoria",
    "virginia", "viviana", "yamila", "yanina", "ximena", "zoe",
}

CABALLEROS = {
    "adrian", "agustin", "alan", "alberto", "alejandro", "alfredo", "alvaro", "andres", "angel",
    "antonio", "augusto", "axel", "benjamin", "bautista", "bruno", "carlos", "cesar", "claudio",
    "cristian", "damian", "daniel", "dario", "david", "diego", "eduardo", "emanuel", "emiliano",
    "enrique", "esteban", "ezequiel", "facundo", "fabian", "fausto", "federico", "felipe", "fernando",
    "francisco", "franco", "gabriel", "gaston", "german", "gerardo", "gonzalo", "guillermo",
    "gustavo", "hector", "hernan", "horacio", "hugo", "ignacio", "ivan", "javier", "jeronimo",
    "joaquin", "joel", "jorge", "jose", "josue", "juan", "julian", "julio", "leandro", "leonardo",
    "lisandro", "lorenzo", "lucas", "lucca", "luciano", "luis", "manuel", "marcelo", "marcos",
    "mariano", "mario", "martin", "mateo", "matias", "mauricio", "mauro", "maximiliano", "miguel",
    "nahuel", "nestor", "nicolas", "oscar", "pablo", "patricio", "pedro", "rafael", "ramiro", "raul",
    "renzo", "ricardo", "roberto", "rodrigo", "rolando", "ruben", "santiago", "santino", "sebastian",
    "sergio", "simon", "steven", "thiago", "tiago", "tomas", "valentino", "victor", "walter",
}

# nombres que en Argentina se usan para los dos: nunca cuentan
AMBIGUOS = {"andrea", "ariel", "cruz", "guadalupe", "rosario", "trinidad", "noel", "alex", "sasha", "angeles"}

MINIMO = 2        # nombres reconocidos para sugerir algo
MAYORIA = 0.8     # parte de un lado para sugerir esa rama


def _pila(nombre) -> str:
    partes = str(nombre or "").split()
    t = unicodedata.normalize("NFD", partes[0] if partes else "")
    return "".join(c for c in t if unicodedata.category(c) != "Mn").lower()


def rama_por_nombre(nombre) -> str | None:
    pila = _pila(nombre)
    if not pila or pila in AMBIGUOS:
        return None
    if pila in DAMAS:
        return "damas"
    if pila in CABALLEROS:
        return "caballeros"
    return None


def sugerir_rama(nombres) -> dict | None:
    """{"rama", "reconocidos", "total"} o None si no alcanza para sugerir."""
    nombres = list(nombres)
    ramas = [r for r in (rama_por_nombre(n) for n in nombres) if r]
    if len(ramas) < MINIMO:
        return None
    damas = ramas.count("damas")
    caballeros = len(ramas) - damas
    if damas / len(ramas) >= MAYORIA:
        rama = "damas"
    elif caballeros / len(ramas) >= MAYORIA:
        rama = "caballeros"
    elif damas >= 2 and caballeros >= 2:
        rama = "mixto"
    else:
        return None
    return {"rama": rama, "reconocidos": len(ramas), "total": len(nombres)}
