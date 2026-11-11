import { useEffect, useState } from "react";
import { api } from "../api.js";
import "./consultas.css";

// le pasa al menú el número nuevo, así no lo vuelve a pedir
const avisarMenu = (n) => window.dispatchEvent(new CustomEvent("consultas-cambiaron", { detail: n }));

const fecha = (iso) =>
  iso ? new Date(iso).toLocaleString("es-AR", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "";

// link para contestar desde WhatsApp: wa.me quiere solo los dígitos
const linkWhatsapp = (tel) => `https://wa.me/${String(tel).replace(/\D/g, "")}`;

export default function Consultas() {
  const [filtro, setFiltro] = useState("abiertas");
  const [lista, setLista] = useState(null);
  const [error, setError] = useState("");
  const [ocupado, setOcupado] = useState(null);

  useEffect(() => {
    let vigente = true; // si cambian el filtro rápido, no piso con la respuesta vieja
    setLista(null);
    setError("");
    api(`/api/consultas?estado=${filtro}`)
      .then((l) => {
        if (!vigente) return;
        setLista(l);
        if (filtro === "abiertas") avisarMenu(l.length);
      })
      .catch((e) => {
        if (!vigente) return;
        setError(e.message);
        setLista([]);
      });
    return () => { vigente = false; };
  }, [filtro]);

  async function resolver(c) {
    setError("");
    setOcupado(c.id);
    try {
      const r = await api(`/api/consultas/${c.id}/resolver`, { metodo: "POST" });
      setLista((l) => l.filter((x) => x.id !== c.id));
      avisarMenu(r.total);
    } catch (e) {
      setError(e.message);
    } finally {
      setOcupado(null);
    }
  }

  return (
    <div>
      <div className="cabecera">
        <h1>Consultas</h1>
        <p className="sub">Lo que el agente no pudo resolver y te pasó a vos. Contestale al alumno y marcala como resuelta.</p>
      </div>

      <div className="cons-barra" role="group" aria-label="Filtrar consultas">
        {[["abiertas", "Abiertas"], ["resueltas", "Resueltas"]].map(([v, t]) => (
          <button key={v} className={"cons-filtro" + (filtro === v ? " activo" : "")} aria-pressed={filtro === v} onClick={() => setFiltro(v)}>
            {t}
          </button>
        ))}
      </div>

      {error && <div className="msg-error" role="alert">{error}</div>}
      {lista === null && <p>Cargando…</p>}
      {lista && lista.length === 0 && !error && (
        <div className="tarjeta">{filtro === "abiertas" ? "No hay consultas abiertas 👌" : "Todavía no hay consultas resueltas."}</div>
      )}

      <div className="cons-lista">
        {(lista || []).map((c) => (
          <div key={c.id} className="cons-card">
            <div className="cons-fila">
              <div>
                <span className="cons-tema">{c.tema || "consulta"}</span>
                <span className="cons-nombre">{c.alumno || (c.telefono ? "No es alumno" : "Sin teléfono")}</span>
              </div>
              <span className="cons-sub">{fecha(c.creado_en)}</span>
            </div>

            <p className="cons-mensaje">{c.mensaje}</p>

            <div className="cons-fila">
              {c.telefono ? (
                <a className="cons-tel" href={linkWhatsapp(c.telefono)} target="_blank" rel="noreferrer">
                  Contestar por WhatsApp ({c.telefono})
                </a>
              ) : <span />}
              {c.resuelta_en ? (
                <span className="cons-sub">Resuelta {c.resuelta_por ? `por ${c.resuelta_por} ` : ""}el {fecha(c.resuelta_en)}</span>
              ) : (
                <button className="boton" disabled={ocupado === c.id} onClick={() => resolver(c)}>Resuelta</button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
