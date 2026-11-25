import { useEffect, useState } from "react";
import { api } from "../api.js";
import { ahora } from "../fechas.js";
import "./altaalumno.css";
import "./profeshoras.css";

// Tarifa por hora de los profes y alta de profes. Solo el dueño (el back frena al resto).
// Una tarifa nueva no pisa las anteriores: cada clase se paga con la tarifa de su fecha.

const plata = (n) => "$" + Number(n).toLocaleString("es-AR", { maximumFractionDigits: 2 });
const fecha = (iso) => (iso ? iso.split("-").reverse().join("/") : "");
const hoyIso = () => {
  const d = ahora();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
const ESTADO = { vigente: "Vigente", futura: "Desde más adelante", vencida: "Anterior" };

// hoja: pantalla completa en celu, modal centrado en compu (mismo estilo que el alta de alumnos)
function Hoja({ titulo, alCerrar, children }) {
  useEffect(() => {
    const tecla = (e) => e.key === "Escape" && alCerrar();
    window.addEventListener("keydown", tecla);
    const antes = document.body.style.overflow;
    document.body.style.overflow = "hidden"; // que no se mueva la página de atrás
    return () => { window.removeEventListener("keydown", tecla); document.body.style.overflow = antes; };
  }, [alCerrar]);
  return (
    <div className="alta-velo">
      <div className="alta-hoja" role="dialog" aria-modal="true" aria-labelledby="ph-hoja-titulo">
        <div className="alta-cabecera">
          <h2 id="ph-hoja-titulo">{titulo}</h2>
          <button type="button" className="alta-cerrar" aria-label="Cerrar" onClick={alCerrar}>×</button>
        </div>
        {children}
      </div>
    </div>
  );
}

// monto + desde, con el aviso de "mes pasado" que pide confirmar
function CamposTarifa({ monto, desde, alCambiar, opcional = false }) {
  return (
    <div className="ph-campos">
      <div className="campo">
        <label htmlFor="ph-monto">Monto por hora{opcional ? " (opcional)" : ""}</label>
        <input id="ph-monto" inputMode="decimal" autoComplete="off" placeholder="Ej. 15000" value={monto}
               onChange={(e) => alCambiar("monto", e.target.value)} />
      </div>
      <div className="campo">
        <label htmlFor="ph-desde">Rige desde{opcional ? " (opcional)" : ""}</label>
        <input id="ph-desde" type="date" value={desde} onChange={(e) => alCambiar("desde", e.target.value)} />
      </div>
    </div>
  );
}

function Confirmar({ texto, guardando, alConfirmar }) {
  return (
    <div className="alta-parecidos" role="alert">
      <p>{texto}</p>
      <button type="button" className="boton chico" disabled={guardando} onClick={alConfirmar}>
        {guardando ? "Guardando…" : "Sí, cargarla igual"}
      </button>
    </div>
  );
}

export function EditarTarifa({ profe, alCerrar }) {
  const [hist, setHist] = useState(null);
  const [f, setF] = useState({ monto: "", desde: hoyIso() });
  const [error, setError] = useState("");
  const [confirmar, setConfirmar] = useState("");
  const [guardando, setGuardando] = useState(false);
  const [cambio, setCambio] = useState(false);
  const cerrar = () => alCerrar(cambio);

  useEffect(() => {
    api(`/api/profes/${profe.profesor_id}/tarifas`).then((d) => setHist(d.tarifas)).catch((e) => setError(e.message));
  }, [profe.profesor_id]);

  async function guardar(e, conf = false) {
    e?.preventDefault();
    setError("");
    setGuardando(true);
    try {
      const r = await api(`/api/profes/${profe.profesor_id}/tarifas`, { metodo: "POST", cuerpo: { ...f, confirmar: conf } });
      setHist(r.tarifas);
      setCambio(true);
      setConfirmar("");
      setF({ monto: "", desde: hoyIso() });
    } catch (err) {
      if (err.status === 409) setConfirmar(err.message);
      else setError(err.message);
    } finally {
      setGuardando(false);
    }
  }

  return (
    <Hoja titulo={`Tarifa de ${profe.nombre}`} alCerrar={cerrar}>
      <form className="alta-form" onSubmit={guardar} noValidate>
        <p className="nota ph-nota">
          La tarifa nueva no pisa las anteriores: cada clase se paga con la que regía ese día.
        </p>
        <CamposTarifa monto={f.monto} desde={f.desde}
                      alCambiar={(k, v) => { setF((x) => ({ ...x, [k]: v })); setConfirmar(""); }} />
        {confirmar && <Confirmar texto={confirmar} guardando={guardando} alConfirmar={() => guardar(null, true)} />}
        {error && <div className="msg-error" role="alert">{error}</div>}
        <div className="alta-pie">
          <button className="boton principal" disabled={guardando || !!confirmar}>{guardando ? "Guardando…" : "Guardar tarifa"}</button>
          <button type="button" className="boton claro" onClick={cerrar}>{cambio ? "Listo" : "Cancelar"}</button>
        </div>
      </form>

      <section className="ph-historial" aria-label="Historial de tarifas">
        <h3>Historial</h3>
        {hist === null && !error && <div className="cargando">Cargando…</div>}
        {hist && hist.length === 0 && <div className="nota">Todavía no tiene ninguna tarifa cargada.</div>}
        {hist && hist.map((t) => (
          <div key={t.id} className={"ph-hist-fila " + t.estado}>
            <b>{plata(t.monto)}<small> / hora</small></b>
            <span>Desde {fecha(t.desde)}{t.hasta ? ` hasta ${fecha(t.hasta)}` : ""}</span>
            <span className={"ph-hist-estado " + t.estado}>{ESTADO[t.estado]}</span>
          </div>
        ))}
      </section>
    </Hoja>
  );
}

export function NuevoProfe({ alCerrar }) {
  const [f, setF] = useState({ nombre: "", head_coach: false, monto: "", desde: "" });
  const [error, setError] = useState("");
  const [confirmar, setConfirmar] = useState("");
  const [guardando, setGuardando] = useState(false);
  const poner = (k, v) => { setF((x) => ({ ...x, [k]: v })); setConfirmar(""); };

  async function guardar(e, conf = false) {
    e?.preventDefault();
    setError("");
    setGuardando(true);
    try {
      const r = await api("/api/profes", { metodo: "POST", cuerpo: { ...f, confirmar: conf } });
      alCerrar(r);
    } catch (err) {
      if (err.status === 409) setConfirmar(err.message);
      else setError(err.message);
      setGuardando(false);
    }
  }

  return (
    <Hoja titulo="Nuevo profe" alCerrar={() => alCerrar(null)}>
      <form className="alta-form" onSubmit={guardar} noValidate>
        <div className="campo">
          <label htmlFor="ph-nombre">Nombre</label>
          <input id="ph-nombre" autoFocus autoComplete="off" maxLength={120} value={f.nombre}
                 onChange={(e) => poner("nombre", e.target.value)} placeholder="Ej. Laura Pérez" />
        </div>
        <label className="alta-check">
          <input type="checkbox" checked={f.head_coach} onChange={(e) => poner("head_coach", e.target.checked)} />
          <span>
            Head Coach
            <small>Sus particulares de mañana se cobran con la tarifa "Head Coach" de Planes y precios.</small>
          </span>
        </label>
        <fieldset className="alta-contactos">
          <legend>Primera tarifa por hora</legend>
          <p className="nota">Opcional: si no la sabés, la cargás después con "Editar tarifa".</p>
          <CamposTarifa monto={f.monto} desde={f.desde} alCambiar={poner} opcional />
        </fieldset>
        {confirmar && <Confirmar texto={confirmar} guardando={guardando} alConfirmar={() => guardar(null, true)} />}
        {error && <div className="msg-error" role="alert">{error}</div>}
        <div className="alta-pie">
          <button className="boton principal" disabled={guardando || !!confirmar}>{guardando ? "Guardando…" : "Guardar profe"}</button>
          <button type="button" className="boton claro" onClick={() => alCerrar(null)} disabled={guardando}>Cancelar</button>
        </div>
      </form>
    </Hoja>
  );
}
