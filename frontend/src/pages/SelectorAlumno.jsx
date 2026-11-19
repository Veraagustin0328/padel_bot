import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

// el último elegido se recuerda en este navegador (si el storage falla, arranca en el propio)
const CLAVE = "alumno-elegido";

function leerGuardado() {
  try {
    return Number(localStorage.getItem(CLAVE)) || null;
  } catch {
    return null;
  }
}

function guardar(id) {
  try {
    localStorage.setItem(CLAVE, String(id));
  } catch {
    /* modo privado o storage bloqueado: no pasa nada */
  }
}

// cuál alumno se está mirando: el de la URL (?a=12), si no el último elegido, si no el primero
// (el propio, que /api/yo/alumnos manda primero). Solo vale un id que esté en la lista.
export function useAlumnoElegido(alumnos) {
  const [params, setParams] = useSearchParams();
  const [id, setId] = useState(null);

  useEffect(() => {
    if (!alumnos || alumnos.length === 0) return;
    const validos = new Set(alumnos.map((a) => a.id));
    const deUrl = Number(params.get("a")) || null;
    const elegido = [deUrl, leerGuardado()].find((x) => x && validos.has(x)) || alumnos[0].id;
    setId(elegido);
  }, [alumnos, params]);

  const elegir = (nuevo) => {
    guardar(nuevo);
    setId(nuevo);
    // replace: cambiar de chico no llena el historial del botón Atrás
    setParams((p) => {
      const q = new URLSearchParams(p);
      q.set("a", String(nuevo));
      return q;
    }, { replace: true });
  };

  return [id, elegir];
}

// "Yo" para lo propio; para un hijo el nombre de pila, o dos palabras si se repite entre los chips
function etiquetas(alumnos) {
  const pila = (a) => a.nombre.split(" ")[0];
  const cuantos = {};
  alumnos.forEach((a) => { cuantos[pila(a)] = (cuantos[pila(a)] || 0) + 1; });
  return Object.fromEntries(alumnos.map((a) => [a.id,
    a.vinculo === "propio" ? "Yo" : cuantos[pila(a)] > 1 ? a.nombre.split(" ").slice(0, 2).join(" ") : pila(a)]));
}

// chips arriba de todo. Con un solo alumno no se muestra
export default function SelectorAlumno({ alumnos, elegido, onElegir }) {
  if (!alumnos || alumnos.length < 2) return null;
  const nombres = etiquetas(alumnos);
  return (
    <div className="alu-selector" role="radiogroup" aria-label="A quién estás viendo">
      {alumnos.map((a) => {
        const activo = a.id === elegido;
        return (
          <button key={a.id} type="button" role="radio" aria-checked={activo}
            className={"alu-chip" + (activo ? " activo" : "")} onClick={() => onElegir(a.id)}>
            {nombres[a.id]}
          </button>
        );
      })}
    </div>
  );
}
