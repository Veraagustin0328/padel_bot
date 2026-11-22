import { useEffect, useState } from "react";
import { api } from "../api.js";
import { Formulario } from "./AltaAlumno.jsx";
import "./altaalumno.css";

// Editar un alumno desde Fichas (dueño y encargado): datos y contactos, y abajo dar de baja,
// reactivar o borrar. El back vuelve a chequear todo (permisos, historia, nombre escrito).

const MOTIVO = { horario: "Horario", lesion: "Lesión", precio: "Precio", mudanza: "Mudanza", otro: "Otro" };
const norm = (s) => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/\s+/g, " ").trim();

function Baja({ g, alumno, alHecho }) {
  const [abierta, setAbierta] = useState(false);
  const [motivo, setMotivo] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const [error, setError] = useState("");
  const deBaja = g.estado === "baja";

  async function hacer() {
    setOcupado(true);
    setError("");
    try {
      if (deBaja) await api(`/api/alumnos/${alumno.id}/reactivar`, { metodo: "POST" });
      else await api(`/api/alumnos/${alumno.id}/baja`, { metodo: "POST", cuerpo: { motivo: motivo || null } });
      alHecho(deBaja ? `Listo, ${alumno.nombre} volvió a estar activo. Anotalo en sus clases desde Clases.`
        : `Listo, ${alumno.nombre} quedó de baja.`);
    } catch (e) {
      setError(e.message);
      setOcupado(false);
    }
  }

  const n = g.baja.clases.length;
  return (
    <div className="edi-accion">
      <div className="edi-accion-cab">
        <div>
          <b>{deBaja ? "Está de baja" : "Dar de baja"}</b>
          <span className="nota">
            {deBaja
              ? `${g.motivo_baja ? `Motivo: ${MOTIVO[g.motivo_baja] || g.motivo_baja}. ` : ""}Reactivarlo no lo vuelve a anotar en sus clases.`
              : "Deja de ir a sus clases. Las cuotas, asistencias y faltas quedan guardadas."}
          </span>
        </div>
        {!abierta && (
          <button type="button" className="boton chico claro" onClick={() => setAbierta(true)}>
            {deBaja ? "Reactivar" : "Dar de baja"}
          </button>
        )}
      </div>
      {abierta && (
        <div className="edi-confirmar" role="alertdialog" aria-label={deBaja ? "Confirmar reactivar" : "Confirmar baja"}>
          {deBaja ? (
            <p>Vuelve a figurar como activo. <b>No se reinscribe</b>: sus clases las cargás a mano en Clases.</p>
          ) : (
            <>
              <p>
                {n === 0 ? "No está anotado en ninguna clase." : <>Se van a cerrar <b>{n} clase{n === 1 ? "" : "s"}</b> desde hoy:</>}
              </p>
              {n > 0 && <ul>{g.baja.clases.map((c, i) => <li key={i}>{c}</li>)}</ul>}
              {(g.baja.recuperaciones > 0 || g.baja.cambios_pendientes > 0) && (
                <p className="nota">
                  También se cancelan {[g.baja.recuperaciones && `${g.baja.recuperaciones} recuperación(es) que tenía por delante`,
                    g.baja.cambios_pendientes && `${g.baja.cambios_pendientes} cambio(s) de días pendiente(s)`].filter(Boolean).join(" y ")}.
                </p>
              )}
              <label className="edi-campo">
                Motivo (opcional)
                <select value={motivo} onChange={(e) => setMotivo(e.target.value)}>
                  <option value="">Sin motivo</option>
                  {g.motivos_baja.map((m) => <option key={m} value={m}>{MOTIVO[m] || m}</option>)}
                </select>
              </label>
            </>
          )}
          {error && <div className="msg-error" role="alert">{error}</div>}
          <div className="alta-pie">
            <button type="button" className={"boton" + (deBaja ? " principal" : " peligro")} disabled={ocupado} onClick={hacer}>
              {ocupado ? "Guardando…" : deBaja ? "Sí, reactivar" : "Sí, dar de baja"}
            </button>
            <button type="button" className="boton claro" disabled={ocupado} onClick={() => setAbierta(false)}>Cancelar</button>
          </div>
        </div>
      )}
    </div>
  );
}

function Borrar({ g, alumno, alHecho }) {
  const [abierta, setAbierta] = useState(false);
  const [escrito, setEscrito] = useState("");
  const [entiendo, setEntiendo] = useState(false);
  const [ocupado, setOcupado] = useState(false);
  const [error, setError] = useState("");
  const coincide = norm(escrito) === norm(alumno.nombre);

  async function borrar() {
    setOcupado(true);
    setError("");
    try {
      await api(`/api/alumnos/${alumno.id}`, { metodo: "DELETE", cuerpo: coincide ? { nombre: escrito } : { entiendo: true } });
      alHecho(`Borraste a ${alumno.nombre}.`, { borrado: true });
    } catch (e) {
      setError(e.message);
      setOcupado(false);
    }
  }

  return (
    <div className="edi-accion">
      <div className="edi-accion-cab">
        <div>
          <b>Borrar</b>
          <span className="nota">
            {g.puede_borrar
              ? "Solo para cargas por error: no tiene clases, cuotas, asistencias, faltas ni notas."
              : `No se puede: tiene ${g.no_borrar.join(", ")}. Si dejó, dalo de baja.`}
          </span>
        </div>
        {!abierta && (
          <button type="button" className="boton chico claro edi-borrar" disabled={!g.puede_borrar}
                  title={g.puede_borrar ? "" : "Tiene historia: dalo de baja"} onClick={() => setAbierta(true)}>
            Borrar
          </button>
        )}
      </div>
      {abierta && (
        <div className="edi-confirmar" role="alertdialog" aria-label="Confirmar borrado">
          <p>Se borra la ficha y sus teléfonos. <b>No se puede deshacer.</b></p>
          <label className="edi-campo">
            Escribí su nombre para confirmar
            <input value={escrito} autoComplete="off" placeholder={alumno.nombre} onChange={(e) => setEscrito(e.target.value)} />
          </label>
          <label className="alta-check">
            <input type="checkbox" checked={entiendo} onChange={(e) => setEntiendo(e.target.checked)} />
            <span>O tildá: entiendo que no se puede deshacer</span>
          </label>
          {error && <div className="msg-error" role="alert">{error}</div>}
          <div className="alta-pie">
            <button type="button" className="boton peligro" disabled={ocupado || !(coincide || entiendo)} onClick={borrar}>
              {ocupado ? "Borrando…" : "Borrar para siempre"}
            </button>
            <button type="button" className="boton claro" disabled={ocupado} onClick={() => setAbierta(false)}>Cancelar</button>
          </div>
        </div>
      )}
    </div>
  );
}

// alCerrar(mensaje, {borrado}): con mensaje si cambió algo (Fichas recarga y lo muestra)
export default function EditarAlumno({ alumno, alCerrar }) {
  const [opciones, setOpciones] = useState(null);
  const [g, setG] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([api("/api/alumnos/alta/opciones"), api(`/api/alumnos/${alumno.id}/gestion`)])
      .then(([o, x]) => { setOpciones(o); setG(x); })
      .catch((e) => setError(e.message));
  }, [alumno.id]);

  useEffect(() => {
    const tecla = (e) => e.key === "Escape" && alCerrar(null);
    window.addEventListener("keydown", tecla);
    const antes = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { window.removeEventListener("keydown", tecla); document.body.style.overflow = antes; };
  }, [alCerrar]);

  return (
    <div className="alta-velo">
      <div className="alta-hoja" role="dialog" aria-modal="true" aria-labelledby="edi-titulo">
        <div className="alta-cabecera">
          <h2 id="edi-titulo">Editar a {alumno.nombre}</h2>
          <button type="button" className="alta-cerrar" aria-label="Cerrar" onClick={() => alCerrar(null)}>×</button>
        </div>
        {error && <div className="msg-error" role="alert">{error}</div>}
        {!opciones && !error && <div className="cargando">Cargando…</div>}
        {opciones && g && (
          <>
            {g.estado === "baja" && <div className="edi-aviso-baja">De baja: no va a ninguna clase.</div>}
            <Formulario opciones={opciones} alumno={alumno} alCerrar={() => alCerrar(null)}
                        alGuardar={(r) => alCerrar(r.cambios?.length ? `Listo, guardé los cambios de ${alumno.nombre}.` : "No había nada para cambiar.")} />
            <section className="edi-cuidado" aria-label="Baja y borrado">
              <h3>Baja y borrado</h3>
              <Baja g={g} alumno={alumno} alHecho={alCerrar} />
              <Borrar g={g} alumno={alumno} alHecho={alCerrar} />
            </section>
          </>
        )}
      </div>
    </div>
  );
}
