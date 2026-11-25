import { useEffect, useMemo, useState } from "react";
import { api } from "../api.js";
import { NivelAlumno, etiquetaNivel } from "../niveles.jsx";
import ScrollLateral from "../ScrollLateral.jsx";
import { ThNombre, ordenarPorNombre } from "../orden.jsx";
import EditarAlumno from "./EditarAlumno.jsx";

// fichas de los alumnos de Neon (no la planilla): nivel, contactos y Tarifa Head Coach.
// "Editar" abre la ficha completa: datos, contactos, baja, reactivar y borrar.

const norm = (s) => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();
const NOMBRE_PARENTESCO = { propio: "Propio (el alumno)", padre: "Padre", madre: "Madre", tutor: "Tutor/a" };
const corto = (p) => (p === "propio" ? "propio" : (NOMBRE_PARENTESCO[p] || p).toLowerCase());

// accion: el botón "Nuevo alumno", que va en la misma fila que los filtros
export default function AlumnosFichas({ accion = null }) {
  const [datos, setDatos] = useState(null);
  const [error, setError] = useState("");
  const [buscar, setBuscar] = useState("");
  const [estado, setEstado] = useState("activo"); // activo | baja | todos
  const [abierto, setAbierto] = useState(null); // id del alumno que se está editando
  const [ok, setOk] = useState("");
  const [soloNuevos, setSoloNuevos] = useState(false); // filtro "A clasificar"
  const [soloSinTel, setSoloSinTel] = useState(false); // filtro "Sin teléfono"
  const [guardandoHC, setGuardandoHC] = useState(null); // id del alumno que se está guardando
  const [sentido, setSentido] = useState(1); // 1 = A–Z, -1 = Z–A (clic en "Nombre")

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
    const filtrados = (datos?.alumnos || []).filter((a) => {
      if (soloNuevos && !a.clasificar) return false;
      if (soloSinTel && !a.sin_telefono) return false;
      if (estado !== "todos" && norm(a.estado) !== estado) return false;
      if (q && !norm(a.nombre).includes(q)) return false;
      return true;
    });
    return ordenarPorNombre(filtrados, sentido);
  }, [datos, buscar, estado, soloNuevos, soloSinTel, sentido]);

  const alumno = datos?.alumnos.find((a) => a.id === abierto);
  const aClasificar = (datos?.alumnos || []).filter((a) => a.clasificar).length;
  // los de baja no cuentan: no hace falta salir a buscarles el teléfono
  const sinTel = (datos?.alumnos || []).filter((a) => a.sin_telefono && norm(a.estado) !== "baja").length;

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

  // casilla Tarifa Head Coach: solo para los nuevos que pidieron con el head coach
  async function cambiarHC(a, valor) {
    setError("");
    setOk("");
    setGuardandoHC(a.id);
    // se tilda al toque; si el guardado falla, vuelve como estaba
    const poner = (v) => setDatos((d) => ({
      ...d,
      alumnos: d.alumnos.map((x) => (x.id === a.id ? { ...x, tarifa_head_coach: v } : x)),
    }));
    poner(valor);
    try {
      const r = await api(`/api/alumnos/${a.id}/tarifa-head-coach`, { metodo: "POST", cuerpo: { valor } });
      poner(r.tarifa_head_coach);
      setOk(r.tarifa_head_coach
        ? `Listo, ${a.nombre} paga tarifa Head Coach en sus particulares con el Head Coach.`
        : `Listo, ${a.nombre} paga la particular normal.`);
    } catch (e) {
      poner(!valor);
      setError(`${a.nombre}: no se guardó la tarifa Head Coach. ${e.message}`);
    } finally {
      setGuardandoHC(null);
    }
  }

  // al cerrar la edición: si cambió algo, aviso y vuelvo a traer la lista
  function cerrarEdicion(mensaje, { borrado = false } = {}) {
    const id = abierto;
    setAbierto(null);
    // el borrado sale de la lista al toque, sin esperar la recarga
    if (borrado) setDatos((d) => ({ ...d, alumnos: d.alumnos.filter((a) => a.id !== id) }));
    if (mensaje) {
      setOk(mensaje);
      cargar();
    }
  }

  return (
    <div>

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
        <button
          type="button"
          className={"fic-filtro-nuevos fic-filtro-sintel" + (soloSinTel ? " activo" : "")}
          aria-pressed={soloSinTel}
          onClick={() => setSoloSinTel(!soloSinTel)}
        >
          Sin teléfono <span className="fic-contador">{sinTel}</span>
        </button>
        <button className="boton chico claro" onClick={cargar}>Actualizar</button>
        {accion}
      </div>

      {datos === null ? (
        <div className="cargando">Cargando…</div>
      ) : lista.length === 0 ? (
        <div className="alu-vacio">
          {soloNuevos && !soloSinTel ? "No hay alumnos nuevos para clasificar."
            : soloSinTel && !soloNuevos && !buscar ? "Todos tienen teléfono cargado 👌" : "No hay alumnos con esos filtros."}
        </div>
      ) : (
        <ScrollLateral className="alu-scroll">
          <table className="alu-tabla fic-tabla">
            <thead>
              <tr>
                <ThNombre sentido={sentido} alCambiar={setSentido} />
                <th>Cat</th>
                <th>Planilla</th>
                <th>Contactos</th>
                {datos.hay_head_coach && <th className="fic-hc" title="Solo alumnos nuevos que pidieron con el Head Coach">Tarifa Head Coach</th>}
                <th></th>
              </tr>
            </thead>
            <tbody>
              {lista.map((a) => (
                <tr key={a.id} className={norm(a.estado) === "baja" ? "baja" : ""}>
                  <td className="nombre">
                    {a.nombre}
                    {norm(a.estado) === "baja" && <span className="fic-baja">de baja</span>}
                    {a.sin_telefono && <span className="fic-sintel" title="No se puede vincular hasta que se cargue: Editar">Sin teléfono</span>}
                  </td>
                  <td className="fic-nivel">
                    <NivelAlumno alumno={{ ...a, nivel: a.categoria || "" }} niveles={datos.niveles}
                                 colores={datos.colores} onElegir={(n) => elegirNivel(a, n)} />
                  </td>
                  <td>{a.planilla}</td>
                  <td className="fic-tels">
                    {a.contactos.length === 0 ? (
                      <span className="fic-sin">{a.sin_telefono ? "Cargalo desde Editar" : "Sin contactos"}</span>
                    ) : (
                      a.contactos.map((c) => (
                        <div key={c.id}>
                          {c.telefono} <span className="fic-par">({corto(c.parentesco)}{c.nombre ? `, ${c.nombre}` : ""})</span>
                        </div>
                      ))
                    )}
                  </td>
                  {datos.hay_head_coach && (
                    <td className="fic-hc">
                      <label title="Solo alumnos nuevos que pidieron con el Head Coach">
                        <input type="checkbox" checked={!!a.tarifa_head_coach} disabled={guardandoHC === a.id}
                               aria-label={`Tarifa Head Coach para ${a.nombre}`}
                               onChange={(e) => cambiarHC(a, e.target.checked)} />
                      </label>
                    </td>
                  )}
                  <td className="fic-acciones">
                    <button className="boton chico claro" onClick={() => { setOk(""); setAbierto(a.id); }}>Editar</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollLateral>
      )}

      {alumno && <EditarAlumno alumno={alumno} alCerrar={cerrarEdicion} />}
    </div>
  );
}
