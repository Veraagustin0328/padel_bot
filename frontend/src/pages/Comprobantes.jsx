import { useEffect, useState } from "react";
import { api } from "../api.js";
import "./comprobantes.css";

const peso = new Intl.NumberFormat("es-AR", { style: "currency", currency: "ARS", maximumFractionDigits: 0 });
const numero = (txt) => Number(String(txt).replace(/\./g, "").replace(",", "."));
const FILTROS = [
  ["pendiente", "Pendientes"],
  ["confirmado", "Confirmados"],
  ["todos", "Todos"],
];
const CONCEPTOS = [
  ["cuota", "Cuota"],
  ["inscripcion", "Inscripción"],
  ["ajuste", "Ajuste"],
];
const MEDIOS = [
  ["transferencia", "Transferencia"],
  ["mercadopago", "Mercado Pago"],
  ["efectivo", "Efectivo"],
  ["otro", "Otro"],
];

export default function Comprobantes() {
  const [filtro, setFiltro] = useState("pendiente");
  const [lista, setLista] = useState(null);
  const [alumnos, setAlumnos] = useState([]);
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");
  const [forms, setForms] = useState({});
  const [ocupado, setOcupado] = useState(null);
  const [resultado, setResultado] = useState(null);

  async function cargar() {
    try {
      setLista(await api(`/api/comprobantes?estado=${filtro}`));
    } catch (e) {
      setError(e.message);
      setLista([]);
    }
  }
  useEffect(() => { setLista(null); cargar(); }, [filtro]);
  useEffect(() => { api("/api/comprobantes/alumnos").then(setAlumnos).catch(() => setAlumnos([])); }, []);

  // lo que tocó el encargado; si no tocó nada, va lo que detectó el backend
  const valor = (c, campo) => {
    const f = forms[c.id] || {};
    if (f[campo] !== undefined) return f[campo];
    if (campo === "monto") return c.monto ?? "";
    if (campo === "alumno_id") return c.alumno_id ?? "";
    if (campo === "mes") return c.mes_iso ?? "";
    if (campo === "concepto") return "cuota";
    if (campo === "medio") return "transferencia";
    return "";
  };
  const cambiar = (c, campo, v) => setForms({ ...forms, [c.id]: { ...(forms[c.id] || {}), [campo]: v } });

  async function confirmar(c) {
    setError(""); setAviso(""); setResultado(null);
    const n = numero(valor(c, "monto"));
    if (!(n > 0)) { setError("Poné el monto antes de aprobar."); return; }
    if (!valor(c, "alumno_id") || !valor(c, "mes")) { setError("Elegí el alumno y el mes antes de aprobar."); return; }
    setOcupado(c.id);
    try {
      await api(`/api/comprobantes/${c.id}/confirmar`, {
        metodo: "POST",
        cuerpo: {
          monto: n,
          alumno_id: Number(valor(c, "alumno_id")),
          mes: valor(c, "mes"),
          concepto: valor(c, "concepto"),
          medio: valor(c, "medio"),
        },
      });
      const nombre = alumnos.find((a) => a.id === Number(valor(c, "alumno_id")))?.nombre || c.alumno || c.telefono;
      setAviso(`Aprobado: ${nombre} por ${peso.format(n)}. Quedó cargado en Cuotas.`);
      await cargar();
    } catch (e) {
      setError(e.message);
    }
    setOcupado(null);
  }

  async function cambiarEstado(c, accion, pregunta, ok) {
    if (!window.confirm(pregunta)) return;
    setError(""); setAviso(""); setResultado(null);
    setOcupado(c.id);
    try {
      const r = await api(`/api/comprobantes/${c.id}/${accion}`, { metodo: "POST" });
      setAviso(ok + (r.pago_borrado ? " Se borró el pago que había generado en Cuotas." : ""));
      await cargar();
    } catch (e) {
      setError(e.message);
    }
    setOcupado(null);
  }

  const rechazar = (c) =>
    cambiarEstado(c, "rechazar", `¿Rechazar el comprobante de ${c.alumno || c.telefono}?`, "Comprobante rechazado.");
  const desaprobar = (c) =>
    cambiarEstado(c, "desaprobar", `¿Volver a pendiente el comprobante de ${c.alumno || c.telefono}?`, "Volvió a pendiente.");

  async function aplicar() {
    if (!window.confirm("¿Pasar a la planilla todos los pagos confirmados?")) return;
    setError(""); setAviso("");
    setOcupado("aplicar");
    try {
      setResultado(await api("/api/comprobantes/aplicar", { metodo: "POST" }));
      await cargar();
    } catch (e) {
      setError(e.message);
    }
    setOcupado(null);
  }

  return (
    <div>
      <h1>Comprobantes</h1>
      <p className="cmp-sub">Lo que avisan los alumnos por WhatsApp. Al aprobar se carga el pago en Cuotas; después lo podés pasar a la planilla.</p>

      <div className="cmp-barra">
        {FILTROS.map(([v, texto]) => (
          <button key={v} className={"cmp-filtro" + (filtro === v ? " activo" : "")} onClick={() => setFiltro(v)}>
            {texto}
          </button>
        ))}
        <span className="cmp-espacio" />
        <button className="boton chico claro" onClick={cargar}>Actualizar</button>
        <button className="boton chico" onClick={aplicar} disabled={ocupado === "aplicar"}>
          {ocupado === "aplicar" ? "Pasando…" : "Pasar confirmados a la planilla"}
        </button>
      </div>

      {error && <div className="cmp-msg error">{error}</div>}
      {aviso && <div className="cmp-msg ok">{aviso}</div>}

      {resultado && (
        <div className="cmp-resultado">
          <strong>Resultado</strong>
          {resultado.aplicados?.length > 0 && (
            <>
              <div>Pasados a la planilla:</div>
              <ul>{resultado.aplicados.map((t) => <li key={t}>{t}</li>)}</ul>
            </>
          )}
          {resultado.saltados?.length > 0 && (
            <>
              <div>Quedaron sin pasar:</div>
              <ul>{resultado.saltados.map((t) => <li key={t}>{t}</li>)}</ul>
            </>
          )}
          {!resultado.aplicados?.length && !resultado.saltados?.length && <div>No había nada confirmado para pasar.</div>}
        </div>
      )}

      {lista === null ? (
        <div className="cargando">Cargando…</div>
      ) : lista.length === 0 ? (
        <div className="cmp-vacio">No hay comprobantes en esta vista.</div>
      ) : (
        <div className="cmp-lista">
          {lista.map((c) => {
            const falta = [!c.alumno_id && "alumno", !c.mes_iso && "mes"].filter(Boolean);
            return (
              <div key={c.id} className="cmp-card">
                <div className="cmp-fila">
                  <div>
                    <div className="cmp-nombre">{c.alumno || c.telefono}</div>
                    <div className="cmp-sub">#{c.id} · {c.mes} · {c.fecha}{c.alumno ? ` · ${c.telefono}` : ""}</div>
                  </div>
                  <div style={{ textAlign: "right" }}>
                    <div className="cmp-monto">{c.monto ? peso.format(c.monto) : "Sin monto"}</div>
                    <span className={"cmp-estado " + c.estado}>{c.estado}</span>
                  </div>
                </div>

                {c.estado === "pendiente" && (
                  <>
                    {falta.length > 0 && (
                      <div className="cmp-falta">No pude identificar {falta.join(" ni ")}: elegilo antes de aprobar.</div>
                    )}
                    <div className="cmp-acciones">
                      <select className="cmp-select" value={valor(c, "alumno_id")} onChange={(e) => cambiar(c, "alumno_id", e.target.value)} aria-label="Alumno">
                        <option value="">Elegí alumno…</option>
                        {alumnos.map((a) => (
                          <option key={a.id} value={a.id}>{a.nombre}{a.estado && a.estado !== "activo" ? ` (${a.estado})` : ""}</option>
                        ))}
                      </select>
                      <input className="cmp-input" type="month" value={valor(c, "mes")} onChange={(e) => cambiar(c, "mes", e.target.value)} aria-label="Mes" />
                      <select className="cmp-select" value={valor(c, "concepto")} onChange={(e) => cambiar(c, "concepto", e.target.value)} aria-label="Concepto">
                        {CONCEPTOS.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
                      </select>
                      <select className="cmp-select" value={valor(c, "medio")} onChange={(e) => cambiar(c, "medio", e.target.value)} aria-label="Medio de pago">
                        {MEDIOS.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
                      </select>
                      <input
                        className="cmp-input"
                        inputMode="numeric"
                        placeholder="Monto"
                        value={valor(c, "monto")}
                        onChange={(e) => cambiar(c, "monto", e.target.value)}
                      />
                      <button
                        className="boton chico"
                        disabled={ocupado === c.id || !valor(c, "alumno_id") || !valor(c, "mes")}
                        onClick={() => confirmar(c)}
                      >
                        Aprobar
                      </button>
                      <button className="boton chico claro" disabled={ocupado === c.id} onClick={() => rechazar(c)}>Rechazar</button>
                    </div>
                  </>
                )}

                {c.estado === "confirmado" && (
                  <div className="cmp-acciones">
                    <span className="cmp-origen">{c.pago_id ? `Cargado en Cuotas (pago #${c.pago_id})` : "Sin pago en Cuotas"}</span>
                    <span className="cmp-espacio" />
                    <button className="boton chico claro" disabled={ocupado === c.id} onClick={() => desaprobar(c)}>Volver a pendiente</button>
                    <button className="boton chico claro" disabled={ocupado === c.id} onClick={() => rechazar(c)}>Rechazar</button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
