import { useEffect, useState } from "react";
import { api } from "../api.js";
import { fechaCorta } from "./Novedades.jsx";
import "./faltas.css";

// el contador del menú se vuelve a pedir cada vez que cambia algo acá
const avisarMenu = () => window.dispatchEvent(new Event("faltas-cambiaron"));

const DIAS = ["Dom", "Lun", "Mar", "Mié", "Jue", "Vie", "Sáb"];
const SOLAPAS = [
  ["pendientes", "Pendientes"],
  ["mes", "Del mes"],
  ["viajes", "Viajes"],
];
const ORIGEN = { alumno: "el alumno", profe: "el profe", encargado: "el encargado", agente: "el agente" };

// "2026-11-12" -> "Jue 12/11" sin que el huso corra el día
function conDia(iso) {
  const [a, m, d] = iso.split("-").map(Number);
  return `${DIAS[new Date(a, m - 1, d).getDay()]} ${String(d).padStart(2, "0")}/${String(m).padStart(2, "0")}`;
}
const hora = (utc) =>
  utc ? new Date(utc).toLocaleString("es-AR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "";
function mesActual() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

// ---------- buscador de alumnos (los de la base, no los de la planilla) ----------

function BuscarAlumno({ id, valor, onElegir, placeholder }) {
  const [texto, setTexto] = useState("");
  const [opciones, setOpciones] = useState([]);

  useEffect(() => {
    if (valor || texto.trim().length < 2) return setOpciones([]);
    let vigente = true;
    const t = setTimeout(() => {
      api(`/api/clases/buscar-alumnos?q=${encodeURIComponent(texto.trim())}`)
        .then((l) => vigente && setOpciones(l))
        .catch(() => {});
    }, 250);
    return () => {
      vigente = false;
      clearTimeout(t);
    };
  }, [texto, valor]);

  if (valor) {
    return (
      <div className="fr-elegido">
        <strong>{valor.nombre}</strong>
        <button type="button" className="boton chico claro" onClick={() => { onElegir(null); setTexto(""); }}>
          Cambiar
        </button>
      </div>
    );
  }
  return (
    <div className="fr-buscar">
      <input id={id} value={texto} placeholder={placeholder} autoComplete="off" onChange={(e) => setTexto(e.target.value)} />
      {opciones.length > 0 && (
        <ul className="fr-opciones">
          {opciones.map((o) => (
            <li key={o.id}>
              <button type="button" onClick={() => onElegir(o)}>{o.nombre}</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ---------- solapa Pendientes ----------

function Pendientes({ avisar }) {
  const [recus, setRecus] = useState(null);
  const [viajes, setViajes] = useState(null);
  const [ocupado, setOcupado] = useState(null);

  async function cargar() {
    try {
      const [r, l] = await Promise.all([api("/api/recuperaciones?estado=pendiente"), api("/api/lapsos")]);
      setRecus(r);
      setViajes(l.filter((x) => x.estado === "pendiente"));
      avisarMenu();
    } catch (e) {
      avisar(e.message, true);
      setRecus([]);
      setViajes([]);
    }
  }
  useEffect(() => {
    cargar();
  }, []);

  async function hacer(clave, fn, ok) {
    setOcupado(clave);
    try {
      await fn();
      avisar(ok);
      await cargar();
    } catch (e) {
      avisar(e.message, true);
    } finally {
      setOcupado(null);
    }
  }

  async function aprobar(x) {
    setOcupado(`r${x.id}`);
    try {
      await api(`/api/recuperaciones/${x.id}/resolver`, { metodo: "POST", cuerpo: { aprobar: true } });
      avisar(`Aprobaste la recuperación de ${x.alumno}`);
      await cargar();
    } catch (e) {
      // si se llenó mientras esperaba, el encargado puede meterla igual
      if (/forzar/i.test(e.message) && window.confirm(`${e.message}. ¿La aprobás igual?`)) {
        await hacer(`r${x.id}`, () => api(`/api/recuperaciones/${x.id}/resolver`, {
          metodo: "POST", cuerpo: { aprobar: true, forzar: true },
        }), `Aprobaste la recuperación de ${x.alumno} (con la clase llena)`);
      } else {
        avisar(e.message, true);
      }
    } finally {
      setOcupado(null);
    }
  }

  if (recus === null) return <p className="nota">Cargando…</p>;
  const nada = recus.length === 0 && viajes.length === 0;

  return (
    <div className="fr-col">
      {nada && <div className="fr-vacio">No hay nada pendiente. Todo al día 👌</div>}

      {recus.length > 0 && <h2 className="fr-titulo">Recuperaciones ({recus.length})</h2>}
      {recus.map((x) => (
        <article key={x.id} className="fr-item">
          <div className="fr-arriba">
            <strong>{x.alumno}</strong>
            <span className="fr-chip pendiente">pendiente</span>
          </div>
          <div>Quiere recuperar el <b>{conDia(x.fecha)}</b> en {x.clase}</div>
          <div className="nota">
            {x.falta ? `Por la falta del ${conDia(x.falta.fecha)}` : "Sin falta asociada"}
            {` · lo pidió ${ORIGEN[x.pedida_por] || x.pedida_por}`}
            {x.creada_en && ` · ${hora(x.creada_en)}`}
          </div>
          {x.fuera_de_regla && <div className="fr-motivo">Fuera de regla: {x.fuera_de_regla}</div>}
          <div className="fr-acciones">
            <button className="boton chico" disabled={ocupado === `r${x.id}`} onClick={() => aprobar(x)}>Aprobar</button>
            <button
              className="boton chico claro"
              disabled={ocupado === `r${x.id}`}
              onClick={() => hacer(`r${x.id}`, () => api(`/api/recuperaciones/${x.id}/resolver`, {
                metodo: "POST", cuerpo: { aprobar: false },
              }), `Rechazaste la recuperación de ${x.alumno}`)}
            >
              Rechazar
            </button>
          </div>
        </article>
      ))}

      {viajes.length > 0 && <h2 className="fr-titulo">Viajes ({viajes.length})</h2>}
      {viajes.map((l) => (
        <article key={l.id} className="fr-item">
          <div className="fr-arriba">
            <strong>{l.alumno}</strong>
            <span className="fr-chip pendiente">pendiente</span>
          </div>
          <div>Del <b>{conDia(l.desde)}</b> al <b>{conDia(l.hasta)}</b> · {l.clase}</div>
          <div className="nota">
            {l.reemplazo ? `Lo reemplaza ${l.reemplazo}` : "Sin reemplazo"}
            {` · lo cargó ${ORIGEN[l.origen] || l.origen}`}
          </div>
          {l.motivo && <div className="nota">“{l.motivo}”</div>}
          <div className="fr-acciones">
            <button
              className="boton chico"
              disabled={ocupado === `l${l.id}`}
              onClick={() => hacer(`l${l.id}`, () => api(`/api/lapsos/${l.id}/confirmar`, { metodo: "POST" }),
                `Confirmaste el viaje de ${l.alumno}`)}
            >
              Aprobar
            </button>
            <button
              className="boton chico claro"
              disabled={ocupado === `l${l.id}`}
              onClick={() => hacer(`l${l.id}`, () => api(`/api/lapsos/${l.id}`, { metodo: "DELETE" }),
                `Rechazaste el viaje de ${l.alumno}`)}
            >
              Rechazar
            </button>
          </div>
        </article>
      ))}
    </div>
  );
}

// ---------- solapa Del mes ----------

function estadoFalta(f) {
  const r = f.recuperacion;
  if (r && r.estado === "confirmada") return ["recuperada", `recuperada el ${conDia(r.fecha)}`];
  if (r && r.estado === "pendiente") return ["pendiente", "recuperación pendiente"];
  return f.a_tiempo ? ["a-tiempo", "a tiempo"] : ["tarde", "tarde"];
}

function DelMes({ avisar }) {
  const [mes, setMes] = useState(mesActual());
  const [faltas, setFaltas] = useState(null);
  const [ocupado, setOcupado] = useState(null);

  useEffect(() => {
    let vigente = true;
    setFaltas(null);
    api(`/api/ausencias?mes=${mes}`)
      .then((l) => vigente && setFaltas(l))
      .catch((e) => {
        if (!vigente) return;
        avisar(e.message, true);
        setFaltas([]);
      });
    return () => {
      vigente = false;
    };
  }, [mes]);

  async function corregir(f) {
    setOcupado(f.id);
    try {
      const nueva = await api(`/api/ausencias/${f.id}`, { metodo: "PATCH", cuerpo: { a_tiempo: !f.a_tiempo } });
      setFaltas((l) => l.map((x) => (x.id === f.id ? nueva : x)));
      avisar(`${f.alumno}: la falta del ${conDia(f.fecha)} quedó ${nueva.a_tiempo ? "a tiempo" : "tarde"}`);
    } catch (e) {
      avisar(e.message, true);
    } finally {
      setOcupado(null);
    }
  }

  const cuenta = (clave) => (faltas || []).filter((f) => estadoFalta(f)[0] === clave).length;

  return (
    <div className="fr-col">
      <div className="campo fr-mes">
        <label htmlFor="fr-mes">Mes</label>
        <input id="fr-mes" type="month" value={mes} onChange={(e) => e.target.value && setMes(e.target.value)} />
      </div>
      {faltas === null && <p className="nota">Cargando…</p>}
      {faltas && faltas.length > 0 && (
        <div className="fr-resumen">
          <span><b>{faltas.length}</b> faltas</span>
          <span><b>{cuenta("a-tiempo")}</b> a tiempo</span>
          <span><b>{cuenta("tarde")}</b> tarde</span>
          <span><b>{cuenta("recuperada")}</b> recuperadas</span>
        </div>
      )}
      {faltas && faltas.length === 0 && <div className="fr-vacio">No hay faltas cargadas este mes.</div>}
      {(faltas || []).map((f) => {
        const [clave, texto] = estadoFalta(f);
        return (
          <article key={f.id} className="fr-item">
            <div className="fr-arriba">
              <strong>{f.alumno}</strong>
              <span className={"fr-chip " + clave}>{texto}</span>
            </div>
            <div><b>{conDia(f.fecha)}</b> · {f.clase}</div>
            <div className="nota">
              {f.avisada_en ? `Avisó ${hora(f.avisada_en)}` : "Sin hora de aviso"}
              {` · la cargó ${ORIGEN[f.origen] || f.origen}`}
              {f.motivo && ` · ${f.motivo}`}
            </div>
            <div className="fr-acciones">
              <button className="boton chico claro" disabled={ocupado === f.id} onClick={() => corregir(f)}>
                {f.a_tiempo ? "Marcar como tarde" : "Marcar a tiempo"}
              </button>
            </div>
          </article>
        );
      })}
    </div>
  );
}

// ---------- solapa Viajes ----------

const VIAJE_VACIO = { alumno: null, desde: "", hasta: "", clase_id: "", reemplazo: null, motivo: "" };

function Viajes({ avisar }) {
  const [lista, setLista] = useState(null);
  const [clases, setClases] = useState([]);
  const [form, setForm] = useState(VIAJE_VACIO);
  const [ocupado, setOcupado] = useState(null);

  async function cargar() {
    try {
      setLista(await api("/api/lapsos"));
      avisarMenu();
    } catch (e) {
      avisar(e.message, true);
      setLista([]);
    }
  }
  useEffect(() => {
    cargar();
    api("/api/clases").then((d) => setClases(d.clases.filter((c) => c.activa))).catch(() => {});
  }, []);

  // solo las clases donde está anotado el alumno elegido
  const susClases = form.alumno ? clases.filter((c) => c.alumnos.some((a) => a.id === form.alumno.id)) : [];
  const nombreClase = (c) => `${["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"][c.dia]} ${c.hora}` +
    (c.profe ? ` · ${c.profe}` : "");

  async function guardar(e) {
    e.preventDefault();
    if (!form.alumno) return avisar("Elegí el alumno", true);
    if (!form.desde || !form.hasta) return avisar("Poné la fecha de ida y la de vuelta", true);
    setOcupado("form");
    try {
      await api("/api/lapsos", {
        metodo: "POST",
        cuerpo: {
          alumno_id: form.alumno.id,
          desde: form.desde,
          hasta: form.hasta,
          clase_id: form.clase_id || null,
          reemplazo_alumno_id: form.reemplazo ? form.reemplazo.id : null,
          motivo: form.motivo,
        },
      });
      avisar(`Listo, cargaste el viaje de ${form.alumno.nombre}`);
      setForm(VIAJE_VACIO);
      await cargar();
    } catch (e) {
      avisar(e.message, true);
    } finally {
      setOcupado(null);
    }
  }

  async function accion(l, fn, ok) {
    setOcupado(l.id);
    try {
      await fn();
      avisar(ok);
      await cargar();
    } catch (e) {
      avisar(e.message, true);
    } finally {
      setOcupado(null);
    }
  }

  return (
    <div className="fr-col">
      <form className="tarjeta fr-form" onSubmit={guardar}>
        <h2>Cargar viaje</h2>
        <div className="campo">
          <label htmlFor="fr-alumno">Alumno</label>
          <BuscarAlumno
            id="fr-alumno"
            valor={form.alumno}
            placeholder="Escribí el nombre"
            onElegir={(a) => setForm({ ...form, alumno: a, clase_id: "" })}
          />
        </div>
        <div className="fr-par">
          <div className="campo">
            <label htmlFor="fr-desde">Se va el</label>
            <input id="fr-desde" type="date" value={form.desde} onChange={(e) => setForm({ ...form, desde: e.target.value })} />
          </div>
          <div className="campo">
            <label htmlFor="fr-hasta">Vuelve el (último día que falta)</label>
            <input id="fr-hasta" type="date" min={form.desde || undefined} value={form.hasta}
              onChange={(e) => setForm({ ...form, hasta: e.target.value })} />
          </div>
        </div>
        <div className="campo">
          <label htmlFor="fr-clase">Clase (opcional)</label>
          <select id="fr-clase" value={form.clase_id} disabled={!form.alumno}
            onChange={(e) => setForm({ ...form, clase_id: e.target.value })}>
            <option value="">Todas sus clases</option>
            {susClases.map((c) => <option key={c.id} value={c.id}>{nombreClase(c)}</option>)}
          </select>
        </div>
        <div className="campo">
          <label htmlFor="fr-reemplazo">Reemplazo (opcional, solo por esas fechas)</label>
          <BuscarAlumno
            id="fr-reemplazo"
            valor={form.reemplazo}
            placeholder="Quién ocupa su lugar"
            onElegir={(a) => setForm({ ...form, reemplazo: a })}
          />
        </div>
        <div className="campo">
          <label htmlFor="fr-motivo">Motivo (opcional)</label>
          <input id="fr-motivo" maxLength={255} value={form.motivo} onChange={(e) => setForm({ ...form, motivo: e.target.value })} />
        </div>
        <div className="botones">
          <button className="boton" disabled={ocupado === "form"}>{ocupado === "form" ? "Guardando…" : "Cargar viaje"}</button>
        </div>
      </form>

      <h2 className="fr-titulo">Vigentes y por venir</h2>
      {lista === null && <p className="nota">Cargando…</p>}
      {lista && lista.length === 0 && <div className="fr-vacio">No hay viajes cargados.</div>}
      {(lista || []).map((l) => (
        <article key={l.id} className="fr-item">
          <div className="fr-arriba">
            <strong>{l.alumno}</strong>
            <span className={"fr-chip " + (l.estado === "pendiente" ? "pendiente" : "a-tiempo")}>{l.estado}</span>
          </div>
          <div>Del <b>{conDia(l.desde)}</b> al <b>{conDia(l.hasta)}</b> · {l.clase}</div>
          <div className="nota">
            {l.reemplazo ? `Lo reemplaza ${l.reemplazo}` : "Sin reemplazo"}
            {l.motivo && ` · ${l.motivo}`}
          </div>
          <div className="fr-acciones">
            {l.estado === "pendiente" && (
              <button className="boton chico" disabled={ocupado === l.id}
                onClick={() => accion(l, () => api(`/api/lapsos/${l.id}/confirmar`, { metodo: "POST" }),
                  `Confirmaste el viaje de ${l.alumno}`)}>
                Confirmar
              </button>
            )}
            <button className="boton chico claro" disabled={ocupado === l.id}
              onClick={() => window.confirm(`¿Borrar el viaje de ${l.alumno} (${fechaCorta(l.desde)} al ${fechaCorta(l.hasta)})?`) &&
                accion(l, () => api(`/api/lapsos/${l.id}`, { metodo: "DELETE" }), `Borraste el viaje de ${l.alumno}`)}>
              Borrar
            </button>
          </div>
        </article>
      ))}
    </div>
  );
}

// ---------- solapa suelta para la pantalla Pendientes ----------

export function FaltasPendientes() {
  const [msg, setMsg] = useState(null);
  const avisar = (texto, error = false) => setMsg({ texto, error });
  return (
    <div className="fr">
      <div className="cabecera">
        <div>
          <h1>Faltas y recuperaciones</h1>
          <div className="sub">Recuperaciones y viajes que esperan tu OK. El historial está en Faltas y viajes.</div>
        </div>
      </div>
      {msg && (
        <div className={msg.error ? "msg-error" : "msg-ok"} role={msg.error ? "alert" : "status"} onClick={() => setMsg(null)}>
          {msg.texto}
        </div>
      )}
      <Pendientes avisar={avisar} />
    </div>
  );
}

// ---------- pantalla ----------

export default function FaltasRecuperaciones() {
  const [solapa, setSolapa] = useState("pendientes");
  const [msg, setMsg] = useState(null);

  const avisar = (texto, error = false) => setMsg({ texto, error });
  const cambiar = (s) => {
    setSolapa(s);
    setMsg(null);
  };

  return (
    <div className="fr">
      <div className="cabecera">
        <div>
          <h1>Faltas y viajes</h1>
          <div className="sub">Lo que se sale de la regla queda acá para que decidas vos.</div>
        </div>
      </div>

      <div className="fr-solapas" role="tablist">
        {SOLAPAS.map(([clave, texto]) => (
          <button key={clave} role="tab" aria-selected={solapa === clave}
            className={"fr-solapa" + (solapa === clave ? " activo" : "")} onClick={() => cambiar(clave)}>
            {texto}
          </button>
        ))}
      </div>

      {msg && (
        <div className={msg.error ? "msg-error" : "msg-ok"} role={msg.error ? "alert" : "status"} onClick={() => setMsg(null)}>
          {msg.texto}
        </div>
      )}

      {solapa === "pendientes" && <Pendientes avisar={avisar} />}
      {solapa === "mes" && <DelMes avisar={avisar} />}
      {solapa === "viajes" && <Viajes avisar={avisar} />}
    </div>
  );
}
