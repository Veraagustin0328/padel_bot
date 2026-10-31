import { useEffect, useMemo, useState } from "react";
import { api } from "../api.js";
import "./clases.css";

const DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"];
const AMBITOS = { adultos: "Adultos mañana", adultos_tarde: "Adultos tarde", sabados: "Sábados" };
const TIPOS = { grupal: "Grupal", particular: "Particular", particular_2: "Particular de 2", otro: "Otro" };
const TIPO_CORTO = { grupal: "G", particular: "P", particular_2: "P2", otro: "Otro" };
const COLORES = { rojo: "#dc2626", verde: "#16a34a", amarillo: "#eab308", azul: "#2563eb", rosado: "#ec4899" };
const ORDEN_LEYENDA = ["rosado", "rojo", "verde", "amarillo", "azul"];
const ALIAS_NIVEL = { "1RA": "1ERA" };

const norm = (s) => String(s || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim();
const capital = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1).toLowerCase() : "");
// "8VA" -> "8va", "PRINCIPIANTES" -> "Principiantes"
const etiquetaNivel = (n) => (/^\d/.test(n) ? n.toLowerCase() : capital(n));

// el punto de color sale del primer nivel de la clase (ej. "6TA/7MA" -> 6TA)
function colorNivel(nivel, colores) {
  if (!nivel) return null;
  const primero = nivel.split("/")[0].trim().toUpperCase();
  const clave = ALIAS_NIVEL[primero] || primero;
  return COLORES[colores?.[clave]] || null;
}

function Punto({ nivel, colores }) {
  const color = colorNivel(nivel, colores);
  return color ? <span className="cla-punto" style={{ background: color }} /> : null;
}

function Leyenda({ colores }) {
  const grupos = {};
  for (const [nivel, color] of Object.entries(colores || {})) (grupos[color] ||= []).push(nivel);
  return (
    <div className="cla-leyenda">
      {ORDEN_LEYENDA.filter((c) => grupos[c]).map((c) => (
        <span key={c} className="cla-ley">
          <span className="cla-punto" style={{ background: COLORES[c] }} />
          {grupos[c].map(etiquetaNivel).join(" · ")}
        </span>
      ))}
      <span className="cla-ley"><span className="cla-muestra dudosa" />Tipo por confirmar</span>
      <span className="cla-ley"><span className="cla-muestra llena" />Cupo completo</span>
      <span className="cla-ley"><span className="cla-muestra pasada" />Más alumnos que cupo</span>
    </div>
  );
}

export default function Clases() {
  const [datos, setDatos] = useState(null);
  const [error, setError] = useState("");
  const [ambito, setAmbito] = useState("adultos");
  const [profe, setProfe] = useState("todos");
  const [buscar, setBuscar] = useState("");
  const [abierta, setAbierta] = useState(null);

  async function cargar() {
    setError("");
    try {
      setDatos(await api("/api/clases"));
    } catch (e) {
      setError(e.message);
      setDatos({ clases: [], colores_nivel: {} });
    }
  }
  useEffect(() => { cargar(); }, []);

  const clases = datos?.clases || [];
  const colores = datos?.colores_nivel || {};

  const ambitos = Object.keys(AMBITOS).filter((a) => clases.some((c) => c.ambito === a));
  const delAmbito = useMemo(() => clases.filter((c) => c.ambito === ambito), [clases, ambito]);
  const profes = useMemo(() => [...new Set(delAmbito.map((c) => c.profe).filter(Boolean))].sort(), [delAmbito]);
  const filtradas = useMemo(
    () => delAmbito.filter((c) => profe === "todos" || c.profe === profe),
    [delAmbito, profe]
  );

  const q = norm(buscar);
  const coincide = (c) => q.length >= 2 && c.alumnos.some((a) => norm(a.nombre).includes(q));
  const hayBusqueda = q.length >= 2;
  const aciertos = hayBusqueda ? filtradas.filter(coincide).length : 0;

  const dias = [...new Set(filtradas.map((c) => c.dia))].sort((a, b) => a - b);
  const horas = [...new Set(filtradas.map((c) => c.hora))].sort();
  const celdas = {};
  for (const c of filtradas) (celdas[c.dia + "|" + c.hora] ||= []).push(c);

  const alumnosUnicos = new Set(filtradas.flatMap((c) => c.alumnos.map((a) => a.id))).size;
  const porConfirmar = filtradas.filter((c) => c.estimado).length;
  const vacias = filtradas.filter((c) => c.alumnos.length === 0).length;

  const sel = clases.find((c) => c.id === abierta);

  return (
    <div>
      <h1>Clases</h1>
      <p style={{ color: "#5b6672" }}>El horario fijo de la academia. Por ahora es solo para mirar.</p>

      {error && <div className="cla-msg">{error}</div>}

      <div className="cla-tabs">
        {ambitos.map((a) => (
          <button
            key={a}
            className={"cla-tab" + (a === ambito ? " activo" : "")}
            onClick={() => { setAmbito(a); setProfe("todos"); setAbierta(null); }}
          >
            {AMBITOS[a]}
          </button>
        ))}
      </div>

      <div className="cla-resumen">
        <div className="cla-dato"><b>{filtradas.length}</b><span>Clases</span></div>
        <div className="cla-dato"><b>{alumnosUnicos}</b><span>Alumnos</span></div>
        <div className="cla-dato aviso"><b>{porConfirmar}</b><span>Tipo por confirmar</span></div>
        <div className="cla-dato"><b>{vacias}</b><span>Sin alumnos</span></div>
      </div>

      <div className="cla-filtros">
        <select value={profe} onChange={(e) => setProfe(e.target.value)}>
          <option value="todos">Todos los profes</option>
          {profes.map((p) => <option key={p} value={p}>{capital(p)}</option>)}
        </select>
        <input placeholder="Buscar un alumno…" value={buscar} onChange={(e) => setBuscar(e.target.value)} />
        {hayBusqueda && <span className="cla-hallazgo">{aciertos} {aciertos === 1 ? "clase" : "clases"}</span>}
        <button className="boton chico claro" onClick={cargar}>Actualizar</button>
      </div>

      <Leyenda colores={colores} />

      {datos === null ? (
        <div className="cargando">Cargando…</div>
      ) : filtradas.length === 0 ? (
        <div className="cla-vacio">No hay clases con esos filtros.</div>
      ) : (
        <div className="cla-cuerpo">
          <div className="cla-scroll">
            <table className="cla-grilla">
              <thead>
                <tr>
                  <th className="hora">Hora</th>
                  {dias.map((d) => <th key={d}>{DIAS[d]}</th>)}
                </tr>
              </thead>
              <tbody>
                {horas.map((h) => (
                  <tr key={h}>
                    <td className="hora">{h}</td>
                    {dias.map((d) => (
                      <td key={d}>
                        {(celdas[d + "|" + h] || []).map((c) => {
                          const n = c.alumnos.length;
                          const clase =
                            "cla-chip" +
                            (c.estimado ? " dudosa" : "") +
                            (n > c.cupo ? " pasada" : n === c.cupo ? " llena" : "") +
                            (c.id === abierta ? " abierta" : "") +
                            (hayBusqueda ? (coincide(c) ? " hit" : " opaco") : "");
                          return (
                            <button key={c.id} className={clase} onClick={() => setAbierta(c.id)}>
                              <span className="cla-arriba">
                                <Punto nivel={c.nivel} colores={colores} />
                                <b>{c.profe ? capital(c.profe) : "Sin profe"}</b>
                                <i>{TIPO_CORTO[c.tipo] || c.tipo}</i>
                              </span>
                              <span className="cla-abajo">{c.nivel || "—"} · {n}/{c.cupo}</span>
                            </button>
                          );
                        })}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {sel && (
            <aside className="cla-detalle">
              <button className="cla-cerrar" onClick={() => setAbierta(null)} aria-label="Cerrar">×</button>
              <h2>{DIAS[sel.dia]} {sel.hora}</h2>
              <p className="cla-sub">
                <Punto nivel={sel.nivel} colores={colores} />
                {sel.profe ? capital(sel.profe) : "Sin profe"} · {sel.nivel || "Sin nivel"}
              </p>
              <div className="cla-tags">
                <span className="cla-tag">{TIPOS[sel.tipo] || sel.tipo}</span>
                <span className="cla-tag">Cupo {sel.cupo}</span>
              </div>
              {sel.estimado && (
                <div className="cla-alerta">El tipo de clase se estimó por la cantidad de alumnos. Falta que Gabi lo confirme.</div>
              )}
              {sel.alumnos.length > sel.cupo && (
                <div className="cla-alerta">Hay más alumnos que cupo. Puede ser que la planilla tenga varias clases mezcladas.</div>
              )}
              {sel.nota && <div className="cla-nota"><b>Nota de la planilla:</b> {sel.nota}</div>}
              <h3>Alumnos ({sel.alumnos.length})</h3>
              {sel.alumnos.length === 0 ? (
                <p className="cla-sub">Nadie anotado todavía.</p>
              ) : (
                <ol className="cla-lista">
                  {sel.alumnos.map((a) => <li key={a.id}>{a.nombre}</li>)}
                </ol>
              )}
            </aside>
          )}
        </div>
      )}
    </div>
  );
}