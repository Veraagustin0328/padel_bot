import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import "./notas.css";

const VACIO = { titulo: "", texto: "", alumno_id: "", fijada: false };

// "10/11 14:30": alcanza para saber de cuándo es
const cuando = (iso) =>
  iso
    ? new Date(iso).toLocaleString("es-AR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })
    : "";

// notas internas: solo dueño y admin (encargado). Primero celu
export default function Notas() {
  const [lista, setLista] = useState(null);
  const [alumnos, setAlumnos] = useState([]);
  const [buscar, setBuscar] = useState("");
  const [filtroAlumno, setFiltroAlumno] = useState("");
  const [form, setForm] = useState(VACIO);
  const [editando, setEditando] = useState(null); // id de la nota que se edita, o null si es nueva
  const [abierto, setAbierto] = useState(false);
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const formRef = useRef(null);

  async function cargar() {
    const params = new URLSearchParams();
    if (buscar.trim()) params.set("q", buscar.trim());
    if (filtroAlumno) params.set("alumno_id", filtroAlumno);
    try {
      setLista(await api(`/api/notas?${params}`));
    } catch (e) {
      setError(e.message);
      setLista([]);
    }
  }

  // la búsqueda espera a que dejes de tipear
  useEffect(() => {
    const t = setTimeout(cargar, 300);
    return () => clearTimeout(t);
  }, [buscar, filtroAlumno]);

  useEffect(() => {
    api("/api/notas/alumnos").then(setAlumnos).catch((e) => setError(`No pude traer la lista de alumnos: ${e.message}`));
  }, []);

  const cambiar = (campo) => (e) =>
    setForm({ ...form, [campo]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  function nueva() {
    setEditando(null);
    setForm({ ...VACIO, alumno_id: filtroAlumno });
    setAbierto(true);
    setError(""); setAviso("");
  }

  function editar(n) {
    setEditando(n.id);
    setForm({ titulo: n.titulo, texto: n.texto, alumno_id: n.alumno_id ? String(n.alumno_id) : "", fijada: n.fijada });
    setAbierto(true);
    setError(""); setAviso("");
    // en el celu el form queda arriba: lo llevo a la vista
    setTimeout(() => formRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 0);
  }

  function cerrar() {
    setAbierto(false);
    setEditando(null);
    setForm(VACIO);
  }

  async function guardar(e) {
    e.preventDefault();
    setError(""); setAviso("");
    if (!form.titulo.trim()) return setError("Poné un título");
    setOcupado(true);
    const cuerpo = { ...form, alumno_id: form.alumno_id ? Number(form.alumno_id) : null };
    try {
      if (editando) {
        await api(`/api/notas/${editando}`, { metodo: "PATCH", cuerpo });
        setAviso("Nota guardada");
      } else {
        await api("/api/notas", { metodo: "POST", cuerpo });
        setAviso("Nota creada");
      }
      cerrar();
      await cargar();
    } catch (e2) {
      setError(e2.message);
    } finally {
      setOcupado(false);
    }
  }

  async function fijar(n) {
    setError(""); setAviso("");
    try {
      await api(`/api/notas/${n.id}`, { metodo: "PATCH", cuerpo: { fijada: !n.fijada } });
      await cargar();
    } catch (e) {
      setError(e.message);
    }
  }

  async function borrar(n) {
    if (!window.confirm(`¿Borrar "${n.titulo}"? No se puede deshacer.`)) return;
    setError(""); setAviso("");
    try {
      await api(`/api/notas/${n.id}`, { metodo: "DELETE" });
      if (editando === n.id) cerrar();
      setAviso(`Borraste "${n.titulo}"`);
      await cargar();
    } catch (e) {
      setError(e.message);
    }
  }

  return (
    <div className="notas">
      <div className="cabecera">
        <div>
          <h1>Notas</h1>
          <div className="sub">Para vos y el equipo. Los profes y alumnos no las ven.</div>
        </div>
        {!abierto && <button className="boton" onClick={nueva}>Nueva nota</button>}
      </div>
      {error && <div className="msg-error" role="alert">{error}</div>}
      {aviso && <div className="msg-ok" role="status">{aviso}</div>}

      {abierto && (
        <form ref={formRef} className="tarjeta notas-form" onSubmit={guardar}>
          <h2>{editando ? "Editar nota" : "Nueva nota"}</h2>
          <div className="campo">
            <label htmlFor="nota-titulo">Título</label>
            <input id="nota-titulo" maxLength={120} value={form.titulo} onChange={cambiar("titulo")} autoFocus />
          </div>
          <div className="campo">
            <label htmlFor="nota-texto">Texto (opcional)</label>
            <textarea id="nota-texto" rows={4} maxLength={4000} value={form.texto} onChange={cambiar("texto")} />
          </div>
          <div className="campo">
            <label htmlFor="nota-alumno">Alumno (opcional)</label>
            <select id="nota-alumno" value={form.alumno_id} onChange={cambiar("alumno_id")}>
              <option value="">Sin alumno</option>
              {alumnos.map((a) => <option key={a.id} value={a.id}>{a.nombre}</option>)}
            </select>
          </div>
          <label className="notas-check">
            <input type="checkbox" checked={form.fijada} onChange={cambiar("fijada")} />
            Fijarla arriba
          </label>
          <div className="botones">
            <button className="boton" disabled={ocupado}>{ocupado ? "Guardando…" : "Guardar"}</button>
            <button type="button" className="boton claro" onClick={cerrar}>Cancelar</button>
          </div>
        </form>
      )}

      <div className="notas-filtros">
        <input type="search" placeholder="Buscar en las notas…" value={buscar} onChange={(e) => setBuscar(e.target.value)} aria-label="Buscar en las notas" />
        <select value={filtroAlumno} onChange={(e) => setFiltroAlumno(e.target.value)} aria-label="Filtrar por alumno">
          <option value="">Todos los alumnos</option>
          {alumnos.map((a) => <option key={a.id} value={a.id}>{a.nombre}</option>)}
        </select>
      </div>

      {lista === null && <p>Cargando…</p>}
      {lista && lista.length === 0 && (
        <div className="tarjeta nota">{buscar || filtroAlumno ? "No hay notas con esos filtros." : "Todavía no hay notas."}</div>
      )}
      <ul className="notas-lista">
        {(lista || []).map((n) => (
          <li key={n.id} className={"notas-item" + (n.fijada ? " fijada" : "")}>
            <div className="notas-arriba">
              {n.fijada && <span className="notas-chip">Fijada</span>}
              <strong>{n.titulo}</strong>
            </div>
            {n.alumno_nombre && <div className="notas-alumno">{n.alumno_nombre}</div>}
            {n.texto && <p className="notas-texto">{n.texto}</p>}
            <div className="notas-pie">
              <span className="nota">
                {n.creada_por_nombre || "—"} · {cuando(n.actualizada_en)}
              </span>
              <div className="notas-acciones">
                <button className="boton chico claro" onClick={() => fijar(n)}>{n.fijada ? "Desfijar" : "Fijar"}</button>
                <button className="boton chico claro" onClick={() => editar(n)}>Editar</button>
                <button className="boton chico claro" onClick={() => borrar(n)}>Borrar</button>
              </div>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
