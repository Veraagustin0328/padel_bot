import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { useAuth } from "../auth.jsx";
import { GESTION } from "../roles.js";
import { MARCA } from "../marca.js";
import { diaSemana, diasDeSemana, hoyEn, lunesDe, mesDe, numeroDia, sumarDias, ultimoDiaConClases } from "../fechas.js";
import { NivelAlumno, Punto, etiquetaNivel } from "../niveles.jsx";
import "./misclases.css";
import { NovedadesVigentes } from "./Novedades.jsx";

const DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"];
const MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
  "septiembre", "octubre", "noviembre", "diciembre"];
const SEMANAS_ATRAS = 8; // hasta dónde se puede ir para marcar lo que quedó colgado
const ESTADOS = [
  ["presente", "Presente"],
  ["ausente", "Ausente"],
  ["ausente_avisa", "Avisó"],
];
const TIPOS = { grupal: "Grupal", particular: "Particular", particular_2: "Particular de 2", otro: "Otra" };

const plural = (n, uno, varios) => `${n} ${n === 1 ? uno : varios}`;
// etiqueta de la lista del día -> clase de color
const TAGS = { recupera: "", reemplaza: "", "avisó": " aviso", "de viaje": " viaje" };

// resumen de la clase ese día: el número ya viene con faltas, viajes, reemplazos y recuperaciones
function resumen(c) {
  const extra = [];
  if (c.recuperan) extra.push(plural(c.recuperan, "recupera", "recuperan"));
  if (c.reemplazos) extra.push(plural(c.reemplazos, "reemplazo", "reemplazos"));
  if (c.no_vienen) extra.push(plural(c.no_vienen, "no viene", "no vienen"));
  return [plural(c.alumnos, "alumno", "alumnos"), ...extra].join(" · ");
}

// "9 al 14 de noviembre" o "30 de noviembre al 5 de diciembre"
function rangoSemana(dias) {
  const [a, b] = [dias[0], dias[dias.length - 1]];
  const ma = MESES[mesDe(a)], mb = MESES[mesDe(b)];
  return ma === mb
    ? `${numeroDia(a)} al ${numeroDia(b)} de ${mb}`
    : `${numeroDia(a)} de ${ma} al ${numeroDia(b)} de ${mb}`;
}

function Clase({ clase, fecha, futuro, verProfe }) {
  const [abierta, setAbierta] = useState(false);
  const [datos, setDatos] = useState(null);
  const [error, setError] = useState("");
  const [guardando, setGuardando] = useState({});
  const [notaAbierta, setNotaAbierta] = useState({});

  // si cambia el día, se vuelve a cargar
  useEffect(() => {
    setDatos(null);
    setError("");
    if (!abierta || futuro) return; // el backend no deja ver ni marcar días que no llegaron
    api(`/api/mis-clases/${clase.id}/asistencia?fecha=${fecha}`)
      .then(setDatos)
      .catch((e) => setError(e.message));
  }, [abierta, fecha, futuro, clase.id]);

  function cambiarLocal(alumnoId, cambios) {
    setDatos((d) => ({ ...d, alumnos: d.alumnos.map((a) => (a.id === alumnoId ? { ...a, ...cambios } : a)) }));
  }

  async function guardar(alumno, cambios) {
    const antes = { estado: alumno.estado, nota: alumno.nota };
    const estado = cambios.estado || alumno.estado;
    if (!estado || futuro) return; // la nota sola no alcanza: primero hay que marcar
    cambiarLocal(alumno.id, cambios);
    setGuardando((g) => ({ ...g, [alumno.id]: "…" }));
    setError("");
    try {
      const r = await api(`/api/mis-clases/${clase.id}/asistencia`, {
        metodo: "POST",
        cuerpo: { fecha, alumno_id: alumno.id, estado, ...("nota" in cambios ? { nota: cambios.nota } : {}) },
      });
      cambiarLocal(alumno.id, { estado: r.estado, nota: r.nota });
      setGuardando((g) => ({ ...g, [alumno.id]: "✓" }));
    } catch (e) {
      cambiarLocal(alumno.id, antes);
      setGuardando((g) => ({ ...g, [alumno.id]: "" }));
      setError(`${alumno.nombre}: ${e.message}`);
    }
  }

  // clasificar al nuevo o recategorizar: el back chequea que esté en la lista de esta clase
  async function elegirNivel(alumno, nivel) {
    setError("");
    try {
      const r = await api(`/api/mis-clases/${clase.id}/nivel`, {
        metodo: "POST",
        cuerpo: { fecha, alumno_id: alumno.id, nivel },
      });
      cambiarLocal(alumno.id, { nivel: r.nivel, nivel_declarado: r.nivel_declarado, clasificar: r.clasificar });
      setGuardando((g) => ({ ...g, [alumno.id]: `✓ ${etiquetaNivel(r.nivel)}` }));
    } catch (e) {
      setError(`${alumno.nombre}: ${e.message}`);
      throw e;
    }
  }

  const presentes = datos ? datos.alumnos.filter((a) => a.estado === "presente").length : 0;
  // con la clase abierta se cuenta en vivo (baja al clasificar); cerrada, lo que mandó el back
  const nuevos = datos ? datos.alumnos.filter((a) => a.clasificar).length : clase.nuevos || 0;
  const marcados = datos ? datos.alumnos.filter((a) => a.estado).length : 0;

  return (
    <div className="mc-clase">
      <button className="mc-cabeza" onClick={() => setAbierta(!abierta)} aria-expanded={abierta}>
        <span className="mc-hora">{clase.hora}</span>
        <span className="mc-info">
          <span className="mc-titulo">
            <Punto color={clase.color} hueco={!!clase.nivel} />
            {TIPOS[clase.tipo] || clase.tipo}
            {clase.nivel && ` · ${clase.nivel}`}
          </span>
          <span className="mc-sub">
            {verProfe && clase.profe ? `${clase.profe} · ` : ""}
            {datos
              ? `${presentes} presentes · ${marcados}/${datos.alumnos.length} marcados`
              : resumen(clase)}
          </span>
          {nuevos > 0 && (
            <span className="mc-nuevos">{nuevos === 1 ? "1 nuevo a clasificar" : `${nuevos} nuevos a clasificar`}</span>
          )}
        </span>
        <span className="mc-flecha">{abierta ? "▲" : "▼"}</span>
      </button>

      {abierta && (
        <div className="mc-cuerpo">
          {futuro && <div className="nota">Todavía no llegó este día: la asistencia se marca ese día o después.</div>}
          {error && <div className="msg-error">{error}</div>}
          {!futuro && !datos && !error && <div className="nota">Cargando…</div>}
          {datos && datos.alumnos.length === 0 && <div className="nota">No hay alumnos anotados ese día.</div>}
          {datos?.alumnos.map((a) => (
            <div key={a.id} className={"mc-alumno" + (a.viene === false ? " no-viene" : "")}>
              <div className="mc-nombre">
                <span>{a.nombre}</span>
                {a.etiqueta && <span className={"mc-tag" + (TAGS[a.etiqueta] || "")}>{a.etiqueta}</span>}
                <span className="mc-guardado">{guardando[a.id]}</span>
              </div>
              <NivelAlumno alumno={a} niveles={datos.niveles} colores={datos.colores}
                           onElegir={(n) => elegirNivel(a, n)} />
              <div className="mc-botones">
                {ESTADOS.map(([valor, texto]) => (
                  <button
                    key={valor}
                    className={`mc-estado ${valor}` + (a.estado === valor ? " activo" : "")}
                    aria-pressed={a.estado === valor}
                    disabled={futuro}
                    onClick={() => a.estado !== valor && guardar(a, { estado: valor })}
                  >
                    {texto}
                  </button>
                ))}
              </div>
              {a.estado &&
                (notaAbierta[a.id] || a.nota ? (
                  <input
                    className="mc-nota"
                    placeholder="Nota (opcional)"
                    defaultValue={a.nota}
                    maxLength={255}
                    disabled={futuro}
                    onBlur={(e) => e.target.value.trim() !== a.nota && guardar(a, { nota: e.target.value.trim() })}
                  />
                ) : (
                  <button className="mc-agregar-nota" onClick={() => setNotaAbierta((n) => ({ ...n, [a.id]: true }))}>
                    + nota
                  </button>
                ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function MisClases() {
  const { usuario } = useAuth();
  const verTodas = GESTION.includes(usuario.rol);
  const sinClases = MARCA.diasSinClases || [];
  // "hoy" se calcula una vez al abrir; si queda abierta de un día para el otro, se recarga y listo
  const [hoy] = useState(() => hoyEn(MARCA.zonaHoraria));
  const lunesActual = lunesDe(hoy);
  const lunesMinimo = sumarDias(lunesActual, -7 * SEMANAS_ATRAS);
  // arranca en hoy, o en el último día con clases si hoy no hay (domingo -> sábado)
  const [elegido, setElegido] = useState(() => ultimoDiaConClases(hoy, sinClases));
  const lunes = lunesDe(elegido);
  const dias = diasDeSemana(lunes, sinClases);
  const filaRef = useRef(null);
  const [clases, setClases] = useState(null);
  const [error, setError] = useState("");
  const [verVacias, setVerVacias] = useState(false);

  // el conteo depende del día, así que se pide de nuevo al cambiar de chip
  useEffect(() => {
    let vigente = true;
    setClases(null);
    setError("");
    api(`/api/mis-clases?fecha=${elegido}`)
      .then((d) => vigente && setClases(d.clases))
      .catch((e) => {
        if (!vigente) return;
        setError(e.message);
        setClases([]);
      });
    return () => {
      vigente = false;
    };
  }, [elegido]);

  // si la fila no entra y scrollea, el día elegido queda centrado
  useEffect(() => {
    const fila = filaRef.current;
    const boton = fila?.querySelector(".mc-dia.activo");
    if (fila && boton && fila.scrollWidth > fila.clientWidth) {
      fila.scrollLeft = boton.offsetLeft - (fila.clientWidth - boton.offsetWidth) / 2;
    }
  }, [elegido]);

  // al cambiar de semana se queda en el mismo día de la semana; volviendo a la actual, en hoy
  function irASemana(salto) {
    const nuevoLunes = sumarDias(lunes, 7 * salto);
    if (nuevoLunes < lunesMinimo || nuevoLunes > lunesActual) return;
    if (nuevoLunes === lunesActual) return setElegido(ultimoDiaConClases(hoy, sinClases));
    const mismo = sumarDias(nuevoLunes, diaSemana(elegido));
    setElegido(sinClases.includes(diaSemana(mismo)) ? diasDeSemana(nuevoLunes, sinClases)[0] : mismo);
  }

  const dia = diaSemana(elegido);
  const futuro = elegido > hoy; // AAAA-MM-DD se compara bien como texto
  const delDia = (clases || []).filter((c) => c.dia === dia);
  // se esconden las que no tienen nadie ese día, salvo que pidan verlas
  const conGente = (c) => c.alumnos > 0;
  const vacias = delDia.filter((c) => !conGente(c)).length;
  const visibles = verVacias ? delDia : delDia.filter(conGente);

  return (
    <div className="mc">
      <div className="cabecera">
        <div>
          <h1>Mis clases</h1>
          <div className="sub">
            {DIAS[dia]} {numeroDia(elegido)} de {MESES[mesDe(elegido)]} · tocá un estado y se guarda solo
          </div>
        </div>
      </div>

      {/* el profe no pasa por el Inicio, así que las novedades las ve acá */}
      {usuario.rol === "profe" && <NovedadesVigentes />}

      <div className="mc-semana">
        <button
          className="mc-flecha-semana"
          onClick={() => irASemana(-1)}
          disabled={lunes <= lunesMinimo}
          aria-label="Semana anterior"
        >
          ‹
        </button>
        <div className="mc-semana-centro">
          <div className="mc-rango">{lunes === lunesActual ? "Esta semana" : rangoSemana(dias)}</div>
          <div className="mc-dias" role="tablist" ref={filaRef} style={{ "--n": dias.length }}>
            {dias.map((f) => (
              <button
                key={f}
                role="tab"
                aria-selected={f === elegido}
                className={"mc-dia" + (f === elegido ? " activo" : "") + (f > hoy ? " futuro" : "")}
                onClick={() => setElegido(f)}
              >
                <span>{DIAS[diaSemana(f)].slice(0, 3)}</span>
                <strong>{numeroDia(f)}</strong>
                {f === hoy && <em className="mc-hoy">hoy</em>}
              </button>
            ))}
          </div>
        </div>
        <button
          className="mc-flecha-semana"
          onClick={() => irASemana(1)}
          disabled={lunes >= lunesActual}
          aria-label="Semana siguiente"
        >
          ›
        </button>
      </div>

      {futuro && <div className="mc-aviso-futuro">Todavía no llegó este día. Podés ver las clases, pero la asistencia se marca ese día.</div>}
      {error && <div className="msg-error">{error}</div>}
      {clases === null && <div className="nota">Cargando…</div>}
      {clases && !error && visibles.length === 0 && (
        <div className="mc-vacio">
          {delDia.length > 0
            ? "No hay clases con alumnos este día."
            : verTodas
              ? "No hay clases este día."
              : "No tenés clases este día."}
        </div>
      )}
      <div className="mc-lista">
        {visibles.map((c) => (
          <Clase key={c.id} clase={c} fecha={elegido} futuro={futuro} verProfe={verTodas} />
        ))}
      </div>
      {vacias > 0 && (
        <button className="boton claro mc-ver-todas" onClick={() => setVerVacias(!verVacias)}>
          {verVacias ? "Ocultar las que no tienen alumnos" : `Ver todas (${vacias} sin alumnos)`}
        </button>
      )}
    </div>
  );
}
