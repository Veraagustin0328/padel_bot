import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { useAuth } from "../auth.jsx";
import { esDueno } from "../roles.js";

const peso = new Intl.NumberFormat("es-AR", { style: "currency", currency: "ARS", maximumFractionDigits: 0 });
const hoy = () => new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);
const fechaAR = (iso) => (iso ? iso.split("-").reverse().join("/") : "—");
const numero = (txt) => Number(String(txt).replace(",", "."));

const NUEVO_VACIO = { franja: "", tipo: "", personas: "1", veces: "1", precio: "", desde: hoy() };

export default function Planes() {
  // el admin (encargado) solo mira; crear, cargar precios y aumentos es del dueño
  const { usuario } = useAuth();
  const editable = esDueno(usuario);
  const [datos, setDatos] = useState({ franjas: [], tipos: [], tarifas: [] });
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");
  const [ocupado, setOcupado] = useState(""); // qué botón está esperando ("" = ninguno)
  const enCurso = useRef(false); // candado contra el doble click

  // subir precios
  const [pct, setPct] = useState("10");
  const [redondeo, setRedondeo] = useState("100");
  const [desde, setDesde] = useState(hoy());
  const [incluirKids, setIncluirKids] = useState(true);
  const [vista, setVista] = useState(null);

  // tarifa nueva
  const [abierto, setAbierto] = useState(false);
  const [nuevo, setNuevo] = useState(NUEVO_VACIO);

  async function cargar() {
    try {
      setDatos(await api("/api/planes"));
    } catch (e) {
      setError(e.message);
    }
  }
  useEffect(() => { cargar(); }, []);

  const cuerpo = (confirmar) => ({
    porcentaje: numero(pct),
    redondeo: numero(redondeo),
    vigente_desde: desde,
    incluir_kids: incluirKids,
    confirmar,
  });

  // una acción por vez: apaga los botones y espera también la recarga
  async function hacer(clave, fn) {
    if (enCurso.current) return;
    enCurso.current = true;
    setOcupado(clave);
    setError(""); setAviso("");
    try {
      await fn();
    } finally {
      enCurso.current = false;
      setOcupado("");
    }
  }

  const verPrevia = () => hacer("previa", async () => {
    try {
      setVista(await api("/api/planes/aumento", { metodo: "POST", cuerpo: cuerpo(false) }));
    } catch (e) {
      setVista(null);
      setError(e.message);
    }
  });

  const aplicar = () => hacer("aplicar", async () => {
    try {
      await api("/api/planes/aumento", { metodo: "POST", cuerpo: cuerpo(true) });
      setVista(null);
      setAviso(`Listo, los precios nuevos rigen desde el ${fechaAR(desde)}.`);
      await cargar();
    } catch (e) {
      setError(e.message);
    }
  });

  const crearTarifa = (e) => {
    e.preventDefault();
    return hacer("crear", () => guardarTarifa());
  };

  async function guardarTarifa() {
    try {
      await api("/api/planes", {
        metodo: "POST",
        cuerpo: {
          franja: nuevo.franja,
          tipo: nuevo.tipo,
          personas: numero(nuevo.personas),
          veces_por_semana: numero(nuevo.veces),
          precio: numero(nuevo.precio),
          vigente_desde: nuevo.desde,
        },
      });
      setNuevo(NUEVO_VACIO);
      setAbierto(false);
      setAviso("Plan creado.");
      await cargar();
    } catch (e2) {
      setError(e2.message);
    }
  }

  // si cambia algún dato, la vista previa vieja ya no vale
  const cambiar = (setter) => (e) => { setter(e.target.value); setVista(null); };
  const campo = (k) => (e) => setNuevo({ ...nuevo, [k]: e.target.value });
  // algunas franjas aceptan solo ciertos tipos (Head Coach: solo particular)
  const franjaElegida = datos.franjas.find((f) => f.id === nuevo.franja);
  const elegirFranja = (e) => {
    const f = datos.franjas.find((x) => x.id === e.target.value);
    setNuevo({ ...nuevo, franja: e.target.value, tipo: f && !f.tipos.includes(nuevo.tipo) ? "" : nuevo.tipo });
  };

  // solo las que rigen hoy o tienen un precio programado
  const visibles = datos.tarifas.filter((t) => t.activo || t.precio_programado);
  const grupos = datos.franjas
    .map((f) => ({ ...f, tarifas: visibles.filter((t) => t.franja === f.id) }))
    .filter((g) => g.tarifas.length > 0);

  return (
    <>
      <div className="cabecera">
        <div>
          <h1>Planes y precios</h1>
          <div className="sub">
            {editable ? "Los cambios quedan con fecha. Los precios viejos no se pisan." : "Los precios los cambia el dueño."}
          </div>
        </div>
        {editable && (
          <button className="boton claro" onClick={() => setAbierto(!abierto)}>
            {abierto ? "Cerrar" : "Nuevo plan"}
          </button>
        )}
      </div>

      {error && <div className="msg-error" role="alert">{error}</div>}
      {aviso && <div className="msg-ok" role="status">{aviso}</div>}

      {editable && abierto && (
        <form className="tarjeta" onSubmit={crearTarifa}>
          <h2>Nuevo plan</h2>
          <div className="campos" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))" }}>
            <div className="campo">
              <label htmlFor="n-franja">Franja</label>
              <select id="n-franja" value={nuevo.franja} onChange={elegirFranja} required>
                <option value="">Elegí…</option>
                {datos.franjas.map((f) => <option key={f.id} value={f.id}>{f.nombre}</option>)}
              </select>
            </div>
            <div className="campo">
              <label htmlFor="n-tipo">Tipo</label>
              <select id="n-tipo" value={nuevo.tipo} onChange={campo("tipo")} required>
                <option value="">Elegí…</option>
                {datos.tipos
                  .filter((t) => !franjaElegida || franjaElegida.tipos.includes(t.id))
                  .map((t) => <option key={t.id} value={t.id}>{t.nombre}</option>)}
              </select>
            </div>
            {nuevo.tipo === "particular" && (
              <div className="campo">
                <label htmlFor="n-personas">Personas</label>
                <select id="n-personas" value={nuevo.personas} onChange={campo("personas")}>
                  <option value="1">1</option>
                  <option value="2">2 (c/u)</option>
                  <option value="3">3 o 4 (c/u)</option>
                </select>
              </div>
            )}
            <div className="campo">
              <label htmlFor="n-veces">Veces por semana</label>
              <input id="n-veces" inputMode="numeric" value={nuevo.veces} onChange={campo("veces")} required />
            </div>
            <div className="campo">
              <label htmlFor="n-precio">Precio por mes</label>
              <input id="n-precio" inputMode="numeric" value={nuevo.precio} onChange={campo("precio")} required />
            </div>
            <div className="campo">
              <label htmlFor="n-desde">Desde</label>
              <input id="n-desde" type="date" value={nuevo.desde} onChange={campo("desde")} required />
            </div>
          </div>
          <button className="boton" disabled={!!ocupado}>{ocupado === "crear" ? "Guardando…" : "Crear plan"}</button>
        </form>
      )}

      <div className="grilla">
        <section className="tarjeta ancha" aria-label="Precios vigentes">
          <h2>Precios vigentes</h2>
          {grupos.length === 0 && <div className="fila nota">Todavía no hay planes cargados.</div>}
          {grupos.map((g) => (
            <div key={g.id} style={{ marginTop: 16 }}>
              <div className="fila titulos">
                <div className="nombre">{g.nombre.toUpperCase()}</div>
                <div className="num">PRECIO</div>
                <div className="num">DESDE</div>
              </div>
              {g.tarifas.map((t) => (
                <div className="fila" key={t.id}>
                  <div className="nombre">
                    {t.nombre}
                    {t.precio_programado && (
                      <div className="programado">
                        {peso.format(t.precio_programado.monto)} desde el {fechaAR(t.precio_programado.desde)}
                      </div>
                    )}
                  </div>
                  <div className="num fuerte">{t.precio_vigente != null ? peso.format(t.precio_vigente) : "—"}</div>
                  <div className="num suave">{fechaAR(t.vigente_desde)}</div>
                </div>
              ))}
            </div>
          ))}
        </section>

        {editable && (
        <section className="tarjeta angosta" aria-label="Subir precios">
          <h2>Subir precios</h2>
          <div className="campos">
            <div className="campo">
              <label htmlFor="pct">Porcentaje</label>
              <input id="pct" inputMode="decimal" value={pct} onChange={cambiar(setPct)} />
            </div>
            <div className="campo">
              <label htmlFor="red">Redondear a</label>
              <input id="red" inputMode="numeric" value={redondeo} onChange={cambiar(setRedondeo)} />
            </div>
            <div className="campo">
              <label htmlFor="des">Desde</label>
              <input id="des" type="date" value={desde} onChange={cambiar(setDesde)} />
            </div>
          </div>
          <label style={{ display: "flex", alignItems: "center", gap: 8, margin: "8px 0" }}>
            <input
              type="checkbox"
              checked={incluirKids}
              onChange={(e) => { setIncluirKids(e.target.checked); setVista(null); }}
            />
            Incluir Kids
          </label>

          {vista && (
            <>
              <div className="previa">
                {vista.planes.map((p) => (
                  <div className="fila" key={p.id}>
                    <div className="nombre">{p.franja}: {p.nombre}</div>
                    <div className="num suave">{peso.format(p.precio_actual)}</div>
                    <div className="num fuerte">{peso.format(p.precio_nuevo)}</div>
                  </div>
                ))}
              </div>
              {vista.sin_precio.length > 0 && (
                <p className="nota">Sin precio en esa fecha (no se tocan): {vista.sin_precio.join(", ")}</p>
              )}
              <p className="nota">Vista previa: todavía no se guardó nada. Las cuotas de meses anteriores no cambian.</p>
            </>
          )}

          <div className="botones">
            <button className="boton claro" onClick={verPrevia} disabled={!!ocupado}>
              {ocupado === "previa" ? "Calculando…" : "Ver vista previa"}
            </button>
            <button className="boton" onClick={aplicar} disabled={!!ocupado || !vista || vista.planes.length === 0}>
              {ocupado === "aplicar" ? "Guardando…" : "Aplicar aumento"}
            </button>
          </div>
        </section>
        )}
      </div>
    </>
  );
}
