import { useEffect, useState } from "react";
import { api, descargar } from "../api.js";
import { MARCA } from "../marca.js";
import { hoyEn, numeroDia } from "../fechas.js";
import "./estadistica.css";

// Estadística de horas: las horas de cada profe por semana y día, como la planilla de Gabi.
// Solo el dueño y SIN plata (los montos están en Profes y horas).

const DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"];
const MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
  "septiembre", "octubre", "noviembre", "diciembre"];
const AMBITOS = { adultos: "Adultos mañana", adultos_tarde: "Adultos tarde", sabados: "Sábados", kids: "Kids", kids_pro: "Kids Pro" };
const TIPOS = { grupal: "grupal", particular: "particular", particular_2: "particular de 2", otro: "otra", fisico: "físico" };

// 1 decimal como máximo; vacío si no hubo horas (no "0")
const h = (n) => (n === null || n === undefined ? "" : Number(n).toLocaleString("es-AR", { maximumFractionDigits: 1 }));
const ddmm = (iso) => `${iso.slice(8)}/${iso.slice(5, 7)}`;

// "2026-11" + n meses, como texto
function sumarMes(mes, n) {
  const [a, m] = mes.split("-").map(Number);
  const t = a * 12 + (m - 1) + n;
  return `${Math.floor(t / 12)}-${String((t % 12) + 1).padStart(2, "0")}`;
}
const nombreMes = (mes) => `${MESES[Number(mes.slice(5)) - 1]} ${mes.slice(0, 4)}`;

function Semana({ s, profes }) {
  return (
    <section className="tarjeta eh-semana">
      <h2>Semana del {ddmm(s.lunes)}</h2>
      <div className="eh-scroll">
        <table className="eh-tabla">
          <thead>
            <tr>
              <th className="eh-dia">Día</th>
              {profes.map((p) => (
                <th key={p.id ?? "sin"}>{p.nombre}</th>
              ))}
              <th className="eh-total">Total</th>
            </tr>
          </thead>
          <tbody>
            {s.dias.map((d) => (
              <tr key={d.fecha} className={!d.en_mes ? "fuera" : d.total === null ? "sin" : ""}>
                <th className="eh-dia" scope="row">
                  {DIAS[d.dia].slice(0, 3)} {numeroDia(d.fecha)}
                </th>
                {d.horas.map((x, i) => (
                  <td key={i} className={x === null ? "vacia" : ""}>
                    {h(x)}
                  </td>
                ))}
                <td className="eh-total">{d.en_mes ? h(d.total) : ""}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th className="eh-dia" scope="row">Subtotal</th>
              {s.subtotal.map((x, i) => (
                <td key={i}>{h(x)}</td>
              ))}
              <td className="eh-total">{h(s.total)}</td>
            </tr>
          </tfoot>
        </table>
      </div>
    </section>
  );
}

export default function EstadisticaHoras() {
  const [mesHoy] = useState(() => hoyEn(MARCA.zonaHoraria).slice(0, 7));
  const [mes, setMes] = useState(mesHoy);
  const [cargados, setDatos] = useState(null);
  const [error, setError] = useState("");
  const [bajando, setBajando] = useState(false);
  // solo si son del mes que se ve: al cambiar de mes no queda un instante con los números del anterior
  const datos = cargados && cargados.mes === mes ? cargados : null;

  useEffect(() => {
    let vigente = true;
    setDatos(null);
    setError("");
    api(`/api/estadistica-horas?mes=${mes}`)
      .then((d) => vigente && setDatos(d))
      .catch((e) => vigente && setError(e.message || "No se pudo cargar la estadística"));
    return () => {
      vigente = false;
    };
  }, [mes]);

  async function bajarCsv() {
    setBajando(true);
    setError("");
    try {
      await descargar(`/api/estadistica-horas/csv?mes=${mes}`, `estadistica_horas_${mes}.csv`);
    } catch (e) {
      setError(e.message);
    } finally {
      setBajando(false);
    }
  }

  const hayHoras = datos && datos.profes.length > 0;

  return (
    <div className="eh">
      <div className="cabecera">
        <div>
          <h1>Estadística de horas</h1>
          <div className="sub">Horas que dio cada profe, por semana y por día. Cuenta solo las clases con al menos un presente.</div>
        </div>
        <button className="boton claro" onClick={bajarCsv} disabled={!hayHoras || bajando}>
          {bajando ? "Bajando…" : "Descargar CSV"}
        </button>
      </div>

      <div className="eh-mes">
        <button className="eh-flecha" onClick={() => setMes(sumarMes(mes, -1))} aria-label="Mes anterior">
          ‹
        </button>
        <div className="eh-mes-nombre">
          {nombreMes(mes)}
          {mes === mesHoy && <small>este mes</small>}
        </div>
        <button className="eh-flecha" onClick={() => setMes(sumarMes(mes, 1))} aria-label="Mes siguiente">
          ›
        </button>
      </div>

      {error && <div className="msg-error">{error}</div>}
      {!datos && !error && <div className="nota">Cargando…</div>}

      {datos && (
        <>
          <div className="eh-resumen">
            <div className="tarjeta eh-numero">
              <small>Total del mes</small>
              <b>{h(datos.total) || "0"} h</b>
            </div>
            {datos.profes.map((p, i) => (
              <div key={p.id ?? "sin"} className="tarjeta eh-numero">
                <small>{p.nombre}</small>
                <b>{h(datos.total_profes[i])} h</b>
              </div>
            ))}
          </div>

          {!hayHoras && <div className="tarjeta eh-vacio">No hay horas dadas en {nombreMes(mes)}.</div>}

          {datos.no_suman.length > 0 && (
            <section className="tarjeta eh-info">
              <h2>No suman (para saber por qué un número no cuadra)</h2>
              <ul>
                {datos.no_suman.map((p) => (
                  <li key={p.id ?? "sin"}>
                    <b>{p.nombre}</b>:{" "}
                    {[
                      p.sin_alumnos && `${p.sin_alumnos} ${p.sin_alumnos === 1 ? "clase" : "clases"} sin alumnos`,
                      p.pendientes && `${p.pendientes} ${p.pendientes === 1 ? "pendiente" : "pendientes"} de confirmar`,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {hayHoras && (
            <>
              {datos.semanas.map((s) => (
                <Semana key={s.lunes} s={s} profes={datos.profes} />
              ))}

              <section className="tarjeta eh-semana">
                <h2>Total del mes</h2>
                <div className="eh-scroll">
                  <table className="eh-tabla">
                    <thead>
                      <tr>
                        <th className="eh-dia" />
                        {datos.profes.map((p) => (
                          <th key={p.id ?? "sin"}>{p.nombre}</th>
                        ))}
                        <th className="eh-total">Total</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr className="eh-fila-total">
                        <th className="eh-dia" scope="row">Horas</th>
                        {datos.total_profes.map((x, i) => (
                          <td key={i}>{h(x)}</td>
                        ))}
                        <td className="eh-total">{h(datos.total)}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </section>

              <section className="tarjeta eh-semana">
                <h2>Por franja</h2>
                <div className="eh-scroll">
                  <table className="eh-tabla eh-franjas">
                    <thead>
                      <tr>
                        <th className="eh-dia">Franja</th>
                        <th>Horas</th>
                        <th>Clases</th>
                        <th className="izq">Detalle</th>
                      </tr>
                    </thead>
                    <tbody>
                      {datos.franjas.map((f) => (
                        <tr key={f.ambito}>
                          <th className="eh-dia" scope="row">{AMBITOS[f.ambito] || f.ambito}</th>
                          <td>{h(f.horas)}</td>
                          <td>{f.clases}</td>
                          <td className="izq eh-detalle">
                            {Object.entries(f.por_tipo)
                              .map(([t, x]) => `${TIPOS[t] || t} ${h(x)}`)
                              .join(" · ")}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            </>
          )}
        </>
      )}
    </div>
  );
}
