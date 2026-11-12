import { useState } from "react";
import "./niveles.css";

// colores por nivel: los mismos de siempre de la pantalla Clases, ahora compartidos
export const COLORES = { rojo: "#dc2626", verde: "#16a34a", amarillo: "#eab308", azul: "#2563eb", rosado: "#ec4899" };
export const ORDEN_LEYENDA = ["rosado", "rojo", "verde", "amarillo", "azul"];
// la categoría del alumno viene como "principiante" o "1ra"; en la config está "PRINCIPIANTES" y "1ERA"
const ALIAS_NIVEL = { "1RA": "1ERA", PRINCIPIANTE: "PRINCIPIANTES" };

const capital = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1).toLowerCase() : "");
// "8VA" -> "8va", "PRINCIPIANTES" -> "Principiantes"
export const etiquetaNivel = (n) => (/^\d/.test(n) ? n.toLowerCase() : capital(n));

// el punto de color sale del primer nivel de la clase (ej. "6TA/7MA" -> 6TA)
export function colorNivel(nivel, colores) {
  if (!nivel) return null;
  const primero = nivel.split("/")[0].trim().toUpperCase();
  const clave = ALIAS_NIVEL[primero] || primero;
  return COLORES[colores?.[clave]] || null;
}

export function Punto({ nivel, colores }) {
  const color = colorNivel(nivel, colores);
  return color ? <span className="niv-punto" style={{ background: color }} /> : null;
}

// Nivel de un alumno con selector de un toque.
// alumno: { nombre, nivel, nivel_declarado, clasificar }. onElegir(nivel) devuelve una promesa.
// Si es nuevo, la marca y las opciones se ven de una; si no, se abren tocando el nivel.
export function NivelAlumno({ alumno, niveles, colores, onElegir }) {
  const [abierto, setAbierto] = useState(false);
  const [guardando, setGuardando] = useState("");
  const visible = alumno.clasificar || abierto;

  async function elegir(n) {
    if (guardando) return;
    setGuardando(n);
    try {
      await onElegir(n);
      setAbierto(false);
    } catch {
      // el error lo muestra la pantalla que llama
    } finally {
      setGuardando("");
    }
  }

  return (
    <div className="niv">
      {alumno.clasificar ? (
        <span className="niv-nuevo">
          Nuevo: clasificar nivel{alumno.nivel_declarado && ` · dijo ${etiquetaNivel(alumno.nivel_declarado)}`}
        </span>
      ) : (
        <button
          type="button"
          className="niv-actual"
          onClick={() => setAbierto(!abierto)}
          aria-expanded={abierto}
          aria-label={`Nivel de ${alumno.nombre}: ${alumno.nivel || "sin nivel"}. Tocá para cambiarlo`}
        >
          <Punto nivel={alumno.nivel} colores={colores} />
          {alumno.nivel ? etiquetaNivel(alumno.nivel) : "Sin nivel"}
          <span className="niv-lapiz" aria-hidden="true">✎</span>
        </button>
      )}
      {visible && (
        <div className="niv-opciones" role="group" aria-label={`Elegí el nivel de ${alumno.nombre}`}>
          {(niveles || []).map((n) => (
            <button
              key={n}
              type="button"
              className={"niv-opcion" + (n === alumno.nivel && !alumno.clasificar ? " activo" : "")}
              aria-pressed={n === alumno.nivel && !alumno.clasificar}
              disabled={!!guardando}
              onClick={() => elegir(n)}
            >
              <Punto nivel={n} colores={colores} />
              {guardando === n ? "…" : etiquetaNivel(n)}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
