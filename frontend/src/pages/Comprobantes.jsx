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

export default function Comprobantes() {
  const [filtro, setFiltro] = useState("pendiente");
  const [lista, setLista] = useState(null);
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");
  const [montos, setMontos] = useState({});
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

  async function confirmar(c) {
    setError(""); setAviso(""); setResultado(null);
    const n = numero(montos[c.id] ?? c.monto ?? "");
    if (!(n > 0)) { setError("Poné el monto antes de confirmar."); return; }
    setOcupado(c.id);
    try {
      await api(`/api/comprobantes/${c.id}/confirmar`, { metodo: "POST", cuerpo: { monto: n } });
      setAviso(`Confirmado: ${c.alumno || c.telefono} por ${peso.format(n)}.`);
      await cargar();
    } catch (e) {
      setError(e.message);
    }
    setOcupado(null);
  }

  async function rechazar(c) {
    if (!window.confirm(`¿Rechazar el comprobante de ${c.alumno || c.telefono}?`)) return;
    setError(""); setAviso(""); setResultado(null);
    setOcupado(c.id);
    try {
      await api(`/api/comprobantes/${c.id}/rechazar`, { metodo: "POST" });
      setAviso("Comprobante rechazado.");
      await cargar();
    } catch (e) {
      setError(e.message);
    }
    setOcupado(null);
  }

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
      <p className="cmp-sub">Lo que avisan los alumnos por WhatsApp. Confirmás el monto y después lo pasás a la planilla.</p>

      <div className="cmp-barra">
        {FILTROS.map(([valor, texto]) => (
          <button key={valor} className={"cmp-filtro" + (filtro === valor ? " activo" : "")} onClick={() => setFiltro(valor)}>
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
          {lista.map((c) => (
            <div key={c.id} className="cmp-card">
              <div className="cmp-fila">
                <div>
                  <div className="cmp-nombre">{c.alumno || c.telefono}</div>
                  <div className="cmp-sub">{c.mes} · {c.fecha}{c.alumno ? ` · ${c.telefono}` : ""}</div>
                </div>
                <div style={{ textAlign: "right" }}>
                  <div className="cmp-monto">{c.monto ? peso.format(c.monto) : "Sin monto"}</div>
                  <span className={"cmp-estado " + c.estado}>{c.estado}</span>
                </div>
              </div>
              {c.estado === "pendiente" && (
                <div className="cmp-acciones">
                  <input
                    className="cmp-input"
                    inputMode="numeric"
                    placeholder="Monto"
                    value={montos[c.id] ?? (c.monto ?? "")}
                    onChange={(e) => setMontos({ ...montos, [c.id]: e.target.value })}
                  />
                  <button className="boton chico" disabled={ocupado === c.id} onClick={() => confirmar(c)}>Confirmar</button>
                  <button className="boton chico claro" disabled={ocupado === c.id} onClick={() => rechazar(c)}>Rechazar</button>
                </div>
              )}
              {c.estado === "confirmado" && (
                <div className="cmp-acciones">
                  <button className="boton chico claro" disabled={ocupado === c.id} onClick={() => rechazar(c)}>Rechazar</button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}