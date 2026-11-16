import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { entorno } from "../simulacion.js";
import "./simulador.css";

// chat de prueba con el agente: mismo camino que WhatsApp, pero no sale nada hacia Meta.
// Existe solo en simulación (en producción ni la ruta ni el backend están)

const TIPOS = [
  { v: "text", t: "Texto" },
  { v: "image", t: "Foto de comprobante" },
  { v: "document", t: "PDF de comprobante" },
  { v: "audio", t: "Audio" },
];

const hora = (iso) => (iso ? new Date(iso).toLocaleTimeString("es-AR", { hour: "2-digit", minute: "2-digit" }) : "");

function Herramientas({ lista }) {
  if (!lista?.length) return <div className="sim-herr vacio">Sin herramientas (respondió el modelo directo)</div>;
  return (
    <details className="sim-herr">
      <summary>{lista.length} {lista.length === 1 ? "herramienta" : "herramientas"}: {lista.map((h) => h.nombre || h.paso).join(", ")}</summary>
      {lista.map((h, i) => (
        <pre key={i}>{h.paso === "herramienta"
          ? `${h.nombre}(${JSON.stringify(h.args)})\n→ ${JSON.stringify(h.resultado, null, 1)}`
          : h.detalle}</pre>
      ))}
    </details>
  );
}

export default function Simulador() {
  const [telefonos, setTelefonos] = useState([]);
  const [tel, setTel] = useState("");
  const [mensajes, setMensajes] = useState([]);
  const [pausado, setPausado] = useState(false);
  const [texto, setTexto] = useState("");
  const [tipo, setTipo] = useState("text");
  const [ocupado, setOcupado] = useState(false);
  const [error, setError] = useState("");
  const [otros, setOtros] = useState([]);
  const abajo = useRef(null);

  const cargarTelefonos = useCallback(() => {
    api("/api/simulacion/telefonos").then((l) => {
      setTelefonos(l);
      setTel((t) => t || l[0]?.telefono || "");
    }).catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    cargarTelefonos();
  }, [cargarTelefonos]);

  // al cambiar de número traigo su charla guardada
  useEffect(() => {
    if (!tel) return;
    setOtros([]);
    api(`/api/simulacion/charla?telefono=${encodeURIComponent(tel)}`)
      .then((d) => {
        setMensajes((d.mensajes || []).map((m) => ({ ...m })));
        setPausado(d.pausado);
      })
      .catch((e) => setError(e.message));
  }, [tel]);

  // con llaves: en Chrome nuevo scrollIntoView devuelve una Promise, y si el efecto la devuelve
  // React la toma como limpieza, revienta y deja la pantalla en blanco
  useEffect(() => {
    abajo.current?.scrollIntoView({ block: "end" });
  }, [mensajes]);

  async function enviar(e) {
    e.preventDefault();
    if (ocupado || (tipo === "text" && !texto.trim())) return;
    setOcupado(true);
    setError("");
    const enviado = tipo === "text" ? texto : `[${TIPOS.find((x) => x.v === tipo).t}] ${texto}`.trim();
    setMensajes((m) => [...m, { rol: "user", contenido: enviado, hora: new Date().toISOString() }]);
    setTexto("");
    try {
      const r = await api("/api/simulacion/mensaje", { metodo: "POST", cuerpo: { telefono: tel, tipo, texto } });
      if (r.error) setError(r.error);
      const nuevas = r.respuestas.map((x) => ({ rol: "assistant", contenido: x.contenido, hora: x.hora }));
      if (!nuevas.length) nuevas.push({ rol: "sistema", contenido: `Sin respuesta (estado: ${r.estado || "?"})` });
      nuevas[nuevas.length - 1].herramientas = r.herramientas;
      nuevas[nuevas.length - 1].segundos = r.segundos;
      setMensajes((m) => [...m, ...nuevas]);
      setOtros(r.otros_envios);
      setPausado(r.pausado);
    } catch (err) {
      setError(err.message);
    } finally {
      setOcupado(false);
      setTipo("text");
    }
  }

  async function cambiarPausa() {
    try {
      const r = await api("/api/simulacion/pausa", { metodo: "POST", cuerpo: { telefono: tel, pausar: !pausado } });
      setPausado(r.pausado);
      cargarTelefonos();
    } catch (err) {
      setError(err.message);
    }
  }

  async function borrar() {
    if (!window.confirm("¿Borro la charla de este número? (solo en la simulación)")) return;
    await api("/api/simulacion/borrar-charla", { metodo: "POST", cuerpo: { telefono: tel } }).catch((e) => setError(e.message));
    setMensajes([]);
  }

  if (!entorno().simulacion) return <p>El simulador existe solo en la simulación.</p>;
  const esJefe = telefonos.find((t) => t.telefono === tel)?.etiqueta?.startsWith("Encargado");

  return (
    <div className="simulador">
      <div className="cabecera">
        <div>
          <h1>Simulador del agente</h1>
          <div className="sub">Hablale como si fuera WhatsApp. No sale nada hacia Meta, pero sí usa el modelo de verdad.</div>
        </div>
      </div>
      {error && <div className="msg-error" role="alert">{error}</div>}

      <div className="sim-controles">
        <label className="campo">
          <span>Número</span>
          <select value={tel} onChange={(e) => setTel(e.target.value)}>
            {telefonos.map((t) => (
              <option key={t.telefono} value={t.telefono}>{t.etiqueta}{t.pausado ? " · pausado" : ""} · {t.telefono}</option>
            ))}
          </select>
        </label>
        <div className="botones">
          {!esJefe && (
            <button className="boton chico claro" onClick={cambiarPausa}>{pausado ? "Reanudar agente" : "Pausar agente"}</button>
          )}
          <button className="boton chico claro" onClick={borrar}>Borrar charla</button>
        </div>
      </div>
      {pausado && <div className="sim-aviso">Agente pausado para este número: lo que escriba va a Consultas y no se contesta.</div>}

      <div className="tarjeta sim-chat">
        {mensajes.length === 0 && <div className="nota">Todavía no hay charla con este número.</div>}
        {mensajes.map((m, i) => (
          <div key={i} className={"sim-burbuja " + m.rol}>
            <div className="sim-texto">{m.contenido}</div>
            <div className="sim-pie">{hora(m.hora)}{m.segundos != null && ` · ${m.segundos} s`}</div>
            {m.herramientas && <Herramientas lista={m.herramientas} />}
          </div>
        ))}
        {ocupado && <div className="sim-burbuja assistant nota">escribiendo…</div>}
        <div ref={abajo} />
      </div>

      {otros.length > 0 && (
        <div className="tarjeta sim-otros">
          <strong>También se “mandó”:</strong>
          {otros.map((o) => <div key={o.id} className="nota">a {o.telefono}: {o.contenido}</div>)}
        </div>
      )}

      <form className="sim-enviar" onSubmit={enviar}>
        <select value={tipo} onChange={(e) => setTipo(e.target.value)} aria-label="Tipo de mensaje">
          {TIPOS.map((t) => <option key={t.v} value={t.v}>{t.t}</option>)}
        </select>
        <input
          value={texto}
          onChange={(e) => setTexto(e.target.value)}
          placeholder={tipo === "text" ? "Escribí como la familia…" : tipo === "audio" ? "(el audio no lleva texto)" : "Texto del comprobante (opcional, ej: 45000)"}
          disabled={tipo === "audio"}
          aria-label="Mensaje"
        />
        <button className="boton" disabled={ocupado || !tel}>{ocupado ? "Esperando…" : "Mandar"}</button>
      </form>
    </div>
  );
}
