import { useEffect, useMemo, useState } from "react";
import { api } from "../api.js";
import "./cuotas.css";

const plata = (n) => "$" + Number(n || 0).toLocaleString("es-AR");
const mesActual = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
};
const NOMBRE_CARGO = { cuota: "Cuota", inscripcion: "Inscripción", ajuste: "Ajuste" };
const ETIQUETA = { pago: "Pagó", debe: "Debe", parcial: "Parcial", a_favor: "A favor" };

function Fila({ it, mes, abierta, alAbrir, hacer }) {
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
        <div className="nom">{it.alumno}</div>
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
                  <button className="boton chico claro" onClick={() => hacer(() => api("/api/cuotas/" + c.id, { metodo: "PATCH", cuerpo: { monto: valor(c, "monto"), nota: valor(c, "nota") } }))}>
                    Guardar
                  </button>
                </div>
                {c.detalle && <div className="cu-chico">{c.detalle}{c.calculado !== null && c.calculado !== c.monto ? ` · calculado: ${plata(c.calculado)}` : ""}</div>}
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
                disabled={!extra.monto}
                onClick={() => hacer(() => api("/api/cuotas/cargo", { metodo: "POST", cuerpo: { alumno_id: it.alumno_id, mes, concepto: extra.concepto, monto: extra.monto } }).then(() => setExtra({ ...extra, monto: "" })))}
              >
                Agregar cargo
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
                  <button className="cu-borrar" onClick={() => hacer(() => api("/api/cuotas/pago/" + p.id, { metodo: "DELETE" }))}>Borrar</button>
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
                disabled={!monto || Number(monto) <= 0}
                onClick={() => hacer(() => api("/api/cuotas/pago", { metodo: "POST", cuerpo: { alumno_id: it.alumno_id, mes, monto, medio, nota } }).then(() => setNota("")))}
              >
                Registrar pago
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
  const [filtro, setFiltro] = useState("todos");
  const [q, setQ] = useState("");
  const [abierto, setAbierto] = useState(null);
  const [ocupado, setOcupado] = useState(false);

  async function cargar() {
    try {
      setDatos(await api("/api/cuotas?mes=" + mes));
    } catch (e) {
      setError(e.message);
    }
  }

  useEffect(() => {
    setDatos(null);
    setError("");
    setAviso("");
    setAbierto(null);
    cargar();
  }, [mes]);

  async function hacer(fn) {
    setOcupado(true);
    setError("");
    try {
      await fn();
      await cargar();
    } catch (e) {
      setError(e.message);
    } finally {
      setOcupado(false);
    }
  }

  const items = useMemo(
    () =>
      (datos?.items || []).filter(
        (i) =>
          (filtro === "todos" || (filtro === "deben" && i.debe > 0) || (filtro === "pagaron" && i.debe === 0)) &&
          i.alumno.toLowerCase().includes(q.toLowerCase())
      ),
    [datos, filtro, q]
  );
  const t = datos?.totales;

  return (
    <>
      <div className="cabecera">
        <div>
          <h1>Cuotas</h1>
          <div className="sub">Quién pagó y quién debe en el mes</div>
        </div>
        <input type="month" value={mes} onChange={(e) => e.target.value && setMes(e.target.value)} aria-label="Mes" style={{ border: "1px solid #c4c8b8", borderRadius: 8, padding: "9px 12px", minHeight: 40, font: '600 14px "Plus Jakarta Sans", system-ui, sans-serif' }} />
        <button
          className="boton"
          disabled={ocupado}
          onClick={() =>
            hacer(async () => {
              const r = await api("/api/cuotas/generar", { metodo: "POST", cuerpo: { mes } });
              setAviso(`Se crearon ${r.creadas} cuotas nuevas (${r.ya_existian} ya estaban, ${r.sin_precio} sin precio).`);
            })
          }
        >
          Generar cuotas del mes
        </button>
      </div>

      {error && <div className="msg-error" role="alert">{error}</div>}
      {aviso && <div className="msg-ok">{aviso}</div>}

      {!datos && !error && <div className="cargando">Cargando…</div>}

      {datos && (
        <>
          <div className="cu-kpis">
            <div className="cu-kpi mal"><small>Deuda</small><b>{plata(t.deuda)}</b><span>{t.deben} alumnos deben</span></div>
            <div className="cu-kpi"><small>Cobrado</small><b>{plata(t.pagado)}</b><span>de {plata(t.cuotas)}</span></div>
            <div className="cu-kpi"><small>Alumnos</small><b>{t.alumnos}</b><span>con cuota este mes</span></div>
          </div>

          {t.alumnos === 0 && <div className="tarjeta">Todavía no hay cuotas de este mes. Tocá “Generar cuotas del mes”.</div>}

          {t.alumnos > 0 && (
            <>
              <div className="cu-barra">
                <input type="search" placeholder="Buscar alumno" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Buscar alumno" />
                {[["todos", "Todos"], ["deben", "Deben"], ["pagaron", "Pagaron"]].map(([k, n]) => (
                  <button key={k} className="cu-chip" aria-pressed={filtro === k} onClick={() => setFiltro(k)}>{n}</button>
                ))}
              </div>

              <div className="cu-lista">
                <div className="cu-fila titulos">
                  <div>Alumno</div>
                  <div className="der oculto">Cuota</div>
                  <div className="der oculto">Pagó</div>
                  <div className="der">Debe</div>
                  <div className="oculto">Estado</div>
                  <div />
                </div>
                {items.map((it) => (
                  <Fila key={it.alumno_id} it={it} mes={mes} abierta={abierto === it.alumno_id} alAbrir={() => setAbierto(abierto === it.alumno_id ? null : it.alumno_id)} hacer={hacer} />
                ))}
                {items.length === 0 && <div className="cu-fila">No hay alumnos con ese filtro.</div>}
              </div>
            </>
          )}
        </>
      )}
    </>
  );
}