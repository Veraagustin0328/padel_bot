import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api.js";
import { NivelAlumno, Punto, RAMAS, etiquetaNivel, rangoNivel } from "../niveles.jsx";
import "./clases.css";

const DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"];
const AMBITOS = { adultos: "Adultos mañana", adultos_tarde: "Adultos tarde", sabados: "Sábados" };
const TIPOS = { grupal: "Grupal", particular: "Particular", particular_2: "Particular de 2", otro: "Otro" };
const TIPO_CORTO = { grupal: "G", particular: "P", particular_2: "P2", otro: "Otro" };

const norm = (s) => String(s || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim();
const capital = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1).toLowerCase() : "");
// punto y etiqueta del nivel viven en ../niveles.jsx (los comparten Mis clases y Fichas)

// una columna de la tabla en texto: "Cab. 7ma-6ta · Damas 6ta"
const textoColumna = (col) =>
  [col.caballeros.length && `Cab. ${rangoNivel(col.caballeros)}`, col.damas.length && `Damas ${rangoNivel(col.damas)}`]
    .filter(Boolean).join(" · ");

function Leyenda({ colores, sinRama }) {
  return (
    <div className="cla-leyenda">
      {(colores?.columnas || []).map((col) => (
        <span key={col.n} className="cla-ley">
          <Punto color={col.color} />
          {textoColumna(col)}
        </span>
      ))}
      <span className="cla-ley">
        <Punto hueco />Sin rama o mixta{sinRama > 0 && ` (${sinRama} grupales sin rama)`}
      </span>
      <span className="cla-ley"><span className="cla-muestra dudosa" />Tipo por confirmar</span>
      <span className="cla-ley"><span className="cla-muestra llena" />Cupo completo</span>
      <span className="cla-ley"><span className="cla-muestra pasada" />Más alumnos que cupo</span>
    </div>
  );
}

export default function Clases() {
  const [datos, setDatos] = useState(null);
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");
  const [ambito, setAmbito] = useState("adultos");
  const [profe, setProfe] = useState("todos");
  const [buscar, setBuscar] = useState("");
  const [abierta, setAbierta] = useState(null);
  const [verInactivas, setVerInactivas] = useState(false);
  const [listaProfes, setListaProfes] = useState([]);
  const [form, setForm] = useState(null);
  const [qAlu, setQAlu] = useState("");
  const [resultados, setResultados] = useState([]);
  const [ocupado, setOcupado] = useState(""); // qué botón está esperando ("" = ninguno)
  const enCurso = useRef(false); // candado contra el doble click

  async function cargar() {
    try {
      setDatos(await api("/api/clases"));
    } catch (e) {
      setError(e.message);
      setDatos({ clases: [], colores: { columnas: [], por_rama: {} } });
    }
  }
  useEffect(() => { cargar(); }, []);
  useEffect(() => {
    api("/api/clases/profes").then(setListaProfes).catch((e) => setError(`No pude traer la lista de profes: ${e.message}`));
  }, []);

  function avisar(texto) {
    setAviso(texto);
    setTimeout(() => setAviso(""), 4000);
  }

  // hace un cambio en el servidor y vuelve a cargar todo.
  // Mientras espera se apagan los botones; el que se tocó muestra "Guardando…"
  async function hacer(fn, ok, clave = "si") {
    if (enCurso.current) return;
    enCurso.current = true;
    setOcupado(clave);
    setError("");
    try {
      const r = await fn();
      if (ok) avisar(typeof ok === "function" ? ok(r) : ok);
      await cargar();
    } catch (e) {
      setError(e.message);
    } finally {
      enCurso.current = false;
      setOcupado("");
    }
  }
  const esperando = (clave, texto, normal) => (ocupado === clave ? texto : normal);

  const clases = useMemo(
    () => (datos?.clases || []).filter((c) => verInactivas || c.activa),
    [datos, verInactivas]
  );
  const colores = datos?.colores || { columnas: [], por_rama: {} };
  const sinRama = clases.filter((c) => c.activa && c.tipo === "grupal" && !c.rama).length;

  const ambitos = Object.keys(AMBITOS).filter((a) => clases.some((c) => c.ambito === a));
  const delAmbito = useMemo(() => clases.filter((c) => c.ambito === ambito), [clases, ambito]);
  const profesFiltro = useMemo(() => [...new Set(delAmbito.map((c) => c.profe).filter(Boolean))].sort(), [delAmbito]);
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
  const grupalesObvias = clases.filter((c) => c.estimado && c.activa && c.tipo === "grupal" && c.alumnos.length >= 3).length;

  const sel = clases.find((c) => c.id === abierta);

  // el formulario del panel arranca con lo que tiene la clase
  useEffect(() => {
    if (sel) setForm({ tipo: sel.tipo, nivel: sel.nivel, cupo: sel.cupo, profesor_id: sel.profe_id ?? "" });
    else setForm(null);
  }, [sel?.id, datos]);

  useEffect(() => { setQAlu(""); setResultados([]); }, [abierta]);

  // buscador de alumnos para anotar en la clase
  useEffect(() => {
    if (qAlu.trim().length < 2) { setResultados([]); return; }
    const t = setTimeout(async () => {
      try {
        setResultados(await api(`/api/clases/buscar-alumnos?q=${encodeURIComponent(qAlu.trim())}`));
      } catch (e) {
        setResultados([]);
        setError(`No pude buscar alumnos: ${e.message}`);
      }
    }, 250);
    return () => clearTimeout(t);
  }, [qAlu]);

  const hayCambios =
    sel && form &&
    (form.tipo !== sel.tipo ||
      form.nivel.trim().toUpperCase() !== sel.nivel ||
      Number(form.cupo) !== sel.cupo ||
      String(form.profesor_id) !== String(sel.profe_id ?? ""));

  function guardar() {
    const cambios = {};
    if (form.tipo !== sel.tipo) cambios.tipo = form.tipo;
    if (form.nivel.trim().toUpperCase() !== sel.nivel) cambios.nivel = form.nivel;
    if (Number(form.cupo) !== sel.cupo) cambios.cupo = Number(form.cupo);
    if (String(form.profesor_id) !== String(sel.profe_id ?? "")) {
      cambios.profesor_id = form.profesor_id === "" ? null : Number(form.profesor_id);
    }
    hacer(() => api(`/api/clases/${sel.id}`, { metodo: "PATCH", cuerpo: cambios }), "Cambios guardados.", "guardar");
  }

  // rama y color: se guardan con un toque, sin pasar por "Guardar cambios"
  function elegirRama(rama) {
    const nueva = rama === sel.rama ? "" : rama; // tocar la que ya está la saca
    hacer(
      () => api(`/api/clases/${sel.id}`, { metodo: "PATCH", cuerpo: { rama: nueva } }),
      nueva ? `Rama: ${RAMAS[nueva]}.` : "La clase quedó sin rama.",
      "rama-" + rama
    );
  }

  function elegirColumna(valor) {
    hacer(
      () => api(`/api/clases/${sel.id}`, { metodo: "PATCH", cuerpo: { columna: valor === "" ? null : Number(valor) } }),
      valor === "" ? "Color automático." : "Color cambiado.",
      "columna"
    );
  }

  function confirmarTipo() {
    hacer(() => api(`/api/clases/${sel.id}`, { metodo: "PATCH", cuerpo: { confirmar_tipo: true } }), "Tipo confirmado.", "tipo");
  }

  function alternarActiva() {
    if (sel.activa && !window.confirm("¿Desactivar esta clase? Deja de contar, pero no se borra nada.")) return;
    hacer(
      () => api(`/api/clases/${sel.id}`, { metodo: "PATCH", cuerpo: { activa: !sel.activa } }),
      sel.activa ? "Clase desactivada." : "Clase reactivada.",
      "activa"
    );
  }

  function sacar(a) {
    if (!window.confirm(`¿Sacar a ${a.nombre} de esta clase?`)) return;
    hacer(() => api(`/api/clases/${sel.id}/alumnos/${a.id}`, { metodo: "DELETE" }), `${a.nombre} salió de la clase.`, "sacar-" + a.id);
  }

  function anotar(a) {
    if (enCurso.current) return;
    setQAlu("");
    setResultados([]);
    hacer(
      () => api(`/api/clases/${sel.id}/alumnos`, { metodo: "POST", cuerpo: { alumno_id: a.id } }),
      `${a.nombre} quedó anotado.`,
      "anotar"
    );
  }

  // clasificar o recategorizar: se actualiza en todas las clases donde está el alumno
  async function elegirNivel(a, nivel) {
    setError("");
    try {
      const r = await api(`/api/alumnos/${a.id}/nivel`, { metodo: "POST", cuerpo: { nivel } });
      const cambio = { nivel: r.nivel, nivel_declarado: r.nivel_declarado, clasificar: r.clasificar };
      setDatos((d) => ({
        ...d,
        clases: d.clases.map((c) => ({
          ...c,
          alumnos: c.alumnos.map((x) => (x.id === a.id ? { ...x, ...cambio } : x)),
        })),
      }));
      avisar(`${a.nombre} quedó en ${etiquetaNivel(r.nivel)}.`);
    } catch (e) {
      setError(`${a.nombre}: ${e.message}`);
      throw e;
    }
  }

  function confirmarGrupales() {
    hacer(
      () => api("/api/clases/confirmar-grupales", { metodo: "POST" }),
      (r) => `${r.confirmadas} clases confirmadas como grupales.`,
      "grupales"
    );
  }

  return (
    <div>
      <h1>Clases</h1>
      <p style={{ color: "#5b6672" }}>El horario fijo de la academia. Tocá una clase para editarla.</p>

      {error && <div className="cla-msg" onClick={() => setError("")}>{error}</div>}
      {aviso && <div className="cla-aviso">{aviso}</div>}

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

      {grupalesObvias > 0 && (
        <div className="cla-acciones">
          <button className="boton chico" disabled={!!ocupado} onClick={confirmarGrupales}>
            {esperando("grupales", "Guardando…", `Confirmar las ${grupalesObvias} grupales de 3 o 4 alumnos`)}
          </button>
          <span className="cla-sub">Son las que casi seguro son grupales. Las de 1 o 2 alumnos las confirmás una por una.</span>
        </div>
      )}

      <div className="cla-filtros">
        <select value={profe} onChange={(e) => setProfe(e.target.value)}>
          <option value="todos">Todos los profes</option>
          {profesFiltro.map((p) => <option key={p} value={p}>{capital(p)}</option>)}
        </select>
        <input placeholder="Buscar un alumno…" value={buscar} onChange={(e) => setBuscar(e.target.value)} />
        {hayBusqueda && <span className="cla-hallazgo">{aciertos} {aciertos === 1 ? "clase" : "clases"}</span>}
        <label className="cla-check">
          <input type="checkbox" checked={verInactivas} onChange={(e) => setVerInactivas(e.target.checked)} />
          Mostrar desactivadas
        </label>
        <button className="boton chico claro" disabled={!!ocupado} onClick={cargar}>Actualizar</button>
      </div>

      <Leyenda colores={colores} sinRama={sinRama} />

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
                          const nuevos = c.alumnos.filter((a) => a.clasificar).length;
                          const clase =
                            "cla-chip" +
                            (c.estimado ? " dudosa" : "") +
                            (n > c.cupo ? " pasada" : n === c.cupo ? " llena" : "") +
                            (!c.activa ? " apagada" : "") +
                            (c.id === abierta ? " abierta" : "") +
                            (hayBusqueda ? (coincide(c) ? " hit" : " opaco") : "");
                          return (
                            <button key={c.id} className={clase} onClick={() => setAbierta(c.id)}>
                              <span className="cla-arriba">
                                <Punto color={c.color} hueco={!!c.nivel} />
                                <b>{c.profe ? capital(c.profe) : "Sin profe"}</b>
                                <i>{TIPO_CORTO[c.tipo] || c.tipo}</i>
                              </span>
                              <span className="cla-abajo">{c.nivel || "—"} · {n}/{c.cupo}</span>
                              {nuevos > 0 && (
                                <span className="cla-nuevos">{nuevos === 1 ? "1 nuevo a clasificar" : `${nuevos} nuevos a clasificar`}</span>
                              )}
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

          {sel && form && (
            <aside className="cla-detalle">
              <button className="cla-cerrar" onClick={() => setAbierta(null)} aria-label="Cerrar">×</button>
              <h2>{DIAS[sel.dia]} {sel.hora}</h2>
              <p className="cla-sub">
                <Punto color={sel.color} hueco={!!sel.nivel} />
                {sel.profe ? capital(sel.profe) : "Sin profe"} · {sel.nivel || "Sin nivel"}
                {sel.rama && ` · ${RAMAS[sel.rama] || sel.rama}`}
                {!sel.activa && " · desactivada"}
              </p>

              <div className="cla-rama">
                <span className="cla-rama-titulo">Rama</span>
                <div className="cla-rama-botones" role="group" aria-label="Rama de la clase">
                  {Object.entries(RAMAS).map(([k, v]) => (
                    <button key={k} type="button" className={"cla-rama-op" + (sel.rama === k ? " activo" : "")}
                            aria-pressed={sel.rama === k} disabled={!!ocupado} onClick={() => elegirRama(k)}>
                      {esperando("rama-" + k, "Guardando…", v)}
                    </button>
                  ))}
                </div>
                {!sel.rama && sel.rama_sugerida && (
                  <div className="cla-sugerida">
                    Sugerido: <b>{RAMAS[sel.rama_sugerida.rama]}</b>
                    <span> ({sel.rama_sugerida.reconocidos} de {sel.rama_sugerida.total} nombres)</span>
                    <button type="button" className="boton chico" disabled={!!ocupado} onClick={() => elegirRama(sel.rama_sugerida.rama)}>
                      {esperando("rama-" + sel.rama_sugerida.rama, "Guardando…", "Confirmar")}
                    </button>
                  </div>
                )}
                {(sel.rama === "damas" || sel.rama === "caballeros") && colores.columnas.length > 0 && (
                  <label className="cla-columna">Color
                    <select value={sel.columna_manual ?? ""} disabled={!!ocupado} onChange={(e) => elegirColumna(e.target.value)}>
                      <option value="">
                        Automático{sel.columna_auto ? ` (${colores.columnas[sel.columna_auto - 1]?.nombre})` : " (sin color)"}
                      </option>
                      {colores.columnas.map((col) => (
                        <option key={col.n} value={col.n}>{col.n} · {col.nombre}: {textoColumna(col)}</option>
                      ))}
                    </select>
                  </label>
                )}
              </div>

              {sel.estimado && (
                <div className="cla-alerta">
                  El tipo ({TIPOS[sel.tipo]}) se estimó por la cantidad de alumnos.
                  <button className="boton chico" disabled={!!ocupado} onClick={confirmarTipo}>{esperando("tipo", "Guardando…", "Confirmar tipo")}</button>
                </div>
              )}
              {sel.alumnos.length > sel.cupo && (
                <div className="cla-alerta">Hay más alumnos que cupo. Puede ser que la planilla tenga varias clases mezcladas.</div>
              )}
              {sel.nota && <div className="cla-nota"><b>Nota de la planilla:</b> {sel.nota}</div>}

              <div className="cla-form">
                <label>Tipo
                  <select value={form.tipo} onChange={(e) => setForm({ ...form, tipo: e.target.value })}>
                    {Object.entries(TIPOS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                </label>
                <label>Nivel
                  <input value={form.nivel} placeholder="Ej. 6TA o 6TA/7MA" onChange={(e) => setForm({ ...form, nivel: e.target.value })} />
                </label>
                <label>Cupo
                  <input type="number" min="1" max="20" value={form.cupo} onChange={(e) => setForm({ ...form, cupo: e.target.value })} />
                </label>
                <label>Profe
                  <select value={form.profesor_id} onChange={(e) => setForm({ ...form, profesor_id: e.target.value })}>
                    <option value="">Sin profe</option>
                    {listaProfes.map((p) => <option key={p.id} value={p.id}>{capital(p.nombre)}</option>)}
                  </select>
                </label>
                <button className="boton chico" disabled={!hayCambios || !!ocupado} onClick={guardar}>{esperando("guardar", "Guardando…", "Guardar cambios")}</button>
              </div>

              <h3>Alumnos ({sel.alumnos.length})</h3>
              {sel.alumnos.length === 0 ? (
                <p className="cla-sub">Nadie anotado todavía.</p>
              ) : (
                <ol className="cla-lista">
                  {sel.alumnos.map((a) => (
                    <li key={a.id}>
                      <div className="cla-alumno">
                        <span>{a.nombre}</span>
                        <NivelAlumno alumno={a} niveles={datos.niveles} colores={colores}
                                     onElegir={(n) => elegirNivel(a, n)} />
                      </div>
                      <button className="cla-quitar" disabled={!!ocupado} onClick={() => sacar(a)} aria-label={`Sacar a ${a.nombre}`}>
                        {esperando("sacar-" + a.id, "…", "×")}
                      </button>
                    </li>
                  ))}
                </ol>
              )}

              <div className="cla-agregar">
                <input placeholder="Anotar un alumno (mín. 2 letras)…" value={qAlu} onChange={(e) => setQAlu(e.target.value)} />
                {/* el buscador se limpia al elegir: que se vea que está anotando */}
                {ocupado === "anotar" && <p className="cla-sub">Anotando…</p>}
                {resultados.length > 0 && (
                  <ul className="cla-resultados">
                    {resultados.map((a) => {
                      const ya = sel.alumnos.some((x) => x.id === a.id);
                      return (
                        <li key={a.id}>
                          <button disabled={ya || !!ocupado} onClick={() => anotar(a)}>
                            {a.nombre}{ya ? " (ya está)" : ""}
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>

              <button className="cla-peligro" disabled={!!ocupado} onClick={alternarActiva}>
                {esperando("activa", "Guardando…", sel.activa ? "Desactivar clase" : "Reactivar clase")}
              </button>
            </aside>
          )}
        </div>
      )}
    </div>
  );
}