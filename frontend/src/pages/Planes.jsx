import { useEffect, useState } from "react";
import { api } from "../api.js";

const peso = new Intl.NumberFormat("es-AR", { style: "currency", currency: "ARS", maximumFractionDigits: 0 });
const hoy = () => new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);
const fechaAR = (iso) => (iso ? iso.split("-").reverse().join("/") : "—");
const numero = (txt) => Number(String(txt).replace(",", "."));

export default function Planes() {
  const [planes, setPlanes] = useState([]);
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");

  // subir precios
  const [pct, setPct] = useState("10");
  const [redondeo, setRedondeo] = useState("100");
  const [desde, setDesde] = useState(hoy());
  const [vista, setVista] = useState(null);

  // plan nuevo
  const [abierto, setAbierto] = useState(false);
  const [nuevo, setNuevo] = useState({ nombre: "", grupales: "0", particulares: "0", precio: "" });

  async function cargar() {
    try {
      const lista = await api("/api/planes");
      setPlanes(lista.filter((p) => p.activo));
    } catch (e) {
      setError(e.message);
    }
  }
  useEffect(() => { cargar(); }, []);

  const cuerpo = (confirmar) => ({
    porcentaje: numero(pct),
    redondeo: numero(redondeo),
    vigente_desde: desde,
    confirmar,
  });

  async function verPrevia() {
    setError(""); setAviso("");
    try {
      setVista(await api("/api/planes/aumento", { metodo: "POST", cuerpo: cuerpo(false) }));
    } catch (e) {
      setVista(null);
      setError(e.message);
    }
  }

  async function aplicar() {
    setError(""); setAviso("");
    try {
      await api("/api/planes/aumento", { metodo: "POST", cuerpo: cuerpo(true) });
      setVista(null);
      setAviso(`Listo, los precios nuevos rigen desde el ${fechaAR(desde)}.`);
      cargar();
    } catch (e) {
      setError(e.message);
    }
  }

  async function crearPlan(e) {
    e.preventDefault();
    setError(""); setAviso("");
    try {
      await api("/api/planes", {
        metodo: "POST",
        cuerpo: {
          nombre: nuevo.nombre,
          grupales_por_semana: numero(nuevo.grupales),
          particulares_por_semana: numero(nuevo.particulares),
          precio: numero(nuevo.precio),
        },
      });
      setNuevo({ nombre: "", grupales: "0", particulares: "0", precio: "" });
      setAbierto(false);
      setAviso("Plan creado.");
      cargar();
    } catch (e2) {
      setError(e2.message);
    }
  }

  // si cambia algún dato, la vista previa vieja ya no vale
  const cambiar = (setter) => (e) => { setter(e.target.value); setVista(null); };

  return (
    <>
      <div className="cabecera">
        <div>
          <h1>Planes y precios</h1>
          <div className="sub">Los cambios quedan con fecha. Los precios viejos no se pisan.</div>
        </div>
        <button className="boton claro" onClick={() => setAbierto(!abierto)}>
          {abierto ? "Cerrar" : "Nuevo plan"}
        </button>
      </div>

      {error && <div className="msg-error" role="alert">{error}</div>}
      {aviso && <div className="msg-ok" role="status">{aviso}</div>}

      {abierto && (
        <form className="tarjeta" onSubmit={crearPlan}>
          <h2>Nuevo plan</h2>
          <div className="campos" style={{ gridTemplateColumns: "2fr 1fr 1fr 1fr" }}>
            <div className="campo">
              <label htmlFor="n-nombre">Nombre</label>
              <input id="n-nombre" value={nuevo.nombre} onChange={(e) => setNuevo({ ...nuevo, nombre: e.target.value })} required />
            </div>
            <div className="campo">
              <label htmlFor="n-g">Grupales por semana</label>
              <input id="n-g" inputMode="numeric" value={nuevo.grupales} onChange={(e) => setNuevo({ ...nuevo, grupales: e.target.value })} />
            </div>
            <div className="campo">
              <label htmlFor="n-p">Particulares por semana</label>
              <input id="n-p" inputMode="numeric" value={nuevo.particulares} onChange={(e) => setNuevo({ ...nuevo, particulares: e.target.value })} />
            </div>
            <div className="campo">
              <label htmlFor="n-precio">Precio</label>
              <input id="n-precio" inputMode="numeric" value={nuevo.precio} onChange={(e) => setNuevo({ ...nuevo, precio: e.target.value })} required />
            </div>
          </div>
          <button className="boton">Crear plan</button>
        </form>
      )}

      <div className="grilla">
        <section className="tarjeta ancha" aria-label="Precios vigentes">
          <h2>Precios vigentes</h2>
          <div className="fila titulos" style={{ marginTop: 12 }}>
            <div className="nombre">PLAN</div>
            <div className="num">PRECIO</div>
            <div className="num">DESDE</div>
          </div>
          {planes.length === 0 && <div className="fila nota">Todavía no hay planes cargados.</div>}
          {planes.map((p) => (
            <div className="fila" key={p.id}>
              <div className="nombre">
                {p.nombre}
                {p.precio_programado && (
                  <div className="programado">
                    {peso.format(p.precio_programado.monto)} desde el {fechaAR(p.precio_programado.desde)}
                  </div>
                )}
              </div>
              <div className="num fuerte">{p.precio_vigente != null ? peso.format(p.precio_vigente) : "—"}</div>
              <div className="num suave">{fechaAR(p.vigente_desde)}</div>
            </div>
          ))}
        </section>

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

          {vista && (
            <>
              <div className="previa">
                {vista.planes.map((p) => (
                  <div className="fila" key={p.id}>
                    <div className="nombre">{p.nombre}</div>
                    <div className="num suave">{peso.format(p.precio_actual)}</div>
                    <div className="num fuerte">{peso.format(p.precio_nuevo)}</div>
                  </div>
                ))}
              </div>
              {vista.sin_precio.length > 0 && (
                <p className="nota">Sin precio cargado (no se tocan): {vista.sin_precio.join(", ")}</p>
              )}
              <p className="nota">Vista previa: todavía no se guardó nada. Las cuotas de meses anteriores no cambian.</p>
            </>
          )}

          <div className="botones">
            <button className="boton claro" onClick={verPrevia}>Ver vista previa</button>
            <button className="boton" onClick={aplicar} disabled={!vista || vista.planes.length === 0}>Aplicar aumento</button>
          </div>
        </section>
      </div>
    </>
  );
}