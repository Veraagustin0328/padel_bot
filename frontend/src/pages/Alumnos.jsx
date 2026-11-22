import { useEffect, useMemo, useState } from "react";
import { ahora } from "../fechas.js";
import { api } from "../api.js";
import AlumnosFichas from "./AlumnosFichas.jsx";
import AltaAlumno from "./AltaAlumno.jsx";
import ScrollLateral from "../ScrollLateral.jsx";
import "./alumnos.css";

const MESES = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"];
const peso = new Intl.NumberFormat("es-AR", { style: "currency", currency: "ARS", maximumFractionDigits: 0 });
const norm = (s) => String(s || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim();
const capital = (s) => s.charAt(0) + s.slice(1).toLowerCase();
// función y no constante: se calcula al dibujar, ya con la fecha del server si es simulación
const mesActual = () => MESES[ahora().getMonth()];

function Celda({ m }) {
  if (m && "pago" in m) return m.pago ? <td className="num">Pagó</td> : <td />; // encargado: sin montos
  if (!m || !m.texto) return <td />;
  if (m.monto !== null && m.monto >= 1000) return <td className="num">{peso.format(m.monto)}</td>;
  if (m.monto === 0) return <td className="num cero">$ 0</td>;
  return <td className="num raro">{m.texto}</td>;
}

// la de siempre: el listado de la planilla, solo para mirar
function ListadoPlanilla({ accion = null }) {
  const [datos, setDatos] = useState(null);
  const [error, setError] = useState("");
  const [buscar, setBuscar] = useState("");
  const [aldia, setAldia] = useState("todos"); // todos | aldia | debe
  const [estado, setEstado] = useState("activo"); // activo | baja | todos
  const [planillaSel, setPlanillaSel] = useState("todas");

  // fresco: "Actualizar" lee la planilla de nuevo (si no, el back puede usar una copia de hasta 90 s)
  async function cargar(fresco = false) {
    setError("");
    try {
      setDatos(await api("/api/alumnos" + (fresco ? "?fresco=1" : "")));
    } catch (e) {
      setError(e.message);
      setDatos([]);
    }
  }
  useEffect(() => { cargar(); }, []);

  const planillas = useMemo(
    () => [...new Set((datos || []).map((a) => a.planilla).filter(Boolean))].sort(),
    [datos]
  );

  // todo menos el filtro de "al día", así los contadores no se pisan
  const base = useMemo(() => {
    const q = norm(buscar);
    return (datos || []).filter((a) => {
      const est = norm(a.estado) || "activo";
      if (estado !== "todos" && est !== estado) return false;
      if (planillaSel !== "todas" && a.planilla !== planillaSel) return false;
      if (q && !norm(a.nombre).includes(q)) return false;
      return true;
    });
  }, [datos, buscar, estado, planillaSel]);

  const esAlDia = (a) => norm(a.al_dia) === "al dia";
  const esDebe = (a) => norm(a.al_dia) === "debe";
  const cuentaAlDia = base.filter(esAlDia).length;
  const cuentaDebe = base.filter(esDebe).length;

  const lista = base.filter((a) => (aldia === "aldia" ? esAlDia(a) : aldia === "debe" ? esDebe(a) : true));

  // solo muestro los meses que tienen algo cargado
  const meses = MESES.filter((m) => base.some((a) => a.meses[m]?.texto || a.meses[m]?.pago));

  return (
    <div>
      <p style={{ color: "#5b6672" }}>Igual que tu listado de la planilla. Por ahora es solo para mirar.</p>

      {error && <div className="alu-msg">{error}</div>}

      <div className="alu-resumen">
        <button className={"alu-dato" + (aldia === "todos" ? " activo" : "")} onClick={() => setAldia("todos")}>
          <b>{base.length}</b><span>Alumnos</span>
        </button>
        <button className={"alu-dato ok" + (aldia === "aldia" ? " activo" : "")} onClick={() => setAldia("aldia")}>
          <b>{cuentaAlDia}</b><span>Al día</span>
        </button>
        <button className={"alu-dato debe" + (aldia === "debe" ? " activo" : "")} onClick={() => setAldia("debe")}>
          <b>{cuentaDebe}</b><span>Deben</span>
        </button>
      </div>

      <div className="alu-filtros">
        <input placeholder="Buscar por nombre…" value={buscar} onChange={(e) => setBuscar(e.target.value)} />
        <select value={estado} onChange={(e) => setEstado(e.target.value)}>
          <option value="activo">Activos</option>
          <option value="baja">De baja</option>
          <option value="todos">Todos</option>
        </select>
        <select value={planillaSel} onChange={(e) => setPlanillaSel(e.target.value)}>
          <option value="todas">Todas las planillas</option>
          {planillas.map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
        <button className="boton chico claro" onClick={() => cargar(true)}>Actualizar</button>
        {accion}
      </div>

      {datos === null ? (
        <div className="cargando">Cargando…</div>
      ) : lista.length === 0 ? (
        <div className="alu-vacio">No hay alumnos con esos filtros.</div>
      ) : (
        <ScrollLateral className="alu-scroll">
          <table className="alu-tabla">
            <thead>
              <tr>
                <th>N°</th>
                <th className="nombre">Nombre</th>
                <th>Cat</th>
                <th>Planilla</th>
                <th>Estado</th>
                <th>Al día</th>
                {meses.map((m) => (
                  <th key={m} className={m === mesActual() ? "actual" : ""}>{capital(m)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {lista.map((a) => (
                <tr key={a.id} className={norm(a.estado) === "baja" ? "baja" : ""}>
                  <td>{a.numero}</td>
                  <td className="nombre">{a.nombre}</td>
                  <td>{a.cat}</td>
                  <td>{a.planilla}</td>
                  <td>{a.estado}{a.mes_baja ? ` (${capital(a.mes_baja)})` : ""}</td>
                  <td>
                    <span className={"alu-badge " + (esAlDia(a) ? "ok" : esDebe(a) ? "debe" : "nada")}>
                      {a.al_dia || "—"}
                    </span>
                  </td>
                  {meses.map((m) => <Celda key={m} m={a.meses[m]} />)}
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollLateral>
      )}
    </div>
  );
}

const SOLAPAS = [
  { clave: "planilla", t: "Planilla" },
  { clave: "fichas", t: "Fichas" },
];

export default function Alumnos() {
  const [solapa, setSolapa] = useState("planilla");
  const [alta, setAlta] = useState(false);
  const [vuelta, setVuelta] = useState(0); // para recargar las fichas después de un alta

  function cerrarAlta(huboCambios) {
    setAlta(false);
    if (huboCambios) {
      // el nuevo está en Fichas (la planilla de Google no se toca)
      setSolapa("fichas");
      setVuelta((v) => v + 1);
    }
  }

  // a la derecha, en la fila del buscador y "Actualizar" (en celu, una celda más de la grilla)
  const nuevo = <button className="boton chico alu-nuevo" onClick={() => setAlta(true)}>+ Nuevo alumno</button>;

  return (
    <div>
      <h1 className="alu-titulo">Alumnos</h1>
      <div className="alu-solapas" role="tablist" aria-label="Alumnos">
        {SOLAPAS.map((s) => (
          <button key={s.clave} role="tab" aria-selected={solapa === s.clave}
                  className={"alu-solapa" + (solapa === s.clave ? " activo" : "")} onClick={() => setSolapa(s.clave)}>
            {s.t}
          </button>
        ))}
      </div>
      {solapa === "planilla" ? <ListadoPlanilla accion={nuevo} /> : <AlumnosFichas key={vuelta} accion={nuevo} />}
      {alta && <AltaAlumno alCerrar={cerrarAlta} />}
    </div>
  );
}
