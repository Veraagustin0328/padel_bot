import { useEffect, useState } from "react";
import { api } from "../api.js";
import "./novedades.css";

export const NOMBRE_TIPO = { aviso: "Aviso", evento: "Evento", promo: "Promo", importante: "Importante" };

// fecha de hoy en hora local, para el min del input (toISOString daría la de UTC)
function hoyLocal() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

// "2026-11-12" -> "12/11/2026" sin pasar por Date (si no, el huso la corre un día)
export const fechaCorta = (iso) => iso.split("-").reverse().join("/");

const VACIO = { titulo: "", texto: "", tipo: "aviso", visible_hasta: "" };

// tarjeta del Inicio: la ven todos los roles, solo trae las vigentes
export function NovedadesVigentes() {
  const [lista, setLista] = useState(null);
  useEffect(() => {
    api("/api/novedades").then(setLista).catch(() => setLista([]));
  }, []);

  if (!lista || lista.length === 0) return null;
  return (
    <section className="tarjeta nov-vigentes" aria-label="Novedades">
      <h2>Novedades</h2>
      <ul className="nov-lista">
        {lista.map((n) => (
          <li key={n.id} className={"nov-item tipo-" + n.tipo}>
            <div className="nov-arriba">
              <span className="nov-tipo">{NOMBRE_TIPO[n.tipo] || n.tipo}</span>
              <strong>{n.titulo}</strong>
            </div>
            <p className="nov-texto">{n.texto}</p>
            {n.visible_hasta && <div className="nota">Hasta el {fechaCorta(n.visible_hasta)}</div>}
          </li>
        ))}
      </ul>
    </section>
  );
}

// pantalla de gestión: admin y encargado
export default function Novedades() {
  const [lista, setLista] = useState(null);
  const [tipos, setTipos] = useState(Object.keys(NOMBRE_TIPO));
  const [form, setForm] = useState(VACIO);
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");
  const [ocupado, setOcupado] = useState(false);

  async function cargar() {
    try {
      setLista(await api("/api/novedades?todas=1"));
    } catch (e) {
      setError(e.message);
      setLista([]);
    }
  }
  useEffect(() => {
    cargar();
    // si falla quedan los tipos de siempre, pero avisamos
    api("/api/novedades/tipos").then(setTipos).catch((e) => setError(`No pude traer los tipos de novedad: ${e.message}`));
  }, []);

  const cambiar = (campo) => (e) => setForm({ ...form, [campo]: e.target.value });

  async function publicar(e) {
    e.preventDefault();
    setError(""); setAviso("");
    if (!form.titulo.trim() || !form.texto.trim()) return setError("Poné título y texto");
    setOcupado(true);
    try {
      await api("/api/novedades", { metodo: "POST", cuerpo: { ...form, visible_hasta: form.visible_hasta || null } });
      setAviso("Listo, la novedad ya se ve en el Inicio");
      setForm(VACIO);
      await cargar();
    } catch (e) {
      setError(e.message);
    } finally {
      setOcupado(false);
    }
  }

  async function borrar(n) {
    if (!window.confirm(`¿Borrar "${n.titulo}"? No se puede deshacer.`)) return;
    setError(""); setAviso("");
    try {
      await api(`/api/novedades/${n.id}`, { metodo: "DELETE" });
      setAviso(`Borraste "${n.titulo}"`);
      await cargar();
    } catch (e) {
      setError(e.message);
    }
  }

  return (
    <div className="nov">
      <div className="cabecera">
        <div>
          <h1>Novedades</h1>
          <div className="sub">Lo que publiques acá aparece en el Inicio de todos.</div>
        </div>
      </div>
      {error && <div className="msg-error" role="alert">{error}</div>}
      {aviso && <div className="msg-ok" role="status">{aviso}</div>}

      <form className="tarjeta nov-form" onSubmit={publicar}>
        <h2>Nueva novedad</h2>
        <div className="campo">
          <label htmlFor="nov-titulo">Título</label>
          <input id="nov-titulo" maxLength={120} value={form.titulo} onChange={cambiar("titulo")} />
        </div>
        <div className="campo">
          <label htmlFor="nov-texto">Texto</label>
          <textarea id="nov-texto" rows={4} maxLength={2000} value={form.texto} onChange={cambiar("texto")} />
        </div>
        <div className="nov-par">
          <div className="campo">
            <label htmlFor="nov-tipo">Tipo</label>
            <select id="nov-tipo" value={form.tipo} onChange={cambiar("tipo")}>
              {tipos.map((t) => <option key={t} value={t}>{NOMBRE_TIPO[t] || t}</option>)}
            </select>
          </div>
          <div className="campo">
            <label htmlFor="nov-hasta">Se muestra hasta (opcional)</label>
            <input id="nov-hasta" type="date" min={hoyLocal()} value={form.visible_hasta} onChange={cambiar("visible_hasta")} />
          </div>
        </div>
        <div className="botones">
          <button className="boton" disabled={ocupado}>{ocupado ? "Publicando…" : "Publicar"}</button>
        </div>
      </form>

      <section className="tarjeta">
        <h2>Publicadas</h2>
        {lista === null && <p>Cargando…</p>}
        {lista && lista.length === 0 && <p className="nota">Todavía no hay novedades.</p>}
        <ul className="nov-lista">
          {(lista || []).map((n) => (
            <li key={n.id} className={"nov-item tipo-" + n.tipo + (n.vigente ? "" : " vencida")}>
              <div className="nov-arriba">
                <span className="nov-tipo">{NOMBRE_TIPO[n.tipo] || n.tipo}</span>
                <strong>{n.titulo}</strong>
              </div>
              <p className="nov-texto">{n.texto}</p>
              <div className="nov-pie">
                <span className="nota">
                  {!n.vigente ? `Vencida el ${fechaCorta(n.visible_hasta)} · no se muestra`
                    : n.visible_hasta ? `Hasta el ${fechaCorta(n.visible_hasta)}` : "Sin vencimiento"}
                </span>
                <button className="boton chico claro" onClick={() => borrar(n)}>Borrar</button>
              </div>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
