import { useEffect, useState } from "react";
import { api } from "../api.js";
import { nombreRol } from "../roles.js";

// avisa al menú que cambió la cantidad de pendientes
const avisarMenu = () => window.dispatchEvent(new Event("solicitudes-cambiaron"));
// qué vínculos lleva cada rol: alumno propio (juega) y/o hijos (padre/tutor)
const CON_PROPIO = ["jugador", "jugador_tutor"];
const CON_HIJOS = ["tutor", "jugador_tutor"];
const NOMBRE_PARENTESCO = { padre: "Padre", madre: "Madre", tutor: "Tutor/a" };

export default function Solicitudes() {
  const [lista, setLista] = useState(null);
  const [opciones, setOpciones] = useState({ roles: [], profesores: [], alumnos: [], parentescos: [] });
  const [forms, setForms] = useState({});
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");
  const [ocupado, setOcupado] = useState(null);

  async function cargar() {
    try {
      setLista(await api("/api/solicitudes"));
    } catch (e) {
      setError(e.message);
      setLista([]);
    }
  }
  useEffect(() => {
    cargar();
    api("/api/solicitudes/opciones").then(setOpciones).catch((e) => setError(e.message));
  }, []);

  const form = (s) => forms[s.id] || { rol: "", vinculo: "", hijos: [], parentesco: "padre" };
  const cambiar = (s, campo, v) => {
    const f = { ...form(s), [campo]: v };
    if (campo === "rol") { f.vinculo = ""; f.hijos = []; } // al cambiar de rol el vínculo viejo no sirve
    setForms({ ...forms, [s.id]: f });
  };
  const sumarHijo = (s, id) => {
    const f = form(s);
    if (id && !f.hijos.includes(id)) cambiar(s, "hijos", [...f.hijos, id]);
  };
  const nombreAlumno = (id) => opciones.alumnos.find((a) => String(a.id) === String(id))?.nombre || `#${id}`;

  async function resolver(s, accion) {
    setError(""); setAviso("");
    const f = form(s);
    let cuerpo;
    if (accion === "aprobar") {
      if (!f.rol) return setError(`Elegí un rol para ${s.nombre}`);
      if (f.rol === "profe" && !f.vinculo) return setError(`Para un profe tenés que elegir a qué profesor corresponde`);
      cuerpo = { rol: f.rol };
      if (f.rol === "profe") cuerpo.profesor_id = Number(f.vinculo);
      if (CON_PROPIO.includes(f.rol) && f.vinculo) cuerpo.alumno_id = Number(f.vinculo);
      if (CON_HIJOS.includes(f.rol) && f.hijos.length) {
        cuerpo.hijos = f.hijos.map(Number);
        cuerpo.parentesco = f.parentesco;
      }
    } else if (!window.confirm(`¿Rechazar la solicitud de ${s.nombre}?`)) {
      return;
    }
    setOcupado(s.id);
    try {
      await api(`/api/solicitudes/${s.id}/${accion}`, { metodo: "POST", cuerpo });
      setAviso(accion === "aprobar" ? `${s.nombre} ya puede entrar como ${nombreRol(f.rol).toLowerCase()}` : `Rechazaste a ${s.nombre}`);
      await cargar();
      avisarMenu();
    } catch (e) {
      setError(e.message);
    } finally {
      setOcupado(null);
    }
  }

  return (
    <div>
      <div className="cabecera">
        <h1>Solicitudes</h1>
        <p className="sub">Gente que pidió cuenta por el link de registro.</p>
      </div>
      {error && <div className="msg-error" role="alert">{error}</div>}
      {aviso && <div className="msg-ok" role="status">{aviso}</div>}

      {lista === null && <p>Cargando…</p>}
      {lista && lista.length === 0 && <div className="tarjeta">No hay solicitudes pendientes 👌</div>}

      <div className="solicitudes">
        {(lista || []).map((s) => {
          const f = form(s);
          const vinculos = f.rol === "profe" ? opciones.profesores : CON_PROPIO.includes(f.rol) ? opciones.alumnos : null;
          const conHijos = CON_HIJOS.includes(f.rol);
          return (
            <div key={s.id} className="tarjeta solicitud">
              <div>
                <strong>{s.nombre}</strong>
                <div className="sub">{s.email}</div>
                {s.creado_en && <div className="sub">Pidió el {new Date(s.creado_en).toLocaleDateString("es-AR")}</div>}
              </div>
              <div className="campos">
                <div className="campo">
                  <label htmlFor={`rol-${s.id}`}>Rol</label>
                  <select id={`rol-${s.id}`} value={f.rol} onChange={(e) => cambiar(s, "rol", e.target.value)}>
                    <option value="">Elegí…</option>
                    {opciones.roles.map((r) => <option key={r} value={r}>{nombreRol(r)}</option>)}
                  </select>
                </div>
                {vinculos && (
                  <div className="campo">
                    <label htmlFor={`vin-${s.id}`}>{f.rol === "profe" ? "Profesor (obligatorio)" : "Su alumno, si juega (opcional)"}</label>
                    <select id={`vin-${s.id}`} value={f.vinculo} onChange={(e) => cambiar(s, "vinculo", e.target.value)}>
                      <option value="">{f.rol === "profe" ? "Elegí…" : "Sin vincular"}</option>
                      {vinculos.map((v) => <option key={v.id} value={v.id}>{v.nombre}</option>)}
                    </select>
                  </div>
                )}
                {conHijos && (
                  <>
                    <div className="campo">
                      <label htmlFor={`hijo-${s.id}`}>Hijos (opcional, puede ser más de uno)</label>
                      <select id={`hijo-${s.id}`} value="" onChange={(e) => sumarHijo(s, e.target.value)}>
                        <option value="">Agregar hijo…</option>
                        {opciones.alumnos
                          .filter((a) => !f.hijos.includes(String(a.id)) && String(a.id) !== String(f.vinculo))
                          .map((a) => <option key={a.id} value={a.id}>{a.nombre}</option>)}
                      </select>
                    </div>
                    <div className="campo">
                      <label htmlFor={`par-${s.id}`}>Es su…</label>
                      <select id={`par-${s.id}`} value={f.parentesco} onChange={(e) => cambiar(s, "parentesco", e.target.value)}>
                        {(opciones.parentescos || []).map((p) => <option key={p} value={p}>{NOMBRE_PARENTESCO[p] || p}</option>)}
                      </select>
                    </div>
                  </>
                )}
              </div>
              {conHijos && f.hijos.length > 0 && (
                <div className="sub" style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 12 }}>
                  {f.hijos.map((h) => (
                    <span key={h} className="chip">
                      {nombreAlumno(h)}{" "}
                      <button type="button" className="boton chico claro" aria-label={`Sacar a ${nombreAlumno(h)}`}
                        onClick={() => cambiar(s, "hijos", f.hijos.filter((x) => x !== h))}>×</button>
                    </span>
                  ))}
                </div>
              )}
              <div className="botones">
                <button className="boton" disabled={ocupado === s.id} onClick={() => resolver(s, "aprobar")}>Aprobar</button>
                <button className="boton claro" disabled={ocupado === s.id} onClick={() => resolver(s, "rechazar")}>Rechazar</button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
