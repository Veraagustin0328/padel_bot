import { useEffect, useRef, useState } from "react";
import { ahora } from "../fechas.js";
import { api } from "../api.js";
import "./novedades.css";

export const NOMBRE_TIPO = { aviso: "Aviso", evento: "Evento", promo: "Promo", importante: "Importante" };

// para quién es cada novedad: el orden es el del selector
export const AUDIENCIAS = [
  { valor: "todos", nombre: "Todos", detalle: "Equipo, alumnos y padres" },
  { valor: "equipo", nombre: "Equipo", detalle: "Dueño, encargado y profes" },
  { valor: "alumnos", nombre: "Alumnos", detalle: "Jugadores y padres" },
];
const NOMBRE_AUDIENCIA = Object.fromEntries(AUDIENCIAS.map((a) => [a.valor, a.nombre]));

// fecha de hoy en hora local, para el min del input (toISOString daría la de UTC)
function hoyLocal() {
  const d = ahora();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

// "2026-11-12" -> "12/11/2026" sin pasar por Date (si no, el huso la corre un día)
export const fechaCorta = (iso) => iso.split("-").reverse().join("/");

// audiencia vacía a propósito: hay que elegirla, así nadie publica para los padres sin querer
const VACIO = { titulo: "", texto: "", tipo: "aviso", visible_hasta: "", audiencia: "" };

// tarjeta del Inicio: la ven todos los roles, solo trae las vigentes (de su audiencia)
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

// selector "Para quién es": radios grandes, uno abajo del otro en celu y en fila en compu
function SelectorAudiencia({ valor, onChange }) {
  return (
    <fieldset className="nov-audiencia">
      <legend>Para quién es</legend>
      <div className="nov-audiencia-opciones">
        {AUDIENCIAS.map((a) => (
          <label key={a.valor} className={"nov-aud-opcion" + (valor === a.valor ? " elegida" : "")}>
            <input type="radio" name="nov-audiencia" value={a.valor} checked={valor === a.valor}
              onChange={() => onChange(a.valor)} />
            <span className="nov-aud-textos">
              <strong>{a.nombre}</strong>
              <span>{a.detalle}</span>
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

// pantalla de gestión: admin y encargado
export default function Novedades() {
  const [lista, setLista] = useState(null);
  const [tipos, setTipos] = useState(Object.keys(NOMBRE_TIPO));
  const [form, setForm] = useState(VACIO);
  const [editando, setEditando] = useState(null); // la novedad original que se está editando
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const formRef = useRef(null);

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

  function empezarEdicion(n) {
    setError(""); setAviso("");
    setEditando(n);
    setForm({ titulo: n.titulo, texto: n.texto, tipo: n.tipo, visible_hasta: n.visible_hasta || "", audiencia: n.audiencia });
    formRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function cancelarEdicion() {
    setEditando(null);
    setForm(VACIO);
  }

  async function guardar(e) {
    e.preventDefault();
    setError(""); setAviso("");
    if (!form.titulo.trim() || !form.texto.trim()) return setError("Poné título y texto");
    if (!form.audiencia) return setError("Elegí para quién es la novedad");
    setOcupado(true);
    try {
      if (editando) {
        const cuerpo = { titulo: form.titulo, texto: form.texto, tipo: form.tipo, audiencia: form.audiencia };
        // la fecha va solo si la tocaron: una vencida tiene fecha pasada y el server la rebotaría
        if ((form.visible_hasta || null) !== (editando.visible_hasta || null)) cuerpo.visible_hasta = form.visible_hasta || null;
        await api(`/api/novedades/${editando.id}`, { metodo: "PATCH", cuerpo });
        setAviso(`Guardaste "${form.titulo.trim()}"`);
        setEditando(null);
      } else {
        await api("/api/novedades", { metodo: "POST", cuerpo: { ...form, visible_hasta: form.visible_hasta || null } });
        setAviso(`Listo, ya se ve en el Inicio (${NOMBRE_AUDIENCIA[form.audiencia].toLowerCase()})`);
      }
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
      if (editando?.id === n.id) cancelarEdicion();
      await cargar();
    } catch (e) {
      setError(e.message);
    }
  }

  const textoBoton = editando ? (ocupado ? "Guardando…" : "Guardar cambios") : (ocupado ? "Publicando…" : "Publicar");

  return (
    <div className="nov">
      <div className="cabecera">
        <div>
          <h1>Novedades</h1>
          <div className="sub">Aparecen en el Inicio de quien elijas: todos, el equipo o los alumnos.</div>
        </div>
      </div>
      {error && <div className="msg-error" role="alert">{error}</div>}
      {aviso && <div className="msg-ok" role="status">{aviso}</div>}

      <form className="tarjeta nov-form" onSubmit={guardar} ref={formRef}>
        <h2>{editando ? "Editar novedad" : "Nueva novedad"}</h2>
        <div className="campo">
          <label htmlFor="nov-titulo">Título</label>
          <input id="nov-titulo" maxLength={120} value={form.titulo} onChange={cambiar("titulo")} />
        </div>
        <div className="campo">
          <label htmlFor="nov-texto">Texto</label>
          <textarea id="nov-texto" rows={4} maxLength={2000} value={form.texto} onChange={cambiar("texto")} />
        </div>
        <SelectorAudiencia valor={form.audiencia} onChange={(a) => setForm({ ...form, audiencia: a })} />
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
          <button className="boton" disabled={ocupado}>{textoBoton}</button>
          {editando && <button type="button" className="boton claro" onClick={cancelarEdicion} disabled={ocupado}>Cancelar</button>}
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
                <span className={"nov-para aud-" + n.audiencia}>Para: {NOMBRE_AUDIENCIA[n.audiencia] || n.audiencia}</span>
                <strong>{n.titulo}</strong>
              </div>
              <p className="nov-texto">{n.texto}</p>
              <div className="nov-pie">
                <span className="nota">
                  {!n.vigente ? `Vencida el ${fechaCorta(n.visible_hasta)} · no se muestra`
                    : n.visible_hasta ? `Hasta el ${fechaCorta(n.visible_hasta)}` : "Sin vencimiento"}
                </span>
                <span className="nov-acciones">
                  <button className="boton chico claro" onClick={() => empezarEdicion(n)}>Editar</button>
                  <button className="boton chico claro" onClick={() => borrar(n)}>Borrar</button>
                </span>
              </div>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
