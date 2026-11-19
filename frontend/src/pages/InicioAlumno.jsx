import { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";
import { useAuth } from "../auth.jsx";
import { MARCA, cargarFuenteTitulos } from "../marca.js";
import { ahora, hoyEn, sumarDias } from "../fechas.js";
import Logo from "../Logo.jsx";
import { NovedadesVigentes } from "./Novedades.jsx";
import SelectorAlumno, { useAlumnoElegido } from "./SelectorAlumno.jsx";

const MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
  "octubre", "noviembre", "diciembre"];

const plata = (n) => "$" + Number(n || 0).toLocaleString("es-AR");

// saludo con la hora del club, no la del celu del que mira
function saludo(momento = ahora()) {
  const hora = Number(new Intl.DateTimeFormat("en-US", {
    timeZone: MARCA.zonaHoraria, hour: "numeric", hourCycle: "h23",
  }).format(momento));
  if (hora >= 5 && hora < 12) return "Buen día";
  if (hora >= 12 && hora < 20) return "Buenas tardes";
  return "Buenas noches";
}

// "hoy", "mañana" o "martes 3/11"
function cuandoEs(clase) {
  const hoy = hoyEn(MARCA.zonaHoraria);
  if (clase.fecha === hoy) return "Hoy";
  if (clase.fecha === sumarDias(hoy, 1)) return "Mañana";
  const [, m, d] = clase.fecha.split("-").map(Number);
  return `${clase.dia} ${d}/${m}`;
}

// textos en 2ª persona (lo propio) o 3ª (un hijo/a): todo sale de acá
function textos(alumno) {
  const pila = alumno.nombre_pila;
  if (alumno.vinculo === "propio") {
    return {
      intro: "Así venís",
      proxima: "Tu próxima clase",
      semana: "Tu semana",
      sinClases: "No tenés clases en los próximos días.",
      cuota: "Tu cuota",
      pago: (c) => `Pagaste ${plata(c.pagado)} de ${plata(c.cuota)}.`,
      recus: "Tus recuperaciones",
      sinRecus: "Ya usaste la de este mes.",
    };
  }
  return {
    intro: `Así viene ${pila}`,
    proxima: `Próxima clase de ${pila}`,
    semana: `Semana de ${pila}`,
    sinClases: `${pila} no tiene clases en los próximos días.`,
    cuota: `Cuota de ${pila}`,
    pago: (c) => `Pagó ${plata(c.pagado)} de ${plata(c.cuota)}.`,
    recus: `Recuperaciones de ${pila}`,
    sinRecus: `${pila} ya usó la de este mes.`,
  };
}

// etiqueta de cada clase de la semana según su estado (el backend ya aplicó las reglas)
const ETIQUETA = { paso: "Ya pasó", proxima: "Próxima", falta: "Avisó falta", viaje: "Viaje" };

function diaCorto(clase) {
  const [, m, d] = clase.fecha.split("-").map(Number);
  return `${clase.dia.slice(0, 3)} ${d}/${m}`;
}

function FilaSemana({ clase }) {
  const { estado } = clase;
  const tachada = estado === "falta" || estado === "viaje";
  return (
    <li className={"alu-sem-fila est-" + estado}>
      <span className="alu-sem-dia">{diaCorto(clase)}</span>
      <span className="alu-sem-cuerpo">
        <span className={"alu-sem-hora" + (tachada ? " tachada" : "")}>{clase.hora} a {clase.hora_fin} hs</span>
        <span className="alu-sem-detalle">
          {[clase.nivel && `Nivel ${clase.nivel}`, clase.profe && `con ${clase.profe}`].filter(Boolean).join(" · ")}
        </span>
      </span>
      <span className="alu-sem-chips">
        {ETIQUETA[estado] && <span className={"alu-sem-chip chip-" + estado}>{ETIQUETA[estado]}</span>}
        {clase.recuperacion && <span className="alu-sem-chip chip-recu">Recuperación</span>}
      </span>
    </li>
  );
}

// toda la semana (lunes a domingo, hora del club). Con una sola clase queda la tarjeta de siempre
function TarjetaSemana({ semana, proxima, t }) {
  const unaSola = semana.length <= 1 && !semana.some((c) => c.estado === "falta" || c.estado === "viaje");
  if (unaSola) return <TarjetaProxima clase={proxima} t={t} />;
  const proximaEnSemana = semana.some((c) => c.estado === "proxima");
  return (
    <section className="tarjeta alu-tarjeta alu-semana" aria-labelledby="alu-sem">
      <h2 id="alu-sem" className="alu-etiqueta">{t.semana}</h2>
      <ul className="alu-sem-lista">
        {semana.map((c) => <FilaSemana key={c.fecha + c.hora + c.recuperacion} clase={c} />)}
      </ul>
      {/* la próxima cae la semana que viene (o no hay): igual se muestra */}
      {!proximaEnSemana && (proxima ? (
        <>
          <div className="alu-sem-sub">La semana que viene</div>
          <ul className="alu-sem-lista">
            <FilaSemana clase={{ ...proxima, estado: "proxima" }} />
          </ul>
        </>
      ) : <p className="alu-vacio">{t.sinClases}</p>)}
    </section>
  );
}

function TarjetaProxima({ clase, t }) {
  return (
    <section className="tarjeta alu-tarjeta" aria-labelledby="alu-prox">
      <h2 id="alu-prox" className="alu-etiqueta">{t.proxima}</h2>
      {clase ? (
        <>
          <div className="alu-grande">{cuandoEs(clase)}</div>
          <div className="alu-linea-fuerte">{clase.hora} a {clase.hora_fin} hs</div>
          <div className="alu-detalle">
            {[clase.nivel && `Nivel ${clase.nivel}`, clase.profe && `con ${clase.profe}`].filter(Boolean).join(" · ")}
          </div>
          {clase.recuperacion && <span className="alu-chip-estado">Recuperación</span>}
        </>
      ) : (
        <p className="alu-vacio">{t.sinClases}</p>
      )}
    </section>
  );
}

function TarjetaCuota({ cuota, t }) {
  const mes = MESES[Number(cuota.mes.split("-")[1]) - 1];
  return (
    <section className="tarjeta alu-tarjeta" aria-labelledby="alu-cuota">
      <h2 id="alu-cuota" className="alu-etiqueta">{t.cuota} · {mes}</h2>
      {cuota.estado === "pago" && (
        <>
          <div className="alu-grande alu-ok">Pagó</div>
          <div className="alu-detalle">{plata(cuota.cuota)} · al día</div>
        </>
      )}
      {cuota.estado === "debe" && (
        <>
          <div className="alu-grande alu-mal">Debe {plata(cuota.debe)}</div>
          <div className="alu-detalle">
            {cuota.pagado > 0 ? t.pago(cuota) : `La cuota es de ${plata(cuota.cuota)}.`}
          </div>
        </>
      )}
      {cuota.estado === "sin_cargar" && <p className="alu-vacio">Todavía no está cargada.</p>}
    </section>
  );
}

function TarjetaRecus({ recus, t }) {
  return (
    <section className="tarjeta alu-tarjeta" aria-labelledby="alu-recus">
      <h2 id="alu-recus" className="alu-etiqueta">{t.recus}</h2>
      {recus.tope == null ? (
        <div className="alu-detalle">Sin tope por mes.</div>
      ) : (
        <>
          <div className={"alu-grande" + (recus.disponibles > 0 ? " alu-acento" : " alu-apagado")}>
            {recus.disponibles}
            <span className="alu-de"> de {recus.tope}</span>
          </div>
          <div className="alu-detalle">{recus.disponibles > 0 ? "Disponibles este mes." : t.sinRecus}</div>
        </>
      )}
    </section>
  );
}

function Reglas({ politicas }) {
  if (!politicas || politicas.length === 0) return null;
  return (
    <details className="tarjeta alu-reglas">
      <summary>
        <span className="alu-etiqueta">Reglas de la academia</span>
        <span className="alu-flecha" aria-hidden="true">›</span>
      </summary>
      <div className="alu-reglas-cuerpo">
        {politicas.map((s) => (
          <div key={s.titulo} className="alu-regla">
            {s.titulo && <h3>{s.titulo}</h3>}
            <ul>
              {s.items.map((i) => <li key={i}>{i}</li>)}
            </ul>
          </div>
        ))}
      </div>
    </details>
  );
}

export default function InicioAlumno() {
  const { usuario } = useAuth();
  const [alumnos, setAlumnos] = useState(null);
  const [info, setInfo] = useState({ politicas: [], nombre_academia: null });
  const [resumen, setResumen] = useState(null);
  const [error, setError] = useState("");
  const [elegido, elegir] = useAlumnoElegido(alumnos);

  useEffect(() => { cargarFuenteTitulos(); }, []);

  useEffect(() => {
    api("/api/yo/alumnos").then(setAlumnos).catch((e) => setError(e.message));
    // si fallan las políticas, el Inicio sigue sin esa sección
    api("/api/yo/politicas").then(setInfo).catch(() => {});
  }, []);

  const cargar = useCallback(() => {
    if (!elegido) return;
    setError("");
    setResumen(null);
    api(`/api/yo/alumnos/${elegido}/resumen`).then(setResumen).catch((e) => setError(e.message));
  }, [elegido]);
  useEffect(cargar, [cargar]);

  const club = info.nombre_academia || MARCA.nombre;
  const t = resumen ? textos(resumen.alumno) : null;

  return (
    <div className="alu">
      <header className="alu-cabecera">
        <div className="alu-club">
          <span className="alu-logo"><Logo tam={28} /></span>
          <span>{club}</span>
        </div>
        <h1 className="alu-saludo">{saludo()}, {usuario.nombre.split(" ")[0]}</h1>
        {t && <p className="alu-intro">{t.intro} en {club}.</p>}
      </header>

      <SelectorAlumno alumnos={alumnos} elegido={elegido} onElegir={elegir} />

      {error && (
        <div className="msg-error" role="alert">
          {error}
          <button className="boton chico claro alu-reintentar" onClick={cargar}>Reintentar</button>
        </div>
      )}
      {alumnos && alumnos.length === 0 && (
        <p className="tarjeta alu-vacio">Todavía no tenés alumnos vinculados. Pedíselo al encargado.</p>
      )}
      {elegido && !resumen && !error && <p className="alu-cargando" role="status">Cargando…</p>}

      {resumen && (
        <div className="alu-grilla">
          <TarjetaSemana semana={resumen.semana || []} proxima={resumen.proxima_clase} t={t} />
          <TarjetaCuota cuota={resumen.cuota} t={t} />
          <TarjetaRecus recus={resumen.recuperaciones} t={t} />
        </div>
      )}

      {/* ya filtradas por audiencia en el backend; si no hay vigentes no aparece */}
      <NovedadesVigentes />
      <Reglas politicas={info.politicas} />
    </div>
  );
}
