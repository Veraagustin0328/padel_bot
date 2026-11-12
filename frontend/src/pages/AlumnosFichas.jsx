import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api.js";
import { NivelAlumno, etiquetaNivel } from "../niveles.jsx";

// fichas de los alumnos de Neon (no la planilla). Por ahora: contactos.
// la columna de acciones queda para sumar después "Cambiar días".

const norm = (s) => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();
const NOMBRE_PARENTESCO = { propio: "Propio (el alumno)", padre: "Padre", madre: "Madre", tutor: "Tutor/a" };
const corto = (p) => (p === "propio" ? "propio" : (NOMBRE_PARENTESCO[p] || p).toLowerCase());
const digitos = (s) => String(s || "").replace(/\D/g, "");

function FilaContacto({ c, i, alumnoId, parentescos, onCambio, onSacar }) {
  const [otros, setOtros] = useState([]);
  const ultimo = useRef("");

  // aviso si el número ya es de otro alumno (esperamos a que deje de tipear)
  useEffect(() => {
    const d = digitos(c.telefono);
    if (d.length < 10) { setOtros([]); return; }
    const t = setTimeout(async () => {
      ultimo.current = d;
      try {
        const r = await api(`/api/alumnos/contactos/chequear?telefono=${d}&alumno_id=${alumnoId}`);
        if (ultimo.current === d) setOtros(r.otros || []);
      } catch {
        setOtros([]);
      }
    }, 400);
    return () => clearTimeout(t);
  }, [c.telefono, alumnoId]);

  return (
    <div className="fic-contacto">
      <div className="fic-campos">
        <label>
          Teléfono {i + 1}
          <input inputMode="tel" placeholder="Ej. 3415551234" value={c.telefono}
                 onChange={(e) => onCambio({ ...c, telefono: e.target.value })} />
        </label>
        <label>
          Parentesco
          <select value={c.parentesco} onChange={(e) => onCambio({ ...c, parentesco: e.target.value })}>
            <option value="">Elegí…</option>
            {parentescos.map((p) => <option key={p} value={p}>{NOMBRE_PARENTESCO[p] || p}</option>)}
          </select>
        </label>
        <label>
          Nombre
          <input placeholder={c.parentesco === "propio" ? "Opcional" : "Ej. Laura"} value={c.nombre}
                 onChange={(e) => onCambio({ ...c, nombre: e.target.value })} />
        </label>
        <button type="button" className="boton chico claro fic-sacar" onClick={onSacar} aria-label={`Sacar teléfono ${i + 1}`}>
          Sacar
        </button>
      </div>
      {otros.length > 0 && (
        <div className="fic-aviso">
          Este número ya está cargado en {otros.map((o) => o.nombre).join(", ")}. Si son hermanos está bien, lo podés guardar igual.
        </div>
      )}
    </div>
  );
}

function ModalContactos({ alumno, max, parentescos, onCerrar, onGuardado }) {
  const [lista, setLista] = useState(() =>
    alumno.contactos.length
      ? alumno.contactos.map((c) => ({ telefono: c.telefono, parentesco: c.parentesco, nombre: c.nombre }))
      : [{ telefono: "", parentesco: "", nombre: "" }]
  );
  const [error, setError] = useState("");
  const [guardando, setGuardando] = useState(false);

  useEffect(() => {
    const tecla = (e) => e.key === "Escape" && !guardando && onCerrar();
    window.addEventListener("keydown", tecla);
    return () => window.removeEventListener("keydown", tecla);
  }, [guardando, onCerrar]);

  const cambiar = (i, c) => setLista((l) => l.map((x, j) => (j === i ? c : x)));
  const sacar = (i) => setLista((l) => l.filter((_, j) => j !== i));
  const sumar = () => setLista((l) => [...l, { telefono: "", parentesco: "", nombre: "" }]);

  async function guardar(e) {
    e.preventDefault();
    setError("");
    // las filas vacías del todo no cuentan
    const cargados = lista.filter((c) => c.telefono.trim() || c.nombre.trim() || c.parentesco);
    setGuardando(true);
    try {
      const r = await api(`/api/alumnos/${alumno.id}/contactos`, { metodo: "PUT", cuerpo: { contactos: cargados } });
      onGuardado(alumno.id, r.contactos);
    } catch (err) {
      setError(err.message);
      setGuardando(false);
    }
  }

  return (
    <div className="fic-velo" onMouseDown={(e) => e.target === e.currentTarget && !guardando && onCerrar()}>
      <form className="fic-modal" role="dialog" aria-modal="true" aria-labelledby="fic-titulo" onSubmit={guardar}>
        <h2 id="fic-titulo">Contactos de {alumno.nombre}</h2>
        <p className="fic-ayuda">
          Desde estos números el agente lo reconoce. Hasta {max} teléfono{max === 1 ? "" : "s"}.
        </p>

        {lista.map((c, i) => (
          <FilaContacto key={i} c={c} i={i} alumnoId={alumno.id} parentescos={parentescos}
                        onCambio={(nuevo) => cambiar(i, nuevo)} onSacar={() => sacar(i)} />
        ))}
        {lista.length === 0 && <div className="fic-ayuda">Sin teléfonos cargados.</div>}

        {lista.length < max && (
          <button type="button" className="boton chico claro" onClick={sumar}>+ Agregar teléfono</button>
        )}

        {error && <div className="alu-msg fic-error">{error}</div>}

        <div className="botones">
          <button className="boton" disabled={guardando}>{guardando ? "Guardando…" : "Guardar"}</button>
          <button type="button" className="boton claro" onClick={onCerrar} disabled={guardando}>Cancelar</button>
        </div>
      </form>
    </div>
  );
}

export default function AlumnosFichas() {
  const [datos, setDatos] = useState(null);
  const [error, setError] = useState("");
  const [buscar, setBuscar] = useState("");
  const [estado, setEstado] = useState("activo"); // activo | baja | todos
  const [abierto, setAbierto] = useState(null); // id del alumno con el modal abierto
  const [ok, setOk] = useState("");
  const [soloNuevos, setSoloNuevos] = useState(false); // filtro "A clasificar"

  async function cargar() {
    setError("");
    try {
      setDatos(await api("/api/alumnos/fichas"));
    } catch (e) {
      setError(e.message);
      setDatos({ alumnos: [], max_contactos: 2, parentescos: [] });
    }
  }
  useEffect(() => { cargar(); }, []);

  const lista = useMemo(() => {
    const q = norm(buscar);
    return (datos?.alumnos || []).filter((a) => {
      if (soloNuevos && !a.clasificar) return false;
      if (estado !== "todos" && norm(a.estado) !== estado) return false;
      if (q && !norm(a.nombre).includes(q)) return false;
      return true;
    });
  }, [datos, buscar, estado, soloNuevos]);

  const alumno = datos?.alumnos.find((a) => a.id === abierto);
  const aClasificar = (datos?.alumnos || []).filter((a) => a.clasificar).length;

  // clasificar o recategorizar desde la ficha
  async function elegirNivel(a, nivel) {
    setError("");
    setOk("");
    try {
      const r = await api(`/api/alumnos/${a.id}/nivel`, { metodo: "POST", cuerpo: { nivel } });
      setDatos((d) => ({
        ...d,
        alumnos: d.alumnos.map((x) => (x.id === a.id
          ? { ...x, categoria: r.nivel, nivel_declarado: r.nivel_declarado, clasificar: r.clasificar }
          : x)),
      }));
      setOk(`Listo, ${a.nombre} quedó en ${etiquetaNivel(r.nivel)}.`);
    } catch (e) {
      setError(`${a.nombre}: ${e.message}`);
      throw e;
    }
  }

  function guardado(id, contactos) {
    setDatos((d) => ({ ...d, alumnos: d.alumnos.map((a) => (a.id === id ? { ...a, contactos } : a)) }));
    const a = datos.alumnos.find((x) => x.id === id);
    setOk(`Listo, guardé los contactos de ${a?.nombre || "el alumno"}.`);
    setAbierto(null);
  }

  return (
    <div>
      <p style={{ color: "#5b6672" }}>Los alumnos que conoce el agente. Acá cargás los teléfonos de cada uno.</p>

      {error && <div className="alu-msg">{error}</div>}
      {ok && <div className="fic-ok" role="status">{ok}</div>}

      <div className="alu-filtros">
        <input placeholder="Buscar por nombre…" value={buscar} onChange={(e) => setBuscar(e.target.value)} />
        <select value={estado} onChange={(e) => setEstado(e.target.value)}>
          <option value="activo">Activos</option>
          <option value="baja">De baja</option>
          <option value="todos">Todos</option>
        </select>
        <button
          type="button"
          className={"fic-filtro-nuevos" + (soloNuevos ? " activo" : "")}
          aria-pressed={soloNuevos}
          onClick={() => setSoloNuevos(!soloNuevos)}
        >
          A clasificar <span className="fic-contador">{aClasificar}</span>
        </button>
        <button className="boton chico claro" onClick={cargar}>Actualizar</button>
      </div>

      {datos === null ? (
        <div className="cargando">Cargando…</div>
      ) : lista.length === 0 ? (
        <div className="alu-vacio">
          {soloNuevos ? "No hay alumnos nuevos para clasificar." : "No hay alumnos con esos filtros."}
        </div>
      ) : (
        <div className="alu-scroll">
          <table className="alu-tabla fic-tabla">
            <thead>
              <tr>
                <th className="nombre">Nombre</th>
                <th>Cat</th>
                <th>Planilla</th>
                <th>Contactos</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {lista.map((a) => (
                <tr key={a.id} className={norm(a.estado) === "baja" ? "baja" : ""}>
                  <td className="nombre">{a.nombre}</td>
                  <td className="fic-nivel">
                    <NivelAlumno alumno={{ ...a, nivel: a.categoria || "" }} niveles={datos.niveles}
                                 colores={datos.colores_nivel} onElegir={(n) => elegirNivel(a, n)} />
                  </td>
                  <td>{a.planilla}</td>
                  <td className="fic-tels">
                    {a.contactos.length === 0 ? (
                      <span className="fic-sin">Sin contactos</span>
                    ) : (
                      a.contactos.map((c) => (
                        <div key={c.id}>
                          {c.telefono} <span className="fic-par">({corto(c.parentesco)}{c.nombre ? `, ${c.nombre}` : ""})</span>
                        </div>
                      ))
                    )}
                  </td>
                  <td className="fic-acciones">
                    <button className="boton chico claro" onClick={() => { setOk(""); setAbierto(a.id); }}>Contactos</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {alumno && (
        <ModalContactos alumno={alumno} max={datos.max_contactos} parentescos={datos.parentescos}
                        onCerrar={() => setAbierto(null)} onGuardado={guardado} />
      )}
    </div>
  );
}
