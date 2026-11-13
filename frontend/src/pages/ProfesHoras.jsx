import { useEffect, useState } from "react";
import { api, descargar } from "../api.js";
import "./cuotas.css";
import "./profeshoras.css";

// Profes y horas: cuánto se le paga a cada profe en el mes. Solo el dueño (el back frena al resto).

const plata = (n) => (n === null || n === undefined ? "—" : "$" + Number(n).toLocaleString("es-AR", { maximumFractionDigits: 2 }));
const horas = (n) => Number(n || 0).toLocaleString("es-AR", { maximumFractionDigits: 2 }) + " h";
const mesActual = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
};
// "2026-11-09" -> "lun 09/11"
const DIAS = ["dom", "lun", "mar", "mié", "jue", "vie", "sáb"];
function fechaCorta(iso) {
  const [a, m, d] = iso.split("-").map(Number);
  return `${DIAS[new Date(a, m - 1, d).getDay()]} ${String(d).padStart(2, "0")}/${String(m).padStart(2, "0")}`;
}

function Tabla({ titulo, filas, conPlata, conMotivo, nota }) {
  if (!filas.length) return null;
  return (
    <div>
      <h3>
        {titulo} <span className="ph-cuenta">{filas.length}</span>
      </h3>
      {nota && <div className="cu-chico">{nota}</div>}
      <div className="ph-tabla">
        {filas.map((c) => (
          <div key={`${c.clase_id}-${c.fecha}`} className="ph-clase">
            <span className="ph-fecha">{fechaCorta(c.fecha)} {c.hora}</span>
            <span className="ph-grupo">{c.grupo}</span>
            <span className="ph-dato">{conMotivo ? c.motivo : `${c.presentes} pres.`}</span>
            <span className="ph-dato der">{horas(c.horas)}</span>
            {conPlata && (
              <span className={"ph-dato der" + (c.tarifa === null ? " ph-falta" : "")}>
                {c.tarifa === null ? "sin tarifa" : plata(c.monto)}
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function Profe({ p, abierto, alAbrir, alMarcarHC }) {
  const pendientes = p.pendientes.length;
  const [guardando, setGuardando] = useState(false);
  const [errorHC, setErrorHC] = useState("");

  async function cambiarHC(e) {
    setGuardando(true);
    setErrorHC("");
    try {
      const r = await api(`/api/profes/${p.profesor_id}/head-coach`, { metodo: "POST", cuerpo: { activo: e.target.checked } });
      alMarcarHC(r.head_coach);
    } catch (err) {
      setErrorHC(err.message);
    } finally {
      setGuardando(false);
    }
  }

  return (
    <>
      <button className={"cu-fila ph-fila" + (p.sin_tarifa ? " debe" : "")} onClick={alAbrir} aria-expanded={abierto}>
        <div className="nom">
          {p.nombre}
          {p.head_coach && <span className="cu-tag a_favor ph-tag">Head Coach</span>}
          {p.sin_tarifa && <span className="cu-tag debe ph-tag">sin tarifa</span>}
        </div>
        <div className="der">{horas(p.horas)}</div>
        <div className="der oculto">{p.tarifa === null ? "—" : plata(p.tarifa)}</div>
        <div className="der ph-monto">{plata(p.monto)}</div>
        <div className="oculto">{pendientes > 0 && <span className="cu-tag parcial">{pendientes} pend.</span>}</div>
        <div className="ph-flecha">{abierto ? "▲" : "▼"}</div>
      </button>
      {abierto && (
        <div className="cu-detalle">
          {p.profesor_id != null && (
            <label className="ph-hc">
              <input type="checkbox" checked={!!p.head_coach} onChange={cambiarHC} disabled={guardando} />
              Head Coach: sus particulares de mañana se cobran con la tarifa "Head Coach" de Planes y precios
            </label>
          )}
          {errorHC && <div className="msg-error" role="alert">{errorHC}</div>}
          {p.sin_tarifa && (
            <div className="msg-error">
              Hay horas sin tarifa vigente: no suman al monto. Cargale la tarifa para que se calculen.
            </div>
          )}
          <Tabla titulo="Clases que se pagan" filas={p.clases} conPlata />
          <Tabla
            titulo="Pendientes de confirmar"
            filas={p.pendientes}
            conMotivo
            nota="No suman hasta que se marque al menos un presente en Mis clases."
          />
          <Tabla titulo="Sin alumnos (no se pagan)" filas={p.sin_alumnos} />
          {!p.clases.length && !p.pendientes.length && !p.sin_alumnos.length && (
            <div className="cu-chico">No tiene clases este mes.</div>
          )}
        </div>
      )}
    </>
  );
}

export default function ProfesHoras() {
  const [mes, setMes] = useState(mesActual());
  const [datos, setDatos] = useState(null);
  const [error, setError] = useState("");
  const [abierto, setAbierto] = useState(null);
  const [bajando, setBajando] = useState(false);

  useEffect(() => {
    let vigente = true;
    setDatos(null);
    setError("");
    setAbierto(null);
    api(`/api/profes-horas?mes=${mes}`)
      .then((d) => vigente && setDatos(d))
      .catch((e) => vigente && setError(e.message));
    return () => {
      vigente = false;
    };
  }, [mes]);

  async function bajarCsv() {
    setBajando(true);
    setError("");
    try {
      await descargar(`/api/profes-horas/csv?mes=${mes}`, `horas_profes_${mes}.csv`);
    } catch (e) {
      setError(e.message);
    } finally {
      setBajando(false);
    }
  }

  const sinTarifa = datos ? datos.profes.filter((p) => p.sin_tarifa).length : 0;

  return (
    <>
      <div className="cabecera">
        <div>
          <h1>Profes y horas</h1>
          <div className="sub">Cuánto se le paga a cada profe por las clases que dio en el mes</div>
        </div>
        <div className="cu-barra">
          <input type="month" value={mes} onChange={(e) => e.target.value && setMes(e.target.value)} aria-label="Mes" />
          <button className="boton claro" onClick={bajarCsv} disabled={bajando || !datos}>
            {bajando ? "Bajando…" : "Bajar CSV"}
          </button>
        </div>
      </div>

      {error && <div className="msg-error" role="alert">{error}</div>}
      {!datos && !error && <div className="cargando">Cargando…</div>}

      {datos && (
        <>
          <div className="cu-kpis">
            <div className="cu-kpi"><small>A pagar</small><b>{plata(datos.total_monto)}</b><span>clases con al menos un presente</span></div>
            <div className="cu-kpi"><small>Horas pagas</small><b>{horas(datos.total_horas)}</b><span>{datos.profes.length} profes</span></div>
            <div className={"cu-kpi" + (datos.total_pendientes ? " ph-ojo" : "")}>
              <small>Pendientes</small><b>{datos.total_pendientes}</b><span>clases sin confirmar</span>
            </div>
          </div>

          {sinTarifa > 0 && (
            <div className="msg-error">
              {sinTarifa === 1 ? "Hay 1 profe" : `Hay ${sinTarifa} profes`} con horas sin tarifa: esas horas no suman al total.
            </div>
          )}

          {datos.profes.length === 0 ? (
            <div className="tarjeta">No hay clases dadas ni pendientes en este mes.</div>
          ) : (
            <div className="cu-lista">
              <div className="cu-fila ph-fila titulos">
                <div>Profe</div>
                <div className="der">Horas</div>
                <div className="der oculto">Tarifa</div>
                <div className="der">Monto</div>
                <div className="oculto">Pendientes</div>
                <div />
              </div>
              {datos.profes.map((p) => {
                const clave = p.profesor_id ?? "sin";
                return (
                  <Profe key={clave} p={p} abierto={abierto === clave}
                         alAbrir={() => setAbierto(abierto === clave ? null : clave)}
                         alMarcarHC={(hc) => setDatos({
                           ...datos,
                           profes: datos.profes.map((x) => (x.profesor_id === p.profesor_id ? { ...x, head_coach: hc } : x)),
                         })} />
                );
              })}
              <div className="cu-fila ph-fila ph-total">
                <div>Total</div>
                <div className="der">{horas(datos.total_horas)}</div>
                <div className="oculto" />
                <div className="der ph-monto">{plata(datos.total_monto)}</div>
                <div className="oculto" />
                <div />
              </div>
            </div>
          )}
        </>
      )}
    </>
  );
}
