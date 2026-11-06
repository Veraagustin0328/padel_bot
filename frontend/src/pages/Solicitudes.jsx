import { useEffect, useState } from "react";
import { api } from "../api.js";

const NOMBRE_ROL = { encargado: "Encargado", profe: "Profe", jugador: "Jugador", tutor: "Tutor" };

// avisa al menú que cambió la cantidad de pendientes
const avisarMenu = () => window.dispatchEvent(new Event("solicitudes-cambiaron"));

export default function Solicitudes() {
  const [lista, setLista] = useState(null);
  const [opciones, setOpciones] = useState({ roles: [], profesores: [], alumnos: [] });
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

  const form = (s) => forms[s.id] || { rol: "", vinculo: "" };
  const cambiar = (s, campo, v) => {
    const f = { ...form(s), [campo]: v };
    if (campo === "rol") f.vinculo = ""; // al cambiar de rol el vínculo viejo no sirve
    setForms({ ...forms, [s.id]: f });
  };

  async function resolver(s, accion) {
    setError(""); setAviso("");
    const f = form(s);
    let cuerpo;
    if (accion === "aprobar") {
      if (!f.rol) return setError(`Elegí un rol para ${s.nombre}`);
      if (f.rol === "profe" && !f.vinculo) return setError(`Para un profe tenés que elegir a qué profesor corresponde`);
      cuerpo = { rol: f.rol };
      if (f.rol === "profe") cuerpo.profesor_id = Number(f.vinculo);
      if ((f.rol === "jugador" || f.rol === "tutor") && f.vinculo) cuerpo.alumno_id = Number(f.vinculo);
    } else if (!window.confirm(`¿Rechazar la solicitud de ${s.nombre}?`)) {
      return;
    }
    setOcupado(s.id);
    try {
      await api(`/api/solicitudes/${s.id}/${accion}`, { metodo: "POST", cuerpo });
      setAviso(accion === "aprobar" ? `${s.nombre} ya puede entrar como ${NOMBRE_ROL[f.rol].toLowerCase()}` : `Rechazaste a ${s.nombre}`);
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
          const vinculos = f.rol === "profe" ? opciones.profesores : (f.rol === "jugador" || f.rol === "tutor") ? opciones.alumnos : null;
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
                    {opciones.roles.map((r) => <option key={r} value={r}>{NOMBRE_ROL[r] || r}</option>)}
                  </select>
                </div>
                {vinculos && (
                  <div className="campo">
                    <label htmlFor={`vin-${s.id}`}>{f.rol === "profe" ? "Profesor (obligatorio)" : "Alumno (opcional)"}</label>
                    <select id={`vin-${s.id}`} value={f.vinculo} onChange={(e) => cambiar(s, "vinculo", e.target.value)}>
                      <option value="">{f.rol === "profe" ? "Elegí…" : "Sin vincular"}</option>
                      {vinculos.map((v) => <option key={v.id} value={v.id}>{v.nombre}</option>)}
                    </select>
                  </div>
                )}
              </div>
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
