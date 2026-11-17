import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api.js";
import { useAuth } from "../auth.jsx";
import { GESTION } from "../roles.js";
import { MARCA } from "../marca.js";
import { diaSemana, hoyEn, lunesDe, mesDe, numeroDia, sumarDias } from "../fechas.js";
import { Punto, etiquetaNivel, RAMAS } from "../niveles.jsx";
import "./semana.css";

// Clases de la semana: solo para mirar quiénes se esperan. La asistencia se marca en Mis clases.

const DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"];
const LETRAS = ["L", "M", "M", "J", "V", "S", "D"];
const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
const TIPOS = { grupal: "Grupal", particular: "Particular", particular_2: "Particular de 2", otro: "Otra", fisico: "Físico" };
const AMBITOS = { adultos: "Adultos", adultos_tarde: "Adultos tarde", sabados: "Sábados", kids: "Kids", kids_pro: "Kids Pro" };
// etiqueta que manda el backend -> clase de color
const TAGS = { recupera: "", reemplaza: "", "avisó": " aviso", "de viaje": " viaje" };

// "16 – 22 nov" o "30 nov – 6 dic"
function rango(lunes) {
  const dom = sumarDias(lunes, 6);
  return mesDe(lunes) === mesDe(dom)
    ? `${numeroDia(lunes)} – ${numeroDia(dom)} ${MESES[mesDe(dom)]}`
    : `${numeroDia(lunes)} ${MESES[mesDe(lunes)]} – ${numeroDia(dom)} ${MESES[mesDe(dom)]}`;
}

const plural = (n, uno, varios) => `${n} ${n === 1 ? uno : varios}`;

function Alumno({ a, gris }) {
  return (
    <li className={"sm-alumno" + (gris ? " gris" : "")}>
      <span className="sm-nombre">{a.nombre}</span>
      {a.etiqueta && <span className={"sm-tag" + (TAGS[a.etiqueta] ?? "")}>{a.etiqueta}</span>}
    </li>
  );
}

function Clase({ c, fecha, hoy, verProfe }) {
  const titulo = [TIPOS[c.tipo] || c.tipo, c.nivel && etiquetaNivel(c.nivel), RAMAS[c.rama]].filter(Boolean).join(" · ");
  const reemplazo = c.la_dio ? ` · ${fecha < hoy ? "la dio" : "la da"} ${c.la_dio}` : "";
  return (
    <article className="sm-clase" style={{ "--color-clase": c.color || "var(--linea)" }}>
      <div className="sm-cabeza">
        <span className="sm-hora">
          {c.hora}
          <small>{c.duracion} min</small>
        </span>
        <span className="sm-cant" title="Alumnos esperados / cupo">
          {c.cantidad}
          {c.cupo ? `/${c.cupo}` : ""}
        </span>
      </div>
      <div className="sm-titulo">
        <Punto color={c.color} hueco={!!c.nivel} />
        {titulo}
      </div>
      <div className="sm-sub">
        {AMBITOS[c.ambito] || c.ambito}
        {(verProfe || c.la_dio) && c.profe ? ` · ${c.profe}` : ""}
        {reemplazo}
      </div>
      {c.vienen.length === 0 && c.no_vienen.length === 0 ? (
        <div className="sm-nadie">Sin alumnos esperados</div>
      ) : (
        <ul className="sm-alumnos">
          {c.vienen.map((a) => (
            <Alumno key={a.id} a={a} />
          ))}
          {c.no_vienen.map((a) => (
            <Alumno key={a.id} a={a} gris />
          ))}
        </ul>
      )}
    </article>
  );
}

export default function Semana() {
  const { usuario } = useAuth();
  const verTodas = GESTION.includes(usuario.rol);
  // "hoy" en la academia, no en el navegador (y corrido si es la simulación)
  const [hoy] = useState(() => hoyEn(MARCA.zonaHoraria));
  const lunesActual = lunesDe(hoy);
  const [lunes, setLunes] = useState(lunesActual);
  const [datos, setDatos] = useState(null);
  const [error, setError] = useState("");
  const [profe, setProfe] = useState(""); // filtro en el navegador, solo gestión
  const [abiertos, setAbiertos] = useState(() => new Set([hoy])); // días abiertos en el celu
  const refs = useRef({});

  useEffect(() => {
    let vigente = true;
    setDatos(null);
    setError("");
    api(`/api/clases-semana?desde=${lunes}`)
      .then((d) => {
        if (!vigente) return;
        setDatos(d);
        // en el celu arranca abierto hoy; si la semana no es esta, el primer día con clases
        if (lunes !== lunesActual) {
          const primero = d.dias.find((x) => x.clases.length > 0);
          setAbiertos(new Set(primero ? [primero.fecha] : []));
        } else {
          setAbiertos(new Set([hoy]));
        }
      })
      .catch((e) => vigente && setError(e.message || "No se pudo cargar la semana"));
    return () => {
      vigente = false;
    };
  }, [lunes, lunesActual, hoy]);

  // profes de la semana para el selector (titulares y reemplazos)
  const profes = useMemo(() => {
    const s = new Set();
    for (const d of datos?.dias || []) for (const c of d.clases) [c.profe, c.la_dio].forEach((p) => p && s.add(p));
    return [...s].sort((a, b) => a.localeCompare(b));
  }, [datos]);
  useEffect(() => {
    if (profe && datos && !profes.includes(profe)) setProfe(""); // esa semana no tiene clases de ese profe
  }, [profes, profe, datos]);

  const dias = (datos?.dias || []).map((d) => ({
    ...d,
    clases: profe ? d.clases.filter((c) => c.profe === profe || c.la_dio === profe) : d.clases,
  }));
  const total = dias.reduce((n, d) => n + d.clases.length, 0);

  function alternar(fecha) {
    setAbiertos((s) => {
      const n = new Set(s);
      n.has(fecha) ? n.delete(fecha) : n.add(fecha);
      return n;
    });
  }

  // chip: abre ese día y lo lleva arriba (en el celu)
  function irADia(fecha) {
    setAbiertos((s) => new Set(s).add(fecha));
    requestAnimationFrame(() => refs.current[fecha]?.scrollIntoView({ behavior: "smooth", block: "start" }));
  }

  const vacio = verTodas
    ? profe
      ? `${profe} no tiene clases esta semana.`
      : "No hay clases esta semana."
    : "No tenés clases esta semana.";

  return (
    <div className="sm">
      <div className="cabecera">
        <div>
          <h1>Clases de la semana</h1>
          <div className="sub">Quiénes se esperan en cada clase. Solo para mirar: la asistencia se marca en Mis clases.</div>
        </div>
      </div>

      <div className="sm-barra">
        <div className="sm-nav">
          <button className="sm-flecha" onClick={() => setLunes(sumarDias(lunes, -7))} aria-label="Semana anterior">
            ‹
          </button>
          <div className="sm-rango">
            {rango(lunes)}
            {lunes === lunesActual && <small>esta semana</small>}
          </div>
          <button className="sm-flecha" onClick={() => setLunes(sumarDias(lunes, 7))} aria-label="Semana siguiente">
            ›
          </button>
          <button className="boton claro chico sm-hoy-btn" onClick={() => setLunes(lunesActual)} disabled={lunes === lunesActual}>
            Hoy
          </button>
        </div>
        <div className="sm-chips" role="tablist" aria-label="Días de la semana">
          {Array.from({ length: 7 }, (_, i) => {
            const f = sumarDias(lunes, i);
            const n = dias[i]?.clases.length;
            return (
              <button
                key={f}
                role="tab"
                aria-selected={abiertos.has(f)}
                aria-label={`${DIAS[i]} ${numeroDia(f)}`}
                className={"sm-chip" + (f === hoy ? " hoy" : "") + (abiertos.has(f) ? " activo" : "") + (datos && !n ? " vacio" : "")}
                onClick={() => irADia(f)}
              >
                <span>{LETRAS[i]}</span>
                <strong>{numeroDia(f)}</strong>
              </button>
            );
          })}
        </div>
        {verTodas && profes.length > 1 && (
          <label className="sm-filtro">
            <span>Profe</span>
            <select value={profe} onChange={(e) => setProfe(e.target.value)}>
              <option value="">Todos</option>
              {profes.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      {error && <div className="msg-error">{error}</div>}
      {!datos && !error && <div className="nota">Cargando…</div>}
      {datos && total === 0 && <div className="sm-vacio">{vacio}</div>}

      {datos && total > 0 && (
        <div className="sm-dias">
          {dias.map((d) => {
            const abierto = abiertos.has(d.fecha);
            return (
              <section
                key={d.fecha}
                ref={(el) => (refs.current[d.fecha] = el)}
                className={"sm-dia" + (abierto ? " abierto" : "") + (d.fecha === hoy ? " hoy" : "") + (d.clases.length ? "" : " sin")}
              >
                <button className="sm-dia-cabeza" onClick={() => alternar(d.fecha)} aria-expanded={abierto}>
                  <span className="sm-dia-nombre">
                    {DIAS[diaSemana(d.fecha)]} {numeroDia(d.fecha)}
                    {d.fecha === hoy && <em className="sm-hoy">hoy</em>}
                  </span>
                  <span className="sm-dia-cuenta">{d.clases.length ? plural(d.clases.length, "clase", "clases") : "sin clases"}</span>
                  <span className="sm-dia-flecha" aria-hidden>
                    {abierto ? "▲" : "▼"}
                  </span>
                </button>
                <div className="sm-dia-cuerpo">
                  {d.clases.length === 0 && <div className="sm-nadie">Sin clases este día</div>}
                  {d.clases.map((c) => (
                    <Clase key={c.id} c={c} fecha={d.fecha} hoy={hoy} verProfe={verTodas} />
                  ))}
                </div>
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}
