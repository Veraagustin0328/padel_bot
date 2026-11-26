import { useEffect, useState } from "react";
import { Link, useOutletContext } from "react-router-dom";
import { api } from "../api.js";
import { useAuth } from "../auth.jsx";
import { MARCA } from "../marca.js";
import { hoyEn } from "../fechas.js";
import { NovedadesVigentes } from "./Novedades.jsx";
import { Clase } from "./MisClases.jsx";
import "./inicio.css";

// Inicio de dueño, encargado y profe: un tablero por rol (alumnos y padres usan InicioAlumno).
// Los números salen de /api/inicio, que ya viene recortado según el rol: acá no se esconde nada,
// lo que no le toca a alguien directamente no llega.

const MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
  "septiembre", "octubre", "noviembre", "diciembre"];
const DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"];
const nombreMes = (mes) => MESES[Number(mes.slice(5, 7)) - 1];
const plata = (n) => "$" + Number(n || 0).toLocaleString("es-AR", { maximumFractionDigits: 0 });
const horasTxt = (n) => Number(n || 0).toLocaleString("es-AR", { maximumFractionDigits: 1 }) + " h";
const plural = (n, uno, varios) => `${n} ${n === 1 ? uno : varios}`;
const diaDe = (iso) => DIAS[(new Date(iso + "T12:00").getDay() + 6) % 7];
const fechaCorta = (iso) => `${iso.slice(8)}/${iso.slice(5, 7)}`;

// saludo según la hora de la academia
function saludo() {
  const h = Number(new Intl.DateTimeFormat("es-AR", { hour: "numeric", hour12: false, timeZone: MARCA.zonaHoraria }).format(new Date()));
  return h < 6 ? "Buenas noches" : h < 13 ? "Buen día" : h < 20 ? "Buenas tardes" : "Buenas noches";
}

function Tarjeta({ titulo, link, linkTxt = "Ver todo", children, tono = "" }) {
  return (
    <section className={"ini-tarjeta" + (tono ? " " + tono : "")}>
      <div className="ini-tarjeta-cabeza">
        <h2>{titulo}</h2>
        {link && <Link to={link} className="ini-link">{linkTxt} →</Link>}
      </div>
      {children}
    </section>
  );
}

// número grande con su etiqueta. tono: ok (verde) / mal (rojo)
function Numero({ valor, etiqueta, tono = "", sub }) {
  return (
    <div className={"ini-numero" + (tono ? " " + tono : "")}>
      <b>{valor}</b>
      <small>{etiqueta}</small>
      {sub && <em>{sub}</em>}
    </div>
  );
}

function Vacio({ children }) {
  return <div className="ini-vacio">{children}</div>;
}

function Atajos({ items }) {
  return (
    <div className="ini-atajos">
      {items.map(([a, t]) => (
        <Link key={a} to={a} className="boton chico">{t}</Link>
      ))}
    </div>
  );
}

function ClasesHoy({ datos, link = "/clases" }) {
  const { total, dadas, clases } = datos;
  return (
    <Tarjeta titulo="Clases de hoy" link={link} linkTxt="Clases">
      {total === 0 ? (
        <Vacio>Hoy no hay clases con alumnos.</Vacio>
      ) : (
        <>
          <div className="ini-numeros">
            <Numero valor={total} etiqueta={total === 1 ? "clase hoy" : "clases hoy"} />
            <Numero valor={dadas} etiqueta={dadas === 1 ? "ya se dio" : "ya se dieron"} tono={dadas === total ? "ok" : ""} />
          </div>
          <ul className="ini-lista">
            {clases.map((c) => (
              <li key={c.id} className={c.dada ? "hecha" : ""}>
                <span className="ini-hora">{c.hora}</span>
                <span className="ini-que">{c.tipo}{c.nivel && ` · ${c.nivel}`}<small>{c.profe || "Sin profe"}</small></span>
                <span className="ini-der">{c.dada ? "dada ✓" : plural(c.esperados, "alumno", "alumnos")}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </Tarjeta>
  );
}

// ---------- dueño ----------

function InicioDueno({ d, pendientes }) {
  const p = d.plata;
  const { sin_profe, sobre_cupo } = d.alertas;
  const hayAlertas = sin_profe.length + sobre_cupo.length > 0;
  return (
    <div className="ini-grilla">
      <Tarjeta titulo={`Plata de ${nombreMes(p.mes)}`} link="/cuotas" linkTxt="Cuotas" tono="ancha">
        {!p.generadas && <Vacio>Todavía no se generaron las cuotas de {nombreMes(p.mes)}. Se generan desde Cuotas.</Vacio>}
        <div className="ini-numeros">
          {/* sin cuotas generadas, los del mes serían todos $0: queda el aviso y solo el vencido */}
          {p.generadas && (
            <>
              <Numero valor={plata(p.cobrado)} etiqueta="Cobrado" tono="ok" />
              <Numero valor={plata(p.a_cobrar)} etiqueta="A cobrar en el mes" tono="ok" />
              <Numero valor={plata(p.falta)} etiqueta="Falta cobrar" tono={p.falta ? "mal" : ""}
                      sub={p.deben ? plural(p.deben, "alumno", "alumnos") : null} />
            </>
          )}
          <Numero valor={plata(p.vencido)} etiqueta="Vencido (meses anteriores)" tono={p.vencido ? "mal" : ""}
                  sub={p.deben_vencido ? plural(p.deben_vencido, "alumno", "alumnos") : null} />
        </div>
      </Tarjeta>

      <ClasesHoy datos={d.clases_hoy} />

      <Tarjeta titulo="Alertas" tono={hayAlertas ? "alerta" : ""} link="/clases" linkTxt="Clases">
        {!hayAlertas && <Vacio>Todo en orden: ninguna clase sin profe ni arriba del cupo.</Vacio>}
        {sin_profe.length > 0 && (
          <>
            <div className="ini-alerta-titulo">{plural(sin_profe.length, "clase sin profe", "clases sin profe")}</div>
            <ul className="ini-lista">
              {sin_profe.map((c) => <li key={c.id}><span className="ini-que">{c.clase}</span><span className="ini-der">{plural(c.anotados, "anotado", "anotados")}</span></li>)}
            </ul>
          </>
        )}
        {sobre_cupo.length > 0 && (
          <>
            <div className="ini-alerta-titulo">{plural(sobre_cupo.length, "clase arriba del cupo", "clases arriba del cupo")}</div>
            <ul className="ini-lista">
              {sobre_cupo.map((c) => <li key={c.id}><span className="ini-que">{c.clase}</span><span className="ini-der mal">{c.anotados}/{c.cupo}</span></li>)}
            </ul>
          </>
        )}
      </Tarjeta>

      <Tarjeta titulo="Alumnos" link="/alumnos" linkTxt="Alumnos">
        <div className="ini-numeros">
          <Numero valor={d.alumnos.activos} etiqueta="activos" />
          <Numero valor={d.alumnos.altas_mes} etiqueta={`altas en ${nombreMes(p.mes)}`} tono={d.alumnos.altas_mes ? "ok" : ""} />
          <Numero valor={d.alumnos.bajas_mes} etiqueta={`bajas en ${nombreMes(p.mes)}`} tono={d.alumnos.bajas_mes ? "mal" : ""} />
        </div>
      </Tarjeta>

      <Tarjeta titulo="Pendientes" link="/pendientes" linkTxt="Pendientes">
        <div className="ini-numeros">
          <Numero valor={pendientes.total} etiqueta={pendientes.total === 1 ? "cosa para revisar" : "cosas para revisar"}
                  tono={pendientes.total ? "mal" : "ok"} />
        </div>
        {!pendientes.total && <Vacio>No hay nada esperando.</Vacio>}
      </Tarjeta>

      <Tarjeta titulo="Atajos">
        <Atajos items={[["/cuotas", "Registrar pago"], ["/alumnos?nuevo=1", "+ Nuevo alumno"], ["/clases", "Clases"]]} />
      </Tarjeta>
    </div>
  );
}

// ---------- encargado ----------

function InicioEncargado({ d, pendientes }) {
  const { deudores, faltas_viajes: fv, incompletos } = d;
  const n = (x) => (x === undefined ? "—" : x); // la de comprobantes tarda (planilla de Google): mientras, una raya
  return (
    <div className="ini-grilla">
      <Tarjeta titulo="Pendientes" link="/pendientes" linkTxt="Pendientes">
        <div className="ini-numeros">
          <Link to="/pendientes/solicitudes" className="ini-numero-link">
            <Numero valor={n(pendientes.solicitudes)} etiqueta="solicitudes de registro" tono={pendientes.solicitudes ? "mal" : ""} />
          </Link>
          <Link to="/pendientes/comprobantes" className="ini-numero-link">
            <Numero valor={n(pendientes.comprobantes)} etiqueta="comprobantes por revisar" tono={pendientes.comprobantes ? "mal" : ""} />
          </Link>
        </div>
      </Tarjeta>

      <Tarjeta titulo="Deudores" link="/cuotas" linkTxt="Cuotas">
        {!deudores.generadas && <Vacio>Todavía no se generaron las cuotas de {nombreMes(deudores.mes)}.</Vacio>}
        {deudores.total === 0 ? (
          deudores.generadas && <Vacio>Nadie debe la cuota de {nombreMes(deudores.mes)} ni la del mes anterior.</Vacio>
        ) : (
          <>
            <ul className="ini-lista">
              {deudores.items.map((x) => (
                <li key={`${x.alumno_id}-${x.mes}`}>
                  <span className="ini-que">{x.alumno}</span>
                  <span className={"ini-der" + (x.vencida ? " mal" : "")}>Cuota de {nombreMes(x.mes)}</span>
                </li>
              ))}
            </ul>
            {deudores.total > deudores.items.length && (
              <div className="nota">y {deudores.total - deudores.items.length} más en Cuotas.</div>
            )}
          </>
        )}
      </Tarjeta>

      <Tarjeta titulo="Faltas y viajes de hoy" link="/faltas-viajes" linkTxt="Faltas y viajes">
        {fv.faltas_hoy + fv.viajes_hoy === 0 && <Vacio>Hoy nadie avisó falta ni está de viaje.</Vacio>}
        {fv.faltas.length > 0 && (
          <>
            <div className="ini-alerta-titulo neutro">{plural(fv.faltas_hoy, "falta avisada", "faltas avisadas")}</div>
            <ul className="ini-lista">
              {fv.faltas.map((x) => (
                <li key={x.id}><span className="ini-que">{x.alumno}<small>{x.clase}</small></span>
                  <span className={"ini-der" + (x.a_tiempo ? "" : " mal")}>{x.a_tiempo ? "a tiempo" : "fuera de término"}</span></li>
              ))}
            </ul>
          </>
        )}
        {fv.viajes.length > 0 && (
          <>
            <div className="ini-alerta-titulo neutro">{plural(fv.viajes_hoy, "de viaje", "de viaje")}</div>
            <ul className="ini-lista">
              {fv.viajes.map((x) => (
                <li key={x.id}><span className="ini-que">{x.alumno}<small>{x.clase}</small></span>
                  <span className="ini-der">hasta el {fechaCorta(x.hasta)}</span></li>
              ))}
            </ul>
          </>
        )}
      </Tarjeta>

      <ClasesHoy datos={d.clases_hoy} />

      <Tarjeta titulo="Datos incompletos" link="/alumnos?solapa=fichas" linkTxt="Fichas">
        {incompletos.sin_telefono + incompletos.sin_categoria === 0 ? (
          <Vacio>Todos los alumnos tienen teléfono y categoría.</Vacio>
        ) : (
          <div className="ini-numeros">
            <Link to="/alumnos?solapa=fichas&filtro=sin_telefono" className="ini-numero-link">
              <Numero valor={incompletos.sin_telefono} etiqueta="sin teléfono" tono={incompletos.sin_telefono ? "mal" : ""} />
            </Link>
            <Link to="/alumnos?solapa=fichas&filtro=sin_categoria" className="ini-numero-link">
              <Numero valor={incompletos.sin_categoria} etiqueta="sin categoría" tono={incompletos.sin_categoria ? "mal" : ""} />
            </Link>
          </div>
        )}
      </Tarjeta>

      <Tarjeta titulo="Atajos">
        <Atajos items={[["/alumnos?nuevo=1", "+ Nuevo alumno"], ["/cuotas", "Cuotas"]]} />
      </Tarjeta>
    </div>
  );
}

// ---------- profe ----------

const FLECHA = { mas: "▲ más", igual: "= igual", menos: "▼ menos" };

function Comparacion({ titulo, c, antesTxt, sinTarifa }) {
  return (
    <div className="ini-compara">
      <div className="ini-compara-titulo">{titulo}</div>
      <div className="ini-numeros">
        <Numero valor={horasTxt(c.actual.horas)} etiqueta="horas" sub={`${antesTxt}: ${horasTxt(c.antes.horas)}`} />
        {sinTarifa ? (
          <Numero valor="Sin tarifa" etiqueta="lo que ganás" sub="avisale al encargado" />
        ) : (
          <Numero valor={plata(c.actual.monto)} etiqueta="lo que ganás" tono="ok" sub={`${antesTxt}: ${plata(c.antes.monto)}`} />
        )}
      </div>
      <div className={"ini-tendencia " + (sinTarifa ? c.horas : c.monto)}>
        {FLECHA[sinTarifa ? c.horas : c.monto]} que {antesTxt.toLowerCase()}
      </div>
    </div>
  );
}

function InicioProfe({ d }) {
  const hoy = d.hoy;
  const [clases, setClases] = useState(null);
  const [error, setError] = useState("");
  // las de hoy: lo mismo que Mis clases (se abren para ver los que se esperan y marcar)
  useEffect(() => {
    let vigente = true;
    api(`/api/mis-clases?fecha=${hoy}`)
      .then((r) => vigente && setClases(r.clases))
      .catch((e) => { if (vigente) { setError(e.message); setClases([]); } });
    return () => { vigente = false; };
  }, [hoy]);
  const delDia = (clases || []).filter((c) => c.alumnos > 0 || !!c.di_la_clase);
  const h = d.horas;

  return (
    <div className="ini-grilla">
      <Tarjeta titulo="Tus clases de hoy" link="/mis-clases" linkTxt="Mis clases" tono="ancha">
        {error && <div className="msg-error">{error}</div>}
        {clases === null && <div className="nota">Cargando…</div>}
        {clases && !error && delDia.length === 0 && <Vacio>Hoy no tenés clases con alumnos.</Vacio>}
        {delDia.length > 0 && (
          <>
            <div className="nota">Abrí la clase para ver quiénes se esperan y marcar. La hora cuenta cuando marcás al menos un “Vino” (o “Di la clase” en las que tienen apoyo).</div>
            <div className="mc-lista ini-clases">
              {delDia.map((c) => <Clase key={c.id} clase={c} fecha={hoy} futuro={false} abrir={delDia.length <= 3} />)}
            </div>
          </>
        )}
      </Tarjeta>

      <Tarjeta titulo="Tus horas" link="/mis-clases" linkTxt="Detalle">
        {h.sin_tarifa && <div className="nota">Todavía no tenés tarifa cargada: se ven las horas, la plata cuando la carguen.</div>}
        <Comparacion titulo={`Lo que va de ${nombreMes(h.mes.desde)}`} c={h.mes} antesTxt={`Mismos días de ${nombreMes(h.mes.antes_desde)}`} sinTarifa={h.sin_tarifa} />
        <Comparacion titulo="Lo que va de la semana" c={h.semana} antesTxt="Semana anterior" sinTarifa={h.sin_tarifa} />
      </Tarjeta>

      <Tarjeta titulo="Próximas clases" link="/mis-clases" linkTxt="Mis clases">
        {d.proximas.length === 0 ? (
          <Vacio>No tenés clases con alumnos en los próximos días.</Vacio>
        ) : (
          <ul className="ini-lista">
            {d.proximas.map((c) => (
              <li key={`${c.clase_id}-${c.fecha}`}>
                <span className="ini-hora">{diaDe(c.fecha).slice(0, 3)} {fechaCorta(c.fecha)}<small>{c.hora}</small></span>
                <span className="ini-que">{c.tipo}{c.nivel && ` · ${c.nivel}`}{c.apoyo && <small>apoyo</small>}</span>
                <span className="ini-der">{plural(c.esperados, "alumno", "alumnos")}</span>
              </li>
            ))}
          </ul>
        )}
      </Tarjeta>
    </div>
  );
}

// ---------- la pantalla ----------

export default function Inicio() {
  const { usuario } = useAuth();
  const pendientes = useOutletContext() || {}; // los contadores del menú (usePendientes en App)
  const [datos, setDatos] = useState(null);
  const [error, setError] = useState("");
  const [hoy] = useState(() => hoyEn(MARCA.zonaHoraria));

  useEffect(() => {
    let vigente = true;
    api("/api/inicio")
      .then((d) => vigente && setDatos(d))
      .catch((e) => vigente && setError(e.message));
    return () => { vigente = false; };
  }, []);

  const fecha = datos?.hoy || hoy;
  return (
    <>
      <div className="cabecera">
        <div>
          <h1>{saludo()}, {usuario.nombre.split(" ")[0]}</h1>
          <div className="sub">{diaDe(fecha)} {Number(fecha.slice(8))} de {nombreMes(fecha)} · {MARCA.nombre}</div>
        </div>
      </div>
      {/* si no hay vigentes no aparece nada */}
      <NovedadesVigentes />
      {error && <div className="msg-error">{error}</div>}
      {!datos && !error && <div className="nota">Cargando…</div>}
      {datos?.rol === "dueno" && <InicioDueno d={datos} pendientes={pendientes} />}
      {datos?.rol === "encargado" && <InicioEncargado d={datos} pendientes={pendientes} />}
      {datos?.rol === "profe" && <InicioProfe d={datos} />}
    </>
  );
}
