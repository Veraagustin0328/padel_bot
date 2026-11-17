import { useEffect, useMemo, useRef, useState } from "react";
import { ahora } from "../fechas.js";
import { api } from "../api.js";
import "./cuotas.css";

const plata = (n) => "$" + Number(n || 0).toLocaleString("es-AR");
const mesActual = () => {
  const d = ahora();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
};
const NOMBRE_CARGO = { cuota: "Cuota", inscripcion: "Inscripción", ajuste: "Ajuste" };
const ETIQUETA = { pago: "Pagó", debe: "Debe", parcial: "Parcial", a_favor: "A favor" };
const ETIQUETA_MES = { pago: "Pagó", no_pago: "No pagó" };

// vista del encargado: el back solo manda pago / no_pago, sin montos
function FilaSimple({ it, mes, abierta, alAbrir, hacer, ocupado, alCobrar }) {
  const [monto, setMonto] = useState("");
  const [medio, setMedio] = useState("efectivo");
  const [nota, setNota] = useState("");
  const [confirmaInsc, setConfirmaInsc] = useState(false); // pregunta antes de cargar la inscripción
  const pago = it.estado_mes === "pago";

  return (
    <>
      <div className={"cu-fila simple " + (pago ? "" : "debe")}>
        <div className="nom">
          {it.alumno}
          {it.inscripcion && <> <span className="cu-tag pago" title="Ya tiene la inscripción cargada (pago único)">Inscripto</span></>}
        </div>
        <div><span className={"cu-tag " + (pago ? "pago" : "debe")}>{ETIQUETA_MES[it.estado_mes]}</span></div>
        <div className="der">
          <button className={"boton chico " + (pago ? "claro" : "")} onClick={alAbrir}>{abierta ? "Cerrar" : "Cobrar"}</button>
        </div>
      </div>
      {abierta && (
        <div className="cu-detalle">
          <div className="cu-form">
            <input className="monto" type="number" min="1" placeholder="Monto recibido" value={monto} onChange={(e) => setMonto(e.target.value)} aria-label="Monto recibido" />
            <select value={medio} onChange={(e) => setMedio(e.target.value)} aria-label="Medio de pago">
              <option value="efectivo">Efectivo</option>
              <option value="transferencia">Transferencia</option>
              <option value="mercadopago">Mercado Pago</option>
              <option value="otro">Otro</option>
            </select>
            <input className="nota" placeholder="Nota (opcional)" value={nota} onChange={(e) => setNota(e.target.value)} />
            <button
              className="boton chico"
              disabled={!!ocupado || !monto || Number(monto) <= 0}
              onClick={() =>
                hacer(async () => {
                  const r = await api("/api/cuotas/pago", { metodo: "POST", cuerpo: { alumno_id: it.alumno_id, mes, monto, medio, nota } });
                  setMonto("");
                  setNota("");
                  alCobrar({ ...r, alumno: it.alumno });
                }, "pago")
              }
            >
              {ocupado === "pago" ? "Guardando…" : "Registrar cobro"}
            </button>
          </div>
          {/* inscripción: pago único, el monto sale de la configuración y no se muestra */}
          {/* confirma porque a los alumnos de siempre sin inscripción cargada también les aparece */}
          {!it.inscripcion && !confirmaInsc && (
            <div className="cu-form">
              <button className="boton chico claro" disabled={!!ocupado} onClick={() => setConfirmaInsc(true)}>
                Agregar inscripción
              </button>
              <span className="cu-chico">Pago único: se carga una sola vez por alumno.</span>
            </div>
          )}
          {!it.inscripcion && confirmaInsc && (
            <div className="cu-form" role="alertdialog" aria-label="Confirmar inscripción">
              <b>¿Agregar la inscripción a {it.alumno}? Es solo para alumnos nuevos.</b>
              <button className="boton chico claro" disabled={!!ocupado} onClick={() => setConfirmaInsc(false)}>
                Cancelar
              </button>
              <button
                className="boton chico"
                disabled={!!ocupado}
                onClick={() =>
                  hacer(
                    () => api("/api/cuotas/inscripcion", { metodo: "POST", cuerpo: { alumno_id: it.alumno_id, mes } }).then(() => setConfirmaInsc(false)),
                    "insc"
                  )
                }
              >
                {ocupado === "insc" ? "Agregando…" : "Confirmar"}
              </button>
            </div>
          )}
        </div>
      )}
    </>
  );
}

function Fila({ it, mes, abierta, alAbrir, hacer, ocupado }) {
  const [monto, setMonto] = useState(String(it.debe || ""));
  const [medio, setMedio] = useState("efectivo");
  const [nota, setNota] = useState("");
  const [edits, setEdits] = useState({});
  const [extra, setExtra] = useState({ concepto: "inscripcion", monto: "" });

  useEffect(() => {
    setMonto(String(it.debe || ""));
    setEdits({});
  }, [it.debe, it.cuota, it.pagado]);

  const valor = (c, campo) => (edits[c.id] && edits[c.id][campo] !== undefined ? edits[c.id][campo] : campo === "monto" ? String(c.monto) : c.nota || "");
  const cambiar = (c, campo, v) => setEdits({ ...edits, [c.id]: { ...(edits[c.id] || {}), [campo]: v } });

  return (
    <>
      <div className={"cu-fila " + (it.debe > 0 ? "debe" : "")}>
        <div className="nom">
          {it.alumno}
          {it.sin_tarifa && <> <span className="cu-tag sin_tarifa" title="Alguna clase no tiene tarifa y no se cobró">Sin tarifa</span></>}
        </div>
        <div className="der oculto">{plata(it.cuota)}</div>
        <div className="der oculto">{plata(it.pagado)}</div>
        <div className={"der " + (it.debe > 0 ? "cu-deuda" : "")}>{it.debe > 0 ? plata(it.debe) : "—"}</div>
        <div className="oculto"><span className={"cu-tag " + it.estado}>{ETIQUETA[it.estado]}</span></div>
        <div className="der">
          <button className={"boton chico " + (it.debe > 0 ? "" : "claro")} onClick={alAbrir}>
            {abierta ? "Cerrar" : it.debe > 0 ? "Cobrar" : "Ver"}
          </button>
        </div>
      </div>
      {abierta && (
        <div className="cu-detalle">
          <div>
            <h3>Cargos del mes</h3>
            {it.cargos.map((c) => (
              <div key={c.id}>
                <div className="cu-cargo">
                  <span className="lbl">{NOMBRE_CARGO[c.concepto] || c.concepto}</span>
                  <input className="monto" type="number" min="0" value={valor(c, "monto")} onChange={(e) => cambiar(c, "monto", e.target.value)} aria-label="Monto" />
                  <input className="nota" placeholder="Nota (ej: arrancó a mitad de mes)" value={valor(c, "nota")} onChange={(e) => cambiar(c, "nota", e.target.value)} />
                  <button className="boton chico claro" disabled={!!ocupado} onClick={() => hacer(() => api("/api/cuotas/" + c.id, { metodo: "PATCH", cuerpo: { monto: valor(c, "monto"), nota: valor(c, "nota") } }), "cargo-" + c.id)}>
                    {ocupado === "cargo-" + c.id ? "Guardando…" : "Guardar"}
                  </button>
                </div>
                {c.detalle && (
                  <div className="cu-chico">
                    {c.detalle.split("; ").map((l, i) => (
                      <span key={i} className={l.includes("SIN TARIFA") ? "cu-alerta" : ""}>{i > 0 ? "; " : ""}{l}</span>
                    ))}
                    {c.calculado !== null && c.calculado !== c.monto ? ` · calculado: ${plata(c.calculado)}` : ""}
                  </div>
                )}
              </div>
            ))}
            <div className="cu-form" style={{ marginTop: 10 }}>
              <select value={extra.concepto} onChange={(e) => setExtra({ ...extra, concepto: e.target.value })} aria-label="Tipo de cargo">
                <option value="inscripcion">Inscripción</option>
                <option value="ajuste">Ajuste</option>
              </select>
              <input className="monto" type="number" placeholder="Monto" value={extra.monto} onChange={(e) => setExtra({ ...extra, monto: e.target.value })} />
              <button
                className="boton chico claro"
                disabled={!!ocupado || !extra.monto}
                onClick={() => hacer(() => api("/api/cuotas/cargo", { metodo: "POST", cuerpo: { alumno_id: it.alumno_id, mes, concepto: extra.concepto, monto: extra.monto } }).then(() => setExtra({ ...extra, monto: "" })), "extra")}
              >
                {ocupado === "extra" ? "Guardando…" : "Agregar cargo"}
              </button>
            </div>
          </div>

          <div>
            <h3>Pagos</h3>
            {it.pagos.length === 0 && <div className="cu-chico">Todavía no pagó nada este mes.</div>}
            {it.pagos.map((p) => (
              <div key={p.id} className="cu-pago">
                <b>{plata(p.monto)}</b>
                <span>{p.fecha}</span>
                <span>{p.medio}</span>
                {p.concepto && p.concepto !== "cuota" && <span>{NOMBRE_CARGO[p.concepto] || p.concepto}</span>}
                <span className={"cu-origen" + (p.comprobante_id ? " comp" : "")}>{p.origen}</span>
                {p.nota && !p.comprobante_id && <span className="cu-chico">{p.nota}</span>}
                {/* los de comprobante se sacan desde Comprobantes */}
                {!p.comprobante_id && (
                  <button className="cu-borrar" disabled={!!ocupado} onClick={() => hacer(() => api("/api/cuotas/pago/" + p.id, { metodo: "DELETE" }), "borrar-" + p.id)}>
                    {ocupado === "borrar-" + p.id ? "Borrando…" : "Borrar"}
                  </button>
                )}
              </div>
            ))}
            <div className="cu-form" style={{ marginTop: 10 }}>
              <input className="monto" type="number" min="1" value={monto} onChange={(e) => setMonto(e.target.value)} aria-label="Monto del pago" />
              <select value={medio} onChange={(e) => setMedio(e.target.value)} aria-label="Medio de pago">
                <option value="efectivo">Efectivo</option>
                <option value="transferencia">Transferencia</option>
                <option value="mercadopago">Mercado Pago</option>
                <option value="otro">Otro</option>
              </select>
              <input className="nota" placeholder="Nota (opcional)" value={nota} onChange={(e) => setNota(e.target.value)} />
              <button
                className="boton chico"
                disabled={!!ocupado || !monto || Number(monto) <= 0}
                onClick={() => hacer(() => api("/api/cuotas/pago", { metodo: "POST", cuerpo: { alumno_id: it.alumno_id, mes, monto, medio, nota } }).then(() => setNota("")), "pago")}
              >
                {ocupado === "pago" ? "Guardando…" : "Registrar pago"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

export default function Cuotas() {
  const [mes, setMes] = useState(mesActual());
  const [datos, setDatos] = useState(null);
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");
  const [revisar, setRevisar] = useState([]); // alumnos sin tarifa al generar el mes
  const [filtro, setFiltro] = useState("todos");
  const [q, setQ] = useState("");
  const [abierto, setAbierto] = useState(null);
  const [ocupado, setOcupado] = useState(""); // qué botón está esperando ("" = ninguno)
  const [cobro, setCobro] = useState(null); // último cobro del encargado, para el Deshacer
  // candado contra el doble click: el estado tarda un render en llegar al botón
  const enCurso = useRef(false);

  async function cargar() {
    try {
      setDatos(await api("/api/cuotas?mes=" + mes));
    } catch (e) {
      setError(e.message);
    }
  }

  useEffect(() => {
    setDatos(null);
    setRevisar([]); // la lista era del mes anterior
    setError("");
    setAviso("");
    setAbierto(null);
    setCobro(null);
    cargar();
  }, [mes]);

  // todos los botones se apagan mientras espera; el que se tocó dice "Guardando…"
  async function hacer(fn, clave = "si") {
    if (enCurso.current) return;
    enCurso.current = true;
    setOcupado(clave);
    setError("");
    try {
      await fn();
      await cargar();
    } catch (e) {
      setError(e.message);
    } finally {
      enCurso.current = false;
      setOcupado("");
    }
  }

  // detalle=false: es el encargado, sin plata
  const conDetalle = datos?.detalle !== false;
  const debe = (i) => (conDetalle ? i.debe > 0 : i.estado_mes !== "pago");
  const items = useMemo(
    () =>
      (datos?.items || []).filter(
        (i) =>
          (filtro === "todos" || (filtro === "deben" && debe(i)) || (filtro === "pagaron" && !debe(i))) &&
          i.alumno.toLowerCase().includes(q.toLowerCase())
      ),
    [datos, filtro, q]
  );
  const t = datos?.totales;
  const cantidad = conDetalle ? t?.alumnos || 0 : (datos?.items || []).length;

  function alCobrar(r) {
    setAbierto(null);
    setCobro({ id: r.id, alumno: r.alumno, estado: r.estado_mes, hasta: Date.now() + (r.deshacer_minutos || 0) * 60000 });
  }

  return (
    <>
      <div className="cabecera">
        <div>
          <h1>Cuotas</h1>
          <div className="sub">{conDetalle ? "Quién pagó y quién debe en el mes" : "Quién pagó el mes y quién no"}</div>
        </div>
        <input type="month" value={mes} onChange={(e) => e.target.value && setMes(e.target.value)} aria-label="Mes" style={{ border: "1px solid #c4c8b8", borderRadius: 8, padding: "9px 12px", minHeight: 40, font: '600 14px "Plus Jakarta Sans", system-ui, sans-serif' }} />
        <button
          className="boton"
          disabled={!!ocupado}
          onClick={() =>
            hacer(async () => {
              const r = await api("/api/cuotas/generar", { metodo: "POST", cuerpo: { mes } });
              setAviso(`Se crearon ${r.creadas} cuotas nuevas (${r.ya_existian} ya estaban, ${r.sin_precio} sin precio).`);
              setRevisar([
                ...(r.sin_precio_detalle || []).map((x) => ({ ...x, que: "no se creó la cuota" })),
                ...(r.incompletas || []).map((x) => ({ ...x, que: "se creó sin esa parte" })),
              ]);
            }, "generar")
          }
        >
          {ocupado === "generar" ? "Generando…" : "Generar cuotas del mes"}
        </button>
      </div>

      {error && <div className="msg-error" role="alert">{error}</div>}
      {aviso && <div className="msg-ok">{aviso}</div>}
      {cobro && (
        <div className="msg-ok" role="status">
          Cobro registrado: {cobro.alumno} quedó {cobro.estado === "pago" ? "con el mes pago" : "sin el mes pago"}.{" "}
          {Date.now() < cobro.hasta && (
            <button
              className="boton chico claro"
              disabled={!!ocupado}
              onClick={() => hacer(() => api("/api/cuotas/pago/" + cobro.id, { metodo: "DELETE" }).then(() => setCobro(null)), "deshacer")}
            >
              {ocupado === "deshacer" ? "Deshaciendo…" : "Deshacer"}
            </button>
          )}
        </div>
      )}
      {revisar.length > 0 && (
        <div className="cu-revisar" role="status">
          <b>Para revisar a mano ({revisar.length}): clases sin tarifa, no se cobraron.{conDetalle ? "" : " Avisale al dueño."}</b>
          {revisar.map((x) => (
            <div key={x.alumno_id}>{x.alumno}: {x.que}{x.motivo ? ` (${x.motivo})` : ""}</div>
          ))}
        </div>
      )}

      {!datos && !error && <div className="cargando">Cargando…</div>}

      {datos && (
        <>
          {conDetalle && (
            <div className="cu-kpis">
              <div className="cu-kpi mal"><small>Deuda</small><b>{plata(t.deuda)}</b><span>{t.deben} alumnos deben</span></div>
              <div className="cu-kpi"><small>Cobrado</small><b>{plata(t.pagado)}</b><span>de {plata(t.cuotas)}</span></div>
              <div className="cu-kpi"><small>Alumnos</small><b>{t.alumnos}</b><span>con cuota este mes</span></div>
            </div>
          )}

          {cantidad === 0 && <div className="tarjeta">Todavía no hay cuotas de este mes. Tocá “Generar cuotas del mes”.</div>}

          {cantidad > 0 && (
            <>
              <div className="cu-barra">
                <input type="search" placeholder="Buscar alumno" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Buscar alumno" />
                {[["todos", "Todos"], ["deben", "Deben"], ["pagaron", "Pagaron"]].map(([k, n]) => (
                  <button key={k} className="cu-chip" aria-pressed={filtro === k} onClick={() => setFiltro(k)}>{n}</button>
                ))}
              </div>

              <div className="cu-lista">
                {conDetalle ? (
                  <div className="cu-fila titulos">
                    <div>Alumno</div>
                    <div className="der oculto">Cuota</div>
                    <div className="der oculto">Pagó</div>
                    <div className="der">Debe</div>
                    <div className="oculto">Estado</div>
                    <div />
                  </div>
                ) : (
                  <div className="cu-fila simple titulos">
                    <div>Alumno</div>
                    <div>Mes</div>
                    <div />
                  </div>
                )}
                {items.map((it) =>
                  conDetalle ? (
                    <Fila key={it.alumno_id} it={it} mes={mes} abierta={abierto === it.alumno_id} alAbrir={() => setAbierto(abierto === it.alumno_id ? null : it.alumno_id)} hacer={hacer} ocupado={ocupado} />
                  ) : (
                    <FilaSimple key={it.alumno_id} it={it} mes={mes} abierta={abierto === it.alumno_id} alAbrir={() => setAbierto(abierto === it.alumno_id ? null : it.alumno_id)} hacer={hacer} ocupado={ocupado} alCobrar={alCobrar} />
                  )
                )}
                {items.length === 0 && <div className="cu-fila">No hay alumnos con ese filtro.</div>}
              </div>
            </>
          )}
        </>
      )}
    </>
  );
}