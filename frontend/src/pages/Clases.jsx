import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api.js";
import { NivelAlumno, Punto, RAMAS, etiquetaNivel, rangoNivel } from "../niveles.jsx";
import { MARCA } from "../marca.js";
import { diaSemana, hoyEn, sumarDias } from "../fechas.js";
import { useEsCelu } from "../useEsCelu.js";
import "./clases.css";

const DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"];
const AMBITOS = { adultos: "Adultos mañana", adultos_tarde: "Adultos tarde", sabados: "Sábados", kids: "Kids", kids_pro: "Kids Pro" };
const TIPOS = { grupal: "Grupal", particular: "Particular", particular_2: "Particular de 2", otro: "Otro", fisico: "Físico" };
const TIPO_CORTO = { grupal: "G", particular: "P", particular_2: "P2", otro: "Otro", fisico: "F" };

const norm = (s) => String(s || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim();
const capital = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1).toLowerCase() : "");
// punto y etiqueta del nivel viven en ../niveles.jsx (los comparten Mis clases y Fichas)

// "2026-12-14" -> "14/12"
const ddmm = (s) => `${s.slice(8, 10)}/${s.slice(5, 7)}`;
const DIA_CORTO = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"];
const conDia = (s) => `${DIA_CORTO[diaSemana(s)]} ${ddmm(s)}`;
// "2026-11-18" -> "mié 18/11/2026": así se ve la fecha en el celu (iOS muestra el campo vacío o en su formato)
const fechaLarga = (s) => `${conDia(s)}/${s.slice(0, 4)}`;

// temporada de la clase mirada desde una fecha. vigente_hasta es el primer día que YA NO va,
// así que el último día que rige es el anterior
function temporada(c, ref) {
  const { vigente_desde: desde, vigente_hasta: hasta } = c;
  if (!desde && !hasta) return null;
  const ultimo = hasta && sumarDias(hasta, -1);
  if (desde && desde > ref) {
    return { estado: "futura", corto: `Desde ${ddmm(desde)}`, largo: `Empieza el ${conDia(desde)}` + (ultimo ? ` y rige hasta el ${conDia(ultimo)}.` : ".") };
  }
  if (ultimo) {
    return { estado: "termina", corto: `Hasta ${ddmm(ultimo)}`, largo: (desde ? `Rige desde el ${conDia(desde)} ` : "Rige ") + `hasta el ${conDia(ultimo)}. Desde el ${conDia(hasta)} ya no se da.` };
  }
  return { estado: "vigente", corto: `Desde ${ddmm(desde)}`, largo: `Rige desde el ${conDia(desde)}, sin fecha de fin.` };
}

// una columna de la tabla en texto: "Cab. 7ma-6ta · Damas 6ta"
const textoColumna = (col) =>
  [col.caballeros.length && `Cab. ${rangoNivel(col.caballeros)}`, col.damas.length && `Damas ${rangoNivel(col.damas)}`]
    .filter(Boolean).join(" · ");

// hayPasadas: "Más alumnos que cupo" solo si alguna de las que se ven está pasada de cupo
function Leyenda({ colores, sinRama, hayTemporadas, hayPasadas }) {
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
      {hayPasadas && <span className="cla-ley"><span className="cla-muestra pasada" />Más alumnos que cupo</span>}
      {hayTemporadas && <span className="cla-ley"><span className="cla-muestra futura" />Empieza más adelante</span>}
    </div>
  );
}

export default function Clases() {
  const [datos, setDatos] = useState(null);
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");
  const [ambito, setAmbito] = useState("adultos");
  const [hoy] = useState(() => hoyEn(MARCA.zonaHoraria));
  // arranca en hoy. "" = todas las que no terminaron; con fecha = las que rigen ese día
  const [fecha, setFecha] = useState(hoy);
  // con fecha elegida: las que empiezan después, para avisar que existen (ej. Kids desde el 14/12)
  const [futuras, setFuturas] = useState([]);
  const esCelu = useEsCelu();
  const [diaCelu, setDiaCelu] = useState(null); // en el celu se ve un día a la vez
  const [verLeyenda, setVerLeyenda] = useState(false); // en el celu la leyenda arranca cerrada
  const [profe, setProfe] = useState("todos");
  const [buscar, setBuscar] = useState("");
  const [abierta, setAbierta] = useState(null);
  const [verInactivas, setVerInactivas] = useState(false);
  const [listaProfes, setListaProfes] = useState([]);
  const [form, setForm] = useState(null);
  const [qAlu, setQAlu] = useState("");
  const [resultados, setResultados] = useState([]);
  // al anotar en una particular con el head coach: alumno nuevo que pidió con él (paga su tarifa)
  const [nuevoHC, setNuevoHC] = useState(false);
  useEffect(() => { setNuevoHC(false); }, [abierta]); // otra clase: arranca destildada
  const [ocupado, setOcupado] = useState(""); // qué botón está esperando ("" = ninguno)
  const enCurso = useRef(false); // candado contra el doble click

  async function cargar(dia = fecha) {
    try {
      setDatos(await api(dia ? `/api/clases?fecha=${dia}` : "/api/clases"));
    } catch (e) {
      setError(e.message);
      setDatos({ clases: [], colores: { columnas: [], por_rama: {} } });
    }
  }
  useEffect(() => { cargar(fecha); }, [fecha]);
  // solo al cambiar la fecha (no después de cada guardado): un pedido sin fecha y se cuentan las que arrancan más adelante
  useEffect(() => {
    if (!fecha) { setFuturas([]); return; }
    let vale = true;
    api("/api/clases")
      .then((d) => vale && setFuturas((d.clases || []).filter((c) => c.activa && c.vigente_desde && c.vigente_desde > fecha)))
      .catch(() => vale && setFuturas([])); // es solo un aviso: si falla, no se muestra
    return () => { vale = false; };
  }, [fecha]);

  // ver todas (sin fecha): si en este ámbito no hay ninguna de las que empiezan después, salta al que tenga
  function verFuturas() {
    const destino = futuras.some((c) => c.ambito === ambito) ? ambito : futuras[0]?.ambito;
    setDatos(null); // si no, con los datos viejos el ámbito nuevo no existe y vuelve al primero
    setAbierta(null);
    setFecha("");
    if (destino) { setAmbito(destino); setProfe("todos"); }
  }
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
  // si con la fecha elegida el ámbito no tiene clases, salta al primero que tenga
  useEffect(() => {
    if (ambitos.length && !ambitos.includes(ambito)) { setAmbito(ambitos[0]); setProfe("todos"); setAbierta(null); }
  }, [ambitos.join(","), ambito]);
  const ref = fecha || hoy;
  const delAmbito = useMemo(() => clases.filter((c) => c.ambito === ambito), [clases, ambito]);
  const profesFiltro = useMemo(() => [...new Set(delAmbito.map((c) => c.profe).filter(Boolean))].sort(), [delAmbito]);
  const filtradas = useMemo(
    () => delAmbito.filter((c) => profe === "todos" || c.profe === profe),
    [delAmbito, profe]
  );

  // misma cuenta que el borde rojo del chip, sobre lo que se está viendo (ámbito, profe, fecha)
  const hayPasadas = filtradas.some((c) => c.alumnos.length > c.cupo);

  const q = norm(buscar);
  const coincide = (c) => q.length >= 2 && c.alumnos.some((a) => norm(a.nombre).includes(q));
  const hayBusqueda = q.length >= 2;
  const aciertos = hayBusqueda ? filtradas.filter(coincide).length : 0;

  const dias = [...new Set(filtradas.map((c) => c.dia))].sort((a, b) => a - b);
  const horas = [...new Set(filtradas.map((c) => c.hora))].sort();
  const celdas = {};
  for (const c of filtradas) (celdas[c.dia + "|" + c.hora] ||= []).push(c);
  // la de apoyo va pegada abajo de su titular (si están en la misma celda); el resto, en el orden de siempre
  for (const lista of Object.values(celdas)) {
    const pos = new Map(lista.map((c, i) => [c.id, i]));
    const base = (c) => (c.apoyo_de && pos.has(c.apoyo_de) ? pos.get(c.apoyo_de) : pos.get(c.id));
    lista.sort((a, b) => base(a) - base(b) || (a.apoyo_de ? 1 : 0) - (b.apoyo_de ? 1 : 0) || pos.get(a.id) - pos.get(b.id));
  }

  // celu: el día que tocó, si no el de la fecha (o hoy) si tiene clases, si no el primero
  useEffect(() => setDiaCelu(null), [fecha]);
  const diaRef = diaSemana(fecha || hoy);
  const diaVisible = dias.includes(diaCelu) ? diaCelu : dias.includes(diaRef) ? diaRef : dias[0];
  const horasDelDia = horas.filter((h) => celdas[diaVisible + "|" + h]);
  // fecha de cada día en la semana de la fecha elegida, para las pestañas ("Mié 18")
  const fechaDelDia = (d) => (fecha ? sumarDias(fecha, d - diaSemana(fecha)) : null);

  // aviso de las que empiezan más adelante: por ámbito, con la primera fecha
  const futurasPorAmbito = {};
  for (const c of futuras) {
    const a = futurasPorAmbito[c.ambito];
    if (!a || c.vigente_desde < a) futurasPorAmbito[c.ambito] = c.vigente_desde;
  }
  const textoFuturas = Object.entries(futurasPorAmbito)
    .map(([a, desde]) => `${AMBITOS[a] || a} desde el ${ddmm(desde)}`)
    .join(", ");

  const alumnosUnicos = new Set(filtradas.flatMap((c) => c.alumnos.map((a) => a.id))).size;
  const porConfirmar = filtradas.filter((c) => c.estimado).length;
  // las de apoyo no tienen alumnos a propósito (se anotan en la titular): no cuentan como vacías
  const vacias = filtradas.filter((c) => c.alumnos.length === 0 && !c.apoyo_de).length;
  // sin fecha se ven juntas las de distintas temporadas: avisamos
  const hayTemporadas = filtradas.some((c) => c.vigente_desde || c.vigente_hasta);
  const grupalesObvias = clases.filter((c) => c.estimado && c.activa && c.tipo === "grupal" && c.alumnos.length >= 3).length;

  const sel = clases.find((c) => c.id === abierta);
  const temSel = sel && temporada(sel, ref);

  // filas de apoyo: otro profe en el mismo grupo, los alumnos van solo en la titular
  const porId = useMemo(() => Object.fromEntries((datos?.clases || []).map((c) => [c.id, c])), [datos]);
  const titularSel = sel?.apoyo_de ? porId[sel.apoyo_de] : null;
  const apoyosSel = sel ? (datos?.clases || []).filter((c) => c.apoyo_de === sel.id && c.activa) : [];
  // candidatas a titular: mismo día, activas, que no sean apoyo. El horario lo valida el back
  const candidatas = sel
    ? (datos?.clases || [])
        .filter((c) => c.id !== sel.id && c.activa && !c.apoyo_de && c.dia === sel.dia && c.ambito === sel.ambito)
        .sort((a, b) => a.hora.localeCompare(b.hora))
    : [];
  const textoClase = (c) => `${c.hora} · ${c.profe ? capital(c.profe) : "Sin profe"} · ${c.nivel || "sin nivel"}`;

  // el formulario del panel arranca con lo que tiene la clase
  useEffect(() => {
    if (sel) setForm({ tipo: sel.tipo, nivel: sel.nivel, cupo: sel.cupo, profesor_id: sel.profe_id ?? "" });
    else setForm(null);
  }, [sel?.id, datos]);

  useEffect(() => { setQAlu(""); setResultados([]); }, [abierta]);

  // celu: el detalle es una hoja encima. Mientras está abierta el fondo no scrollea y Escape la cierra
  const hojaAbierta = esCelu && !!sel;
  useEffect(() => {
    if (!hojaAbierta) return;
    const alTeclear = (e) => e.key === "Escape" && setAbierta(null);
    window.addEventListener("keydown", alTeclear);
    document.body.classList.add("sin-scroll");
    return () => {
      window.removeEventListener("keydown", alTeclear);
      document.body.classList.remove("sin-scroll");
    };
  }, [hojaAbierta]);

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

  // se guarda con un toque, como la rama. "" = vuelve a ser clase normal
  function elegirApoyo(valor) {
    hacer(
      () => api(`/api/clases/${sel.id}`, { metodo: "PATCH", cuerpo: { apoyo_de: valor === "" ? null : Number(valor) } }),
      valor === "" ? "Ahora es una clase normal." : "Marcada como fila de apoyo.",
      "apoyo"
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
    const hc = !!sel.head_coach && nuevoHC;
    setNuevoHC(false);
    hacer(
      () => api(`/api/clases/${sel.id}/alumnos`, { metodo: "POST", cuerpo: { alumno_id: a.id, tarifa_head_coach: hc } }),
      `${a.nombre} quedó anotado${hc ? " con tarifa Head Coach" : ""}.`,
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

  // una clase en la grilla (compu) o en la lista del día (celu)
  function chip(c) {
    const n = c.alumnos.length;
    const nuevos = c.alumnos.filter((a) => a.clasificar).length;
    const tem = temporada(c, ref);
    const clase =
      "cla-chip" +
      (c.estimado ? " dudosa" : "") +
      (n > c.cupo ? " pasada" : n === c.cupo ? " llena" : "") +
      (!c.activa ? " apagada" : "") +
      (c.id === abierta ? " abierta" : "") +
      (tem?.estado === "futura" ? " futura" : "") +
      (hayBusqueda ? (coincide(c) ? " hit" : " opaco") : "");
    return (
      <button key={c.id} className={clase} onClick={() => setAbierta(c.id)}>
        <span className="cla-arriba">
          <Punto color={c.color} hueco={!!c.nivel} />
          <b>{c.profe ? capital(c.profe) : "Sin profe"}</b>
          <i>{TIPO_CORTO[c.tipo] || c.tipo}</i>
        </span>
        <span className="cla-abajo">{c.nivel || "—"} · {c.apoyo_de ? "apoyo" : `${n}/${c.cupo}`}</span>
        {tem && <span className={"cla-vig " + tem.estado} title={tem.largo}>{tem.corto}</span>}
        {nuevos > 0 && (
          <span className="cla-nuevos">{nuevos === 1 ? "1 nuevo a clasificar" : `${nuevos} nuevos a clasificar`}</span>
        )}
      </button>
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
        <button className="boton chico claro" disabled={!!ocupado} onClick={() => cargar()}>Actualizar</button>
      </div>

      <div className="cla-fecha">
        <label>
          Clases que rigen el
          {/* en el celu se ve el texto y el selector nativo queda encima, invisible: tocar abre el calendario */}
          <span className="cla-fecha-campo">
            <span className="cla-fecha-texto" aria-hidden="true">{fecha ? fechaLarga(fecha) : "Todas las fechas"}</span>
            <input type="date" value={fecha} onChange={(e) => { setFecha(e.target.value); setAbierta(null); }} />
          </span>
        </label>
        {fecha !== hoy && <button className="boton chico claro" onClick={() => { setFecha(hoy); setAbierta(null); }}>Hoy</button>}
        {fecha && <button className="boton chico claro" onClick={() => { setFecha(""); setAbierta(null); }}>Ver todas</button>}
        <span className="cla-sub">
          {fecha
            ? `El horario que rige el ${conDia(fecha)}${fecha === hoy ? " (hoy)" : ""}, toda esa semana. Los alumnos son los anotados hoy.`
            : hayTemporadas
              ? "Se ven juntas las de ahora y las que empiezan más adelante. Elegí una fecha para ver cuáles rigen ese día."
              : "Todas las que no terminaron."}
        </span>
      </div>

      {/* con fecha no se ven las que empiezan después: que no parezca que faltan clases */}
      {fecha && futuras.length > 0 && (
        <button type="button" className="cla-futuras" onClick={verFuturas}>
          <span>
            Hay {futuras.length === 1 ? "1 clase que empieza" : `${futuras.length} clases que empiezan`} más adelante
            {textoFuturas && <small> ({textoFuturas})</small>}
          </span>
          <b>Ver</b>
        </button>
      )}

      {/* en el celu la leyenda ocupa media pantalla: arranca cerrada */}
      {esCelu && (
        <button type="button" className="cla-leyenda-boton" aria-expanded={verLeyenda} onClick={() => setVerLeyenda(!verLeyenda)}>
          <span>Referencias de colores</span>
          <span aria-hidden="true">{verLeyenda ? "▲" : "▼"}</span>
        </button>
      )}
      {(!esCelu || verLeyenda) && <Leyenda colores={colores} sinRama={sinRama} hayTemporadas={hayTemporadas && !fecha} hayPasadas={hayPasadas} />}

      {datos === null ? (
        <div className="cargando">Cargando…</div>
      ) : filtradas.length === 0 ? (
        <div className="cla-vacio">No hay clases con esos filtros.</div>
      ) : (
        <div className="cla-cuerpo">
          {esCelu ? (
            // celu: un día a la vez, con pestañas arriba
            <div className="cla-dia-celu">
              <div className="cla-dias" role="tablist" aria-label="Día">
                {dias.map((d) => {
                  const f = fechaDelDia(d);
                  // buscando un alumno: los días donde aparece llevan un punto (los otros días no se ven)
                  const conHit = hayBusqueda && filtradas.some((c) => c.dia === d && coincide(c));
                  return (
                    <button
                      key={d}
                      role="tab"
                      aria-selected={d === diaVisible}
                      className={"cla-dia" + (d === diaVisible ? " activo" : "") + (f && f === hoy ? " hoy" : "")}
                      onClick={() => setDiaCelu(d)}
                    >
                      <span>{DIAS[d].slice(0, 3)}</span>
                      {f && <strong>{Number(f.slice(8, 10))}</strong>}
                      {conHit && <i className="cla-dia-hit" aria-label="tiene coincidencias" />}
                    </button>
                  );
                })}
              </div>
              <div className="cla-lista-dia">
                {horasDelDia.map((h) => (
                  <div key={h} className="cla-franja">
                    <div className="cla-franja-hora">{h}</div>
                    <div className="cla-franja-clases">{celdas[diaVisible + "|" + h].map(chip)}</div>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="cla-scroll">
              <table className="cla-grilla">
                <thead>
                  <tr>
                    <th className="hora">Hora</th>
                    {dias.map((d) => (
                      <th key={d} className={fecha && diaSemana(fecha) === d ? "elegido" : ""}>
                        {DIAS[d]}{fecha && diaSemana(fecha) === d && ` ${ddmm(fecha)}`}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {horas.map((h) => (
                    <tr key={h}>
                      <td className="hora">{h}</td>
                      {dias.map((d) => (
                        <td key={d}>{(celdas[d + "|" + h] || []).map(chip)}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* celu: fondo oscuro detrás de la hoja; tocarlo la cierra */}
          {hojaAbierta && form && <div className="cla-velo" onClick={() => setAbierta(null)} aria-hidden="true" />}
          {sel && form && (
            <aside className={"cla-detalle" + (esCelu ? " hoja" : "")} role={esCelu ? "dialog" : undefined} aria-modal={esCelu || undefined}
                   aria-label={`Clase del ${DIAS[sel.dia]} ${sel.hora}`}>
              {esCelu ? (
                <div className="cla-hoja-cabeza">
                  <h2>{DIAS[sel.dia]} {sel.hora}</h2>
                  <button className="boton chico claro" onClick={() => setAbierta(null)}>Cerrar</button>
                </div>
              ) : (
                <>
                  <button className="cla-cerrar" onClick={() => setAbierta(null)} aria-label="Cerrar">×</button>
                  <h2>{DIAS[sel.dia]} {sel.hora}</h2>
                </>
              )}
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

              {temSel && <div className={"cla-temporada " + temSel.estado}>{temSel.largo}</div>}

              {/* fila de apoyo: otro profe en el mismo grupo; cobra según la titular */}
              <div className="cla-rama">
                <span className="cla-rama-titulo">Fila de apoyo</span>
                {apoyosSel.length > 0 ? (
                  <span className="cla-sub">
                    Es la titular. Apoyo: {apoyosSel.map((a) => (a.profe ? capital(a.profe) : "Sin profe")).join(", ")}.
                  </span>
                ) : (
                  <>
                    <label className="cla-columna">Es apoyo de
                      <select value={sel.apoyo_de ?? ""} disabled={!!ocupado} onChange={(e) => elegirApoyo(e.target.value)}>
                        <option value="">No, es una clase normal</option>
                        {titularSel && !candidatas.includes(titularSel) && (
                          <option value={titularSel.id}>{textoClase(titularSel)}</option>
                        )}
                        {candidatas.map((c) => <option key={c.id} value={c.id}>{textoClase(c)}</option>)}
                      </select>
                    </label>
                    {ocupado === "apoyo" && <span className="cla-sub">Guardando…</span>}
                    <span className="cla-sub">
                      {sel.apoyo_de
                        ? "Los alumnos se anotan en la titular. El profe marca “di la clase” en Mis clases para que cuente su hora."
                        : "Para un segundo profe en el mismo grupo: no lleva alumnos propios."}
                    </span>
                  </>
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
                {/* con cambios: color de la marca. Sin cambios: gris y lo dice, para que no parezca roto */}
                <button className="boton chico principal" disabled={!hayCambios || !!ocupado} onClick={guardar}>
                  {esperando("guardar", "Guardando…", hayCambios ? "Guardar cambios" : "Sin cambios")}
                </button>
              </div>

              {sel.apoyo_de ? (
                <p className="cla-sub">
                  Los alumnos van en la titular{titularSel ? ` (${textoClase(titularSel)})` : ""}.
                  {titularSel && (
                    <> <button type="button" className="boton chico claro" onClick={() => setAbierta(titularSel.id)}>Ver la titular</button></>
                  )}
                </p>
              ) : (<>
              <h3>Alumnos ({sel.alumnos.length})</h3>
              {sel.alumnos.length === 0 ? (
                <p className="cla-sub">Nadie anotado todavía.</p>
              ) : (
                <ol className="cla-lista">
                  {sel.alumnos.map((a) => (
                    <li key={a.id}>
                      <div className="cla-alumno">
                        <span>{a.nombre}</span>
                        {sel.head_coach && a.tarifa_head_coach && <span className="cla-chip-hc">Tarifa Head Coach</span>}
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
                {/* antes del buscador: se tilda y después se elige al alumno (la lista de resultados no la tapa) */}
                {sel.head_coach && (
                  <label className="cla-check-hc">
                    <input type="checkbox" checked={nuevoHC} onChange={(e) => setNuevoHC(e.target.checked)} />
                    <span>Es nuevo y pidió con el Head Coach: paga tarifa Head Coach</span>
                  </label>
                )}
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
              </>)}

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