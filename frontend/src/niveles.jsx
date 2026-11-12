import { useState } from "react";
import "./niveles.css";

// Los colores salen de config_academia 'colores_rama' (por nivel y rama): el backend manda
// { columnas: [{ n, nombre, color, damas, caballeros }], por_rama: { damas: { "6TA": "#..." }, ... } }.

const capital = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1).toLowerCase() : "");
// "8VA" -> "8va", "PRINCIPIANTES" -> "Principiantes"
export const etiquetaNivel = (n) => (/^\d/.test(n) ? n.toLowerCase() : capital(n));
// ["7MA", "6TA"] -> "7ma-6ta"
export const rangoNivel = (lista) => (lista || []).map(etiquetaNivel).join("-");

export const RAMAS = { damas: "Damas", caballeros: "Caballeros", mixto: "Mixto" };

// color del punto de un alumno: su nivel en la tabla de su rama
export function colorAlumno(colores, rama, nivel) {
  return colores?.por_rama?.[rama]?.[nivel] || null;
}

// con color: punto lleno. Sin color pero con nivel (sin rama o mixta): punto hueco gris.
export function Punto({ color, hueco }) {
  if (color) return <span className="niv-punto" style={{ background: color }} />;
  return hueco ? <span className="niv-punto hueco" /> : null;
}

// Nivel de un alumno con selector de un toque.
// alumno: { nombre, nivel, nivel_declarado, clasificar, rama }. onElegir(nivel) devuelve una promesa.
// Si es nuevo, la marca y las opciones se ven de una; si no, se abren tocando el nivel.
export function NivelAlumno({ alumno, niveles, colores, onElegir }) {
  const [abierto, setAbierto] = useState(false);
  const [guardando, setGuardando] = useState("");
  const visible = alumno.clasificar || abierto;
  const color = (n) => colorAlumno(colores, alumno.rama, n);

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
          <Punto color={color(alumno.nivel)} hueco={!!alumno.nivel} />
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
              <Punto color={color(n)} hueco />
              {guardando === n ? "…" : etiquetaNivel(n)}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
