import { useEffect, useState } from "react";
import { api } from "../api.js";
import "./faltas.css";

// el contador del menú se vuelve a pedir cada vez que cambia algo acá
const avisarMenu = () => window.dispatchEvent(new Event("cambios-cambiaron"));

const DIAS = ["Dom", "Lun", "Mar", "Mié", "Jue", "Vie", "Sáb"];
const ORIGEN = { alumno: "el alumno por WhatsApp", encargado: "el encargado", panel: "el panel" };

// "2026-12-01" -> "Mar 01/12" sin que el huso corra el día
function conDia(iso) {
  if (!iso) return "";
  const [a, m, d] = iso.split("-").map(Number);
  return `${DIAS[new Date(a, m - 1, d).getDay()]} ${String(d).padStart(2, "0")}/${String(m).padStart(2, "0")}`;
}
const pesos = (n) => (n ? "$" + Number(n).toLocaleString("es-AR") : "sin tarifa exacta");
const lista = (l) => (l.length ? l.join(", ") : "nada");

function Cambio({ x, ocupado, onAprobar, onRechazar, soloLectura }) {
  const [rechazando, setRechazando] = useState(false);
  const [motivo, setMotivo] = useState("");

  return (
    <article className="fr-item">
      <div className="fr-arriba">
        <strong>{x.alumno}</strong>
        <span className="fr-chip pendiente">{soloLectura ? "espera al alumno" : "pendiente"}</span>
      </div>
      <div>Desde el <b>{conDia(x.vigente_desde)}</b></div>
      <div>Deja: {lista(x.deja)}</div>
      <div>Pasa a: <b>{lista(x.nuevas)}</b></div>
      <div className="nota">
        Hoy viene {lista(x.actuales)} · Cuota {pesos(x.cuota_actual)} → <b>{pesos(x.cuota_nueva)}</b>
      </div>
      <div className="nota">Lo pidió {ORIGEN[x.origen] || x.origen || "?"}</div>
      {x.sin_lugar.length > 0 && (
        <div className="fr-motivo">Ya no hay lugar en {lista(x.sin_lugar)}: no se puede aprobar así.</div>
      )}

      {!soloLectura && !rechazando && (
        <div className="fr-acciones">
          <button className="boton chico" disabled={ocupado || x.sin_lugar.length > 0} onClick={() => onAprobar(x)}>
            Aprobar
          </button>
          <button className="boton chico claro" disabled={ocupado} onClick={() => setRechazando(true)}>
            Rechazar
          </button>
        </div>
      )}

      {!soloLectura && rechazando && (
        <form
          className="fr-form"
          onSubmit={(e) => {
            e.preventDefault();
            onRechazar(x, motivo);
          }}
        >
          <label htmlFor={`motivo-${x.id}`}>Motivo (se lo mandamos al alumno)</label>
          <textarea id={`motivo-${x.id}`} rows={2} value={motivo} required onChange={(e) => setMotivo(e.target.value)} />
          <div className="fr-acciones">
            <button className="boton chico" disabled={ocupado || !motivo.trim()}>Confirmar rechazo</button>
            <button type="button" className="boton chico claro" disabled={ocupado} onClick={() => setRechazando(false)}>
              Volver
            </button>
          </div>
        </form>
      )}
    </article>
  );
}

export default function CambiosDias() {
  const [datos, setDatos] = useState(null);
  const [ocupado, setOcupado] = useState(null);
  const [msg, setMsg] = useState(null);

  const avisar = (texto, error = false) => setMsg({ texto, error });

  async function cargar() {
    try {
      setDatos(await api("/api/cambios-dias"));
      avisarMenu();
    } catch (e) {
      avisar(e.message, true);
      setDatos({ pendientes: [], esperando_alumno: [] });
    }
  }
  useEffect(() => {
    cargar();
  }, []);

  async function hacer(x, ruta, cuerpo, ok) {
    setOcupado(x.id);
    try {
      const r = await api(`/api/cambios-dias/${x.id}/${ruta}`, { metodo: "POST", cuerpo });
      const extra = (r.avisos || []).join(" ");
      avisar(`${ok}.${r.avisado ? " Le avisamos por WhatsApp." : ""}${extra ? " " + extra : ""}`, !!extra);
      await cargar();
    } catch (e) {
      avisar(e.message, true);
      await cargar();
    } finally {
      setOcupado(null);
    }
  }

  const aprobar = (x) => {
    if (!window.confirm(`¿Aprobás el cambio de ${x.alumno} desde el ${conDia(x.vigente_desde)}?`)) return;
    hacer(x, "aprobar", undefined, `Aprobaste el cambio de ${x.alumno}`);
  };
  const rechazar = (x, motivo) => hacer(x, "rechazar", { motivo }, `Rechazaste el cambio de ${x.alumno}`);

  return (
    <div className="fr">
      <div className="cabecera">
        <div>
          <h1>Cambios de días</h1>
          <div className="sub">Pedidos de alumnos para cambiar sus días fijos. Al aprobar se cambian las clases y la cuota.</div>
        </div>
      </div>

      {msg && (
        <div className={msg.error ? "msg-error" : "msg-ok"} role={msg.error ? "alert" : "status"} onClick={() => setMsg(null)}>
          {msg.texto}
        </div>
      )}

      {datos === null ? (
        <p className="nota">Cargando…</p>
      ) : (
        <div className="fr-col">
          {datos.pendientes.length === 0 && <div className="fr-vacio">No hay cambios para aprobar 👌</div>}
          {datos.pendientes.map((x) => (
            <Cambio key={x.id} x={x} ocupado={ocupado === x.id} onAprobar={aprobar} onRechazar={rechazar} />
          ))}

          {datos.esperando_alumno.length > 0 && (
            <h2 className="fr-titulo">Esperando que el alumno acepte ({datos.esperando_alumno.length})</h2>
          )}
          {datos.esperando_alumno.map((x) => (
            <Cambio key={x.id} x={x} soloLectura />
          ))}
        </div>
      )}
    </div>
  );
}
