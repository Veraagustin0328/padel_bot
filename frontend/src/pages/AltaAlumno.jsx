import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api.js";
import { etiquetaNivel } from "../niveles.jsx";
import "./altaalumno.css";

// Alta de un alumno nuevo (dueño y encargado). Paso 1: los datos. Paso 2: anotarlo en clases,
// con la cuota del mes en vivo. Anotar usa el mismo pedido que Clases (POST /api/clases/<id>/alumnos).

const DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"];
const DIAS_CORTOS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"];
const MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
  "septiembre", "octubre", "noviembre", "diciembre"];
const TIPOS = { grupal: "Grupal", particular: "Particular", particular_2: "Particular de 2", otro: "Otra", fisico: "Físico" };
const PARENTESCO = { padre: "Padre", madre: "Madre", tutor: "Tutor/a" };
const PLANILLA = { adultos: "Adultos", kids: "Kids" };
// qué clases se le ofrecen según la planilla
const AMBITOS = { adultos: ["adultos", "adultos_tarde", "sabados"], kids: ["kids", "kids_pro"] };
const nombrePlanilla = (p) => PLANILLA[p] || String(p || "").replace(/_/g, " ").replace(/^./, (x) => x.toUpperCase());
const MOTIVO = { mismo_telefono: "mismo teléfono", nombre_parecido: "nombre parecido" };
const peso = new Intl.NumberFormat("es-AR", { style: "currency", currency: "ARS", maximumFractionDigits: 0 });
const VACIO = { nombre: "", planilla: "adultos", nivel: "", telefono: "", contactos: [], tarifa_head_coach: false, inscripcion: "cobrar" };
const CONTACTO = { nombre: "", parentesco: "", telefono: "" };

// mismo criterio que el back (alumnos_alta.normalizar_telefono): 549 + característica + número
export function normalizarTelefono(texto) {
  let d = String(texto || "").replace(/\D/g, "");
  if (d.startsWith("00")) d = d.slice(2);
  if (d.length === 13 && d.startsWith("549")) return d;
  if (d.length === 12 && d.startsWith("54")) d = d.slice(2);
  else if (d.length === 11 && d.startsWith("0")) d = d.slice(1);
  return d.length === 10 && "123".includes(d[0]) ? "549" + d : null;
}

// ayuda debajo de cada teléfono: cómo se va a guardar, o qué le falta
function AyudaTel({ valor }) {
  if (!valor.trim()) return null;
  const t = normalizarTelefono(valor);
  return t
    ? <span className="alta-tel-ok">Se guarda como {t}</span>
    : <span className="alta-tel-mal">Característica y número, sin 0 ni 15 (ej. 2614567890)</span>;
}

function Parecidos({ lista, alConfirmar, guardando }) {
  if (!lista.length) return null;
  const soloTel = lista.every((p) => p.motivos.length === 1 && p.motivos[0] === "mismo_telefono");
  return (
    <div className="alta-parecidos" role="alert">
      <b>{alConfirmar ? "Antes de guardar, fijate:" : "Ojo, ya hay alumnos parecidos:"}</b>
      <ul>
        {lista.map((p) => (
          <li key={p.id}>
            <span className="alta-par-nombre">{p.nombre}</span>
            <span className="alta-par-datos">
              {nombrePlanilla(p.planilla)}{p.estado === "baja" ? " · de baja" : ""} · {p.motivos.map((m) => MOTIVO[m] || m).join(" y ")}
            </span>
          </li>
        ))}
      </ul>
      <p>{soloTel ? "Si son hermanos que comparten el teléfono de los papás, está bien: guardalo igual." : "Si es la misma persona, no lo cargues de nuevo: buscalo en Fichas."}</p>
      {alConfirmar && (
        <button type="button" className="boton chico" disabled={guardando} onClick={alConfirmar}>
          {guardando ? "Guardando…" : "Es otra persona, guardar igual"}
        </button>
      )}
    </div>
  );
}

function Formulario({ opciones, alGuardar, alCerrar }) {
  const [f, setF] = useState(VACIO);
  const [parecidos, setParecidos] = useState([]);
  const [pedirConfirmar, setPedirConfirmar] = useState(false);
  const [error, setError] = useState("");
  const [guardando, setGuardando] = useState(false);
  const ultimo = useRef("");
  const esKids = (opciones.planillas_menores || []).includes(f.planilla);
  const poner = (campo, valor) => { setF((x) => ({ ...x, [campo]: valor })); setPedirConfirmar(false); };

  // parecidos mientras se completa: espera a que deje de tipear
  const clave = JSON.stringify([f.nombre.trim(), f.telefono, f.contactos.map((c) => c.telefono)]);
  useEffect(() => {
    if (f.nombre.trim().length < 3 && ![f.telefono, ...f.contactos.map((c) => c.telefono)].some(normalizarTelefono)) {
      setParecidos([]);
      return;
    }
    const t = setTimeout(async () => {
      ultimo.current = clave;
      try {
        const r = await api("/api/alumnos/alta/chequear", {
          metodo: "POST", cuerpo: { nombre: f.nombre, telefono: f.telefono, contactos: f.contactos },
        });
        if (ultimo.current === clave) setParecidos(r.parecidos || []);
      } catch {
        /* el chequeo es una ayuda: si falla, el guardado vuelve a mirar */
      }
    }, 450);
    return () => clearTimeout(t);
  }, [clave]);

  function cambiarPlanilla(p) {
    setF((x) => ({ ...x, planilla: p, contactos: (opciones.planillas_menores || []).includes(p) ? (x.contactos.length ? x.contactos : [{ ...CONTACTO }]) : [] }));
    setPedirConfirmar(false);
  }
  const cambiarContacto = (i, c) => poner("contactos", f.contactos.map((x, j) => (j === i ? c : x)));

  async function guardar(e, confirmar = false) {
    e?.preventDefault();
    setError("");
    setGuardando(true);
    try {
      const contactos = f.contactos.filter((c) => c.telefono.trim() || c.nombre.trim());
      const r = await api("/api/alumnos", { metodo: "POST", cuerpo: { ...f, contactos, confirmar } });
      alGuardar(r.alumno);
    } catch (err) {
      if (err.status === 409) {
        // el back volvió a encontrar parecidos: los muestro con el botón para confirmar
        try {
          const r = await api("/api/alumnos/alta/chequear", { metodo: "POST", cuerpo: { nombre: f.nombre, telefono: f.telefono, contactos: f.contactos } });
          setParecidos(r.parecidos || []);
        } catch { /* quedan los que había */ }
        setPedirConfirmar(true);
      } else {
        setError(err.message);
      }
      setGuardando(false);
    }
  }

  const insc = opciones.inscripcion || {};
  return (
    <form className="alta-form" onSubmit={guardar} noValidate>
      <div className="campo">
        <label htmlFor="alta-nombre">Nombre y apellido</label>
        <input id="alta-nombre" autoFocus autoComplete="off" maxLength={120} value={f.nombre}
               onChange={(e) => poner("nombre", e.target.value)} placeholder="Ej. Martina López" />
      </div>

      <div className="campo">
        <span className="alta-etiqueta">Planilla</span>
        <div className="alta-segmentos" role="radiogroup" aria-label="Planilla">
          {opciones.planillas.map((p) => (
            <button key={p} type="button" role="radio" aria-checked={f.planilla === p}
                    className={"alta-segmento" + (f.planilla === p ? " activo" : "")} onClick={() => cambiarPlanilla(p)}>
              {PLANILLA[p] || p}
            </button>
          ))}
        </div>
      </div>

      <div className="campo">
        <label htmlFor="alta-nivel">Categoría / nivel{esKids ? " (opcional)" : ""}</label>
        <select id="alta-nivel" value={f.nivel} onChange={(e) => poner("nivel", e.target.value)}>
          <option value="">{esKids ? "Sin nivel" : "Elegí…"}</option>
          {opciones.niveles.map((n) => <option key={n} value={n}>{etiquetaNivel(n)}</option>)}
        </select>
        {f.nivel && <span className="nota">Queda “a clasificar” hasta que su profe lo confirme en Mis clases.</span>}
      </div>

      <div className="campo">
        <label htmlFor="alta-tel">Teléfono {esKids ? "del chico (opcional)" : "del alumno"}</label>
        <input id="alta-tel" inputMode="tel" autoComplete="off" value={f.telefono}
               onChange={(e) => poner("telefono", e.target.value)} placeholder="Ej. 2614567890" />
        <AyudaTel valor={f.telefono} />
      </div>

      {esKids && (
        <fieldset className="alta-contactos">
          <legend>Padre, madre o tutor</legend>
          <p className="nota">Desde estos números el agente reconoce al chico. Hasta {opciones.max_tutores}.</p>
          {f.contactos.map((c, i) => (
            <div key={i} className="alta-contacto">
              <div className="alta-contacto-campos">
                <label>
                  Nombre
                  <input value={c.nombre} maxLength={80} placeholder="Ej. Laura"
                         onChange={(e) => cambiarContacto(i, { ...c, nombre: e.target.value })} />
                </label>
                <label>
                  Parentesco
                  <select value={c.parentesco} onChange={(e) => cambiarContacto(i, { ...c, parentesco: e.target.value })}>
                    <option value="">Elegí…</option>
                    {opciones.parentescos.map((p) => <option key={p} value={p}>{PARENTESCO[p] || p}</option>)}
                  </select>
                </label>
                <label className="alta-contacto-tel">
                  Teléfono
                  <input inputMode="tel" value={c.telefono} placeholder="Ej. 2614567890"
                         onChange={(e) => cambiarContacto(i, { ...c, telefono: e.target.value })} />
                  <AyudaTel valor={c.telefono} />
                </label>
              </div>
              <button type="button" className="boton chico claro" onClick={() => poner("contactos", f.contactos.filter((_, j) => j !== i))}>
                Sacar
              </button>
            </div>
          ))}
          {f.contactos.length < opciones.max_tutores && (
            <button type="button" className="boton chico claro" onClick={() => poner("contactos", [...f.contactos, { ...CONTACTO }])}>
              + Agregar padre, madre o tutor
            </button>
          )}
        </fieldset>
      )}

      {opciones.hay_head_coach && (
        <label className="alta-check">
          <input type="checkbox" checked={f.tarifa_head_coach} onChange={(e) => poner("tarifa_head_coach", e.target.checked)} />
          <span>
            Tarifa Head Coach
            <small>Solo si es nuevo y pidió clases con el Head Coach.</small>
          </span>
        </label>
      )}

      <div className="campo">
        <span className="alta-etiqueta">Inscripción (pago único)</span>
        <label className="alta-radio">
          <input type="radio" name="alta-insc" checked={f.inscripcion === "cobrar"} onChange={() => poner("inscripcion", "cobrar")} />
          <span>
            Cobrarla este mes{insc.monto ? ` (${peso.format(insc.monto)})` : ""}
            {!insc.configurada && <small className="alta-tel-mal">No está cargado el monto: avisale al dueño o elegí la otra.</small>}
          </span>
        </label>
        <label className="alta-radio">
          <input type="radio" name="alta-insc" checked={f.inscripcion === "ya_estaba"} onChange={() => poner("inscripcion", "ya_estaba")} />
          <span>Ya estaba inscripto (no se cobra)</span>
        </label>
      </div>

      <Parecidos lista={parecidos} guardando={guardando} alConfirmar={pedirConfirmar ? () => guardar(null, true) : null} />
      {error && <div className="msg-error" role="alert">{error}</div>}

      <div className="alta-pie">
        <button className="boton principal" disabled={guardando || pedirConfirmar}>{guardando ? "Guardando…" : "Guardar alumno"}</button>
        <button type="button" className="boton claro" onClick={alCerrar} disabled={guardando}>Cancelar</button>
      </div>
    </form>
  );
}

// paso 2: elegir clases y ver la cuota del mes antes de anotarlo
function AnotarEnClases({ alumno, alTerminar }) {
  const [clases, setClases] = useState(null);
  const [error, setError] = useState("");
  const [elegidas, setElegidas] = useState([]);
  const [dia, setDia] = useState("todos");
  const [soloNivel, setSoloNivel] = useState(!!alumno.categoria);
  const [cuota, setCuota] = useState(null);
  const [anotando, setAnotando] = useState(false);
  const [listo, setListo] = useState(null); // {anotadas, fallas}

  useEffect(() => {
    api("/api/clases")
      .then((r) => setClases(r.clases.filter((c) => c.activa && !c.apoyo_de && (AMBITOS[alumno.planilla] || []).includes(c.ambito))))
      .catch((e) => { setError(e.message); setClases([]); });
  }, [alumno.planilla]);

  // cuota en vivo: sin guardar nada
  useEffect(() => {
    let vale = true;
    setCuota(null); // "Calculando…" mientras vuelve (Neon puede tardar)
    api(`/api/alumnos/${alumno.id}/cotizar`, { metodo: "POST", cuerpo: { clase_ids: elegidas } })
      .then((r) => vale && setCuota(r))
      .catch((e) => vale && setCuota({ error: e.message }));
    return () => { vale = false; };
  }, [elegidas, alumno.id]);

  const dias = useMemo(() => [...new Set((clases || []).map((c) => c.dia))].sort(), [clases]);
  const nivel = String(alumno.categoria || "").toUpperCase();
  const lista = (clases || []).filter((c) =>
    (dia === "todos" || c.dia === dia)
    && (!soloNivel || !nivel || !c.nivel || c.nivel.toUpperCase().split(/[/\-\s]+/).includes(nivel) || elegidas.includes(c.id)));
  const porDia = lista.reduce((acc, c) => ({ ...acc, [c.dia]: [...(acc[c.dia] || []), c] }), {});
  const alternar = (id) => setElegidas((l) => (l.includes(id) ? l.filter((x) => x !== id) : [...l, id]));

  async function anotar() {
    setAnotando(true);
    setError("");
    const anotadas = [], fallas = [];
    for (const id of elegidas) {
      const c = clases.find((x) => x.id === id);
      try {
        await api(`/api/clases/${id}/alumnos`, { metodo: "POST", cuerpo: { alumno_id: alumno.id } });
        anotadas.push(c);
      } catch (e) {
        fallas.push({ c, error: e.message });
      }
    }
    setAnotando(false);
    setListo({ anotadas, fallas });
  }

  const texto = (c) => `${DIAS[c.dia]} ${c.hora}`;
  const mes = cuota?.mes ? MESES[Number(cuota.mes.slice(5, 7)) - 1] : "";
  const cuotaVivo = (
    <div className="alta-cuota" aria-live="polite">
      {!cuota ? <span className="nota">Calculando…</span>
        : cuota.error ? <span className="alta-tel-mal">{cuota.error}</span>
        : cuota.precio !== null ? (
          <>
            <span>Cuota de {mes}</span>
            <b>{peso.format(cuota.precio)}</b>
          </>
        ) : cuota.sin_tarifa ? (
          <span className="alta-tel-mal">Sin tarifa exacta para estas clases: la cuota la define el dueño.</span>
        ) : <span className="nota">Elegí sus clases para ver la cuota del mes.</span>}
    </div>
  );

  if (listo) {
    return (
      <div className="alta-paso2">
        {listo.anotadas.length > 0 && (
          <div className="msg-ok" role="status">
            Listo, {alumno.nombre} quedó anotado en {listo.anotadas.map(texto).join(", ")}.
          </div>
        )}
        {listo.fallas.map((x) => (
          <div key={x.c.id} className="msg-error" role="alert">{texto(x.c)}: {x.error}</div>
        ))}
        {cuotaVivo}
        <p className="nota">Si la cuota de {mes} ya estaba generada, en Cuotas tocá “Generar” de nuevo: le arma la suya sin tocar las demás.</p>
        <div className="alta-pie">
          <button className="boton principal" onClick={() => alTerminar(true)}>Listo</button>
        </div>
      </div>
    );
  }

  return (
    <div className="alta-paso2">
      <div className="msg-ok" role="status">Listo, guardé a {alumno.nombre}. ¿Lo anotás en sus clases?</div>
      {error && <div className="msg-error" role="alert">{error}</div>}

      <div className="alta-filtros" role="group" aria-label="Filtrar por día">
        <button type="button" className={"alta-chip" + (dia === "todos" ? " activo" : "")} onClick={() => setDia("todos")}>Todos</button>
        {dias.map((d) => (
          <button key={d} type="button" className={"alta-chip" + (dia === d ? " activo" : "")} onClick={() => setDia(d)}>{DIAS_CORTOS[d]}</button>
        ))}
        {nivel && (
          <label className="alta-chip alta-chip-check">
            <input type="checkbox" checked={soloNivel} onChange={(e) => setSoloNivel(e.target.checked)} />
            Solo {etiquetaNivel(nivel)}
          </label>
        )}
      </div>

      {clases === null ? <div className="cargando">Cargando clases…</div>
        : lista.length === 0 ? <div className="nota alta-vacio">No hay clases con esos filtros.</div>
        : (
          <div className="alta-clases">
            {Object.entries(porDia).map(([d, cs]) => (
              <section key={d}>
                <h3>{DIAS[d]}</h3>
                {cs.map((c) => {
                  const ocupados = c.alumnos.length;
                  const lleno = ocupados >= c.cupo;
                  const sel = elegidas.includes(c.id);
                  return (
                    <label key={c.id} className={"alta-clase" + (sel ? " elegida" : "") + (lleno ? " llena" : "")}
                           style={c.color ? { "--color-clase": c.color } : undefined}>
                      <input type="checkbox" checked={sel} onChange={() => alternar(c.id)} />
                      <span className="alta-clase-hora">{c.hora}</span>
                      <span className="alta-clase-datos">
                        <b>{TIPOS[c.tipo] || c.tipo}{c.nivel ? ` · ${c.nivel}` : ""}</b>
                        <span>{c.profe || "Sin profe"}{c.ambito !== alumno.planilla ? ` · ${c.ambito.replace("_", " ")}` : ""}</span>
                      </span>
                      <span className={"alta-clase-cupo" + (lleno ? " lleno" : "")}>{lleno ? "Llena" : `${ocupados}/${c.cupo}`}</span>
                    </label>
                  );
                })}
              </section>
            ))}
          </div>
        )}

      <div className="alta-barra">
        {cuotaVivo}
        <div className="alta-pie">
          <button className="boton principal" disabled={!elegidas.length || anotando} onClick={anotar}>
            {anotando ? "Anotando…" : elegidas.length ? `Anotar en ${elegidas.length} clase${elegidas.length === 1 ? "" : "s"}` : "Elegí sus clases"}
          </button>
          <button type="button" className="boton claro" disabled={anotando} onClick={() => alTerminar(true)}>Ahora no</button>
        </div>
      </div>
    </div>
  );
}

// la hoja: en celu ocupa toda la pantalla, en compu es un modal centrado
export default function AltaAlumno({ alCerrar }) {
  const [opciones, setOpciones] = useState(null);
  const [error, setError] = useState("");
  const [alumno, setAlumno] = useState(null);
  const [cambios, setCambios] = useState(false);

  useEffect(() => {
    api("/api/alumnos/alta/opciones").then(setOpciones).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    const tecla = (e) => e.key === "Escape" && !alumno && alCerrar(cambios);
    window.addEventListener("keydown", tecla);
    // que no se mueva la página de atrás
    const antes = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { window.removeEventListener("keydown", tecla); document.body.style.overflow = antes; };
  }, [alumno, cambios, alCerrar]);

  return (
    <div className="alta-velo">
      <div className="alta-hoja" role="dialog" aria-modal="true" aria-labelledby="alta-titulo">
        <div className="alta-cabecera">
          <h2 id="alta-titulo">{alumno ? `Anotar a ${alumno.nombre}` : "Nuevo alumno"}</h2>
          <button type="button" className="alta-cerrar" aria-label="Cerrar" onClick={() => alCerrar(cambios || !!alumno)}>×</button>
        </div>
        {error && <div className="msg-error" role="alert">{error}</div>}
        {!opciones && !error && <div className="cargando">Cargando…</div>}
        {opciones && !alumno && (
          <Formulario opciones={opciones} alCerrar={() => alCerrar(false)}
                      alGuardar={(a) => { setAlumno(a); setCambios(true); }} />
        )}
        {alumno && <AnotarEnClases alumno={alumno} alTerminar={() => alCerrar(true)} />}
      </div>
    </div>
  );
}
