import { Fragment, useEffect, useRef, useState } from "react";
import { ahora } from "../fechas.js";
import { api } from "../api.js";
import { useAuth } from "../auth.jsx";
import { esDueno } from "../roles.js";

const peso = new Intl.NumberFormat("es-AR", { style: "currency", currency: "ARS", maximumFractionDigits: 0 });
const hoy = () => {
  const d = ahora();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
};
const fechaAR = (iso) => (iso ? iso.split("-").reverse().join("/") : "—");
const numero = (txt) => Number(String(txt).replace(",", "."));

// franja + tipo + personas + veces: no cambia aunque se cargue o quite una fila (el id sí)
const claveDe = (t) => `${t.franja}|${t.tipo}|${t.personas}|${t.veces_por_semana}`;
// función: la fecha se toma al abrir, no al importar
const nuevoVacio = () => ({ franja: "", tipo: "", personas: "1", veces: "1", precio: "", desde: hoy() });
const AVISO = { background: "#fef3c7", color: "#92400e", padding: "10px 14px", borderRadius: 8, margin: "8px 0" };

// historial de precios de una tarifa, con editar / quitar / dar de baja (solo el dueño).
// Antes de confirmar se pide el chequeo: si alguna cuota generada usó la fila, no se toca y se
// ofrece cargar un precio nuevo con fecha o darla de baja desde una fecha.
function PreciosDeTarifa({ tarifa, ocupado, hacer, alCambiar }) {
  const [filas, setFilas] = useState(null);
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");
  const [accion, setAccion] = useState(null); // { tipo: editar|quitar|baja|nuevo, fila, chequeo }
  const [precio, setPrecio] = useState("");
  const [fecha, setFecha] = useState(hoy());

  async function cargarFilas() {
    try {
      setFilas(await api(`/api/planes/${tarifa.id}/precios`));
    } catch (e) {
      setError(e.message);
    }
  }
  useEffect(() => { cargarFilas(); }, [tarifa.id]);

  const cerrar = () => { setAccion(null); setPrecio(""); setFecha(hoy()); };

  // editar o quitar: primero el chequeo, así el dueño ve qué va a pasar antes de confirmar
  const abrir = (tipo, fila) => hacer(`chequeo-${fila.id}`, async () => {
    setError(""); setAviso("");
    try {
      const chequeo = await api(`/api/planes/filas/${fila.id}/chequeo`);
      setAccion({ tipo, fila, chequeo });
      setPrecio(String(fila.monto));
      setFecha(hoy());
    } catch (e) {
      setError(e.message);
    }
  });
  const abrirBaja = () => { setError(""); setAviso(""); setFecha(hoy()); setAccion({ tipo: "baja" }); };
  const abrirNuevo = () => { setError(""); setAviso(""); setFecha(hoy()); setPrecio(""); setAccion({ tipo: "nuevo" }); };

  // después de guardar: recarga la lista y la pantalla de arriba
  async function listo(texto) {
    cerrar();
    setAviso(texto);
    await cargarFilas();
    await alCambiar();
  }
  const correr = (clave, fn) => hacer(clave, async () => {
    setError(""); setAviso("");
    try {
      await fn();
    } catch (e) {
      setError(e.message);
    }
  });

  const guardarEdicion = () => correr("editar", async () => {
    await api(`/api/planes/filas/${accion.fila.id}`, { metodo: "PATCH", cuerpo: { precio: numero(precio) } });
    await listo("Precio cambiado.");
  });
  const quitar = () => correr("quitar", async () => {
    const r = await api(`/api/planes/filas/${accion.fila.id}`, { metodo: "DELETE" });
    if (!r.tarifa) {
      cerrar();
      await alCambiar(); // era la única fila: la tarifa ya no existe
      return;
    }
    await listo("Fila quitada.");
  });
  const darDeBaja = () => correr("baja", async () => {
    const r = await api(`/api/planes/filas/${tarifa.id}/baja`, { metodo: "POST", cuerpo: { desde: fecha } });
    await listo(`Dada de baja desde el ${fechaAR(fecha)}.` + (r.aviso ? ` ${r.aviso}` : ""));
  });
  const cargarNuevo = () => correr("nuevo", async () => {
    await api(`/api/planes/${tarifa.id}/precios`, {
      metodo: "POST", cuerpo: { monto: numero(precio), vigente_desde: fecha },
    });
    await listo(`Precio nuevo cargado desde el ${fechaAR(fecha)}.`);
  });

  const usada = accion?.chequeo && !accion.chequeo.puede_directo;

  return (
    <div className="previa" style={{ margin: "6px 0 12px" }}>
      {error && <div className="msg-error" role="alert">{error}</div>}
      {aviso && <div className="msg-ok" role="status">{aviso}</div>}
      {!filas && !error && <div className="fila nota">Cargando…</div>}
      {filas && filas.map((f) => (
        <div className="fila" key={f.id} style={{ flexWrap: "wrap" }}>
          <div className="nombre">
            desde el {fechaAR(f.vigente_desde)}
            {!f.activa && <span className="programado"> · de baja</span>}
          </div>
          <div className="num">{f.activa ? peso.format(f.monto) : "—"}</div>
          <div className="botones" style={{ margin: 0 }}>
            {f.activa && (
              <button className="boton chico claro" onClick={() => abrir("editar", f)} disabled={!!ocupado}>
                {ocupado === `chequeo-${f.id}` ? "…" : "Editar"}
              </button>
            )}
            <button className="boton chico claro" onClick={() => abrir("quitar", f)} disabled={!!ocupado}>Quitar</button>
          </div>
        </div>
      ))}

      {filas && !accion && (
        <div className="botones">
          <button className="boton chico claro" onClick={abrirNuevo} disabled={!!ocupado}>Cargar precio nuevo</button>
          <button className="boton chico claro" onClick={abrirBaja} disabled={!!ocupado}>Dar de baja desde…</button>
        </div>
      )}

      {accion && (accion.tipo === "editar" || accion.tipo === "quitar") && (
        <div style={{ marginTop: 8 }}>
          <div style={usada ? AVISO : undefined} className={usada ? "" : "nota"}>{accion.chequeo.explicacion}</div>
          {!usada && accion.tipo === "editar" && (
            <div className="campos">
              <div className="campo">
                <label htmlFor="ed-precio">Precio nuevo de esta fila</label>
                <input id="ed-precio" inputMode="numeric" value={precio} onChange={(e) => setPrecio(e.target.value)} />
              </div>
            </div>
          )}
          {!usada && accion.tipo === "quitar" && (
            <p className="nota">Se borra la fila del {fechaAR(accion.fila.vigente_desde)}. Queda registrado quién lo hizo.</p>
          )}
          <div className="botones">
            {!usada && accion.tipo === "editar" && (
              <button className="boton chico" onClick={guardarEdicion} disabled={!!ocupado}>
                {ocupado === "editar" ? "Guardando…" : "Guardar precio"}
              </button>
            )}
            {!usada && accion.tipo === "quitar" && (
              <button className="boton chico" onClick={quitar} disabled={!!ocupado}>
                {ocupado === "quitar" ? "Quitando…" : "Sí, quitar esta fila"}
              </button>
            )}
            {usada && (
              <>
                <button className="boton chico" onClick={abrirNuevo} disabled={!!ocupado}>Cargar precio nuevo con fecha</button>
                <button className="boton chico claro" onClick={abrirBaja} disabled={!!ocupado}>Dar de baja desde una fecha</button>
              </>
            )}
            <button className="boton chico claro" onClick={cerrar} disabled={!!ocupado}>Cancelar</button>
          </div>
        </div>
      )}

      {accion && (accion.tipo === "nuevo" || accion.tipo === "baja") && (
        <div style={{ marginTop: 8 }}>
          <p className="nota">
            {accion.tipo === "nuevo"
              ? "Se agrega un precio con su fecha. Los precios anteriores y las cuotas ya generadas no cambian."
              : "Desde esa fecha la tarifa queda sin precio. Lo anterior no cambia. Va desde hoy o más adelante."}
          </p>
          <div className="campos">
            {accion.tipo === "nuevo" && (
              <div className="campo">
                <label htmlFor="nu-precio">Precio por mes</label>
                <input id="nu-precio" inputMode="numeric" value={precio} onChange={(e) => setPrecio(e.target.value)} />
              </div>
            )}
            <div className="campo">
              <label htmlFor="nu-fecha">Desde</label>
              <input id="nu-fecha" type="date" value={fecha} min={accion.tipo === "baja" ? hoy() : undefined}
                     onChange={(e) => setFecha(e.target.value)} />
            </div>
          </div>
          <div className="botones">
            <button className="boton chico" onClick={accion.tipo === "nuevo" ? cargarNuevo : darDeBaja} disabled={!!ocupado}>
              {ocupado === accion.tipo ? "Guardando…" : accion.tipo === "nuevo" ? "Cargar precio" : "Dar de baja"}
            </button>
            <button className="boton chico claro" onClick={cerrar} disabled={!!ocupado}>Cancelar</button>
          </div>
        </div>
      )}
    </div>
  );
}

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
  const [abierta, setAbierta] = useState(null); // claveDe de la tarifa con "Ver precios" abierto
  const [verBajas, setVerBajas] = useState(false); // el dueño puede ver las dadas de baja (para deshacer)

  // tarifa nueva
  const [abierto, setAbierto] = useState(false);
  const [nuevo, setNuevo] = useState(nuevoVacio);

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
      setNuevo(nuevoVacio());
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
  const visibles = datos.tarifas.filter(
    (t) => t.activo || t.precio_programado || (editable && (verBajas || claveDe(t) === abierta)));
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
          {editable && (
            <label className="nota" style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <input type="checkbox" checked={verBajas} onChange={(e) => setVerBajas(e.target.checked)} />
              Mostrar las dadas de baja
            </label>
          )}
          {grupos.length === 0 && <div className="fila nota">Todavía no hay planes cargados.</div>}
          {grupos.map((g) => (
            <div key={g.id} style={{ marginTop: 16 }}>
              <div className="fila titulos">
                <div className="nombre">{g.nombre.toUpperCase()}</div>
                <div className="num">PRECIO</div>
                <div className="num">DESDE</div>
              </div>
              {g.tarifas.map((t) => (
                <Fragment key={claveDe(t)}>
                  <div className="fila">
                    <div className="nombre">
                      {t.nombre}
                      {!t.activo && !t.precio_programado && <span className="programado"> · de baja</span>}
                      {t.precio_programado && (
                        <div className="programado">
                          {peso.format(t.precio_programado.monto)} desde el {fechaAR(t.precio_programado.desde)}
                        </div>
                      )}
                      {/* abajo del nombre: así no corre las columnas de precio y fecha */}
                      {editable && (
                        <div style={{ marginTop: 6 }}>
                          <button className="boton chico claro" disabled={!!ocupado}
                                  onClick={() => setAbierta(abierta === claveDe(t) ? null : claveDe(t))}>
                            {abierta === claveDe(t) ? "Cerrar precios" : "Ver precios"}
                          </button>
                        </div>
                      )}
                    </div>
                    <div className="num fuerte">{t.precio_vigente != null ? peso.format(t.precio_vigente) : "—"}</div>
                    <div className="num suave">{fechaAR(t.vigente_desde)}</div>
                  </div>
                  {editable && abierta === claveDe(t) && (
                    <PreciosDeTarifa tarifa={t} ocupado={ocupado} hacer={hacer} alCambiar={cargar} />
                  )}
                </Fragment>
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
              {vista.bloqueadas?.length > 0 && (
                <div style={AVISO} role="alert">
                  Estas ya tienen un precio en esa fecha que usaron cuotas generadas, no se pueden pisar:{" "}
                  {vista.bloqueadas.join(", ")}. Elegí otra fecha.
                </div>
              )}
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
            <button className="boton" onClick={aplicar} disabled={!!ocupado || !vista || vista.planes.length === 0 || vista.bloqueadas?.length > 0}>
              {ocupado === "aplicar" ? "Guardando…" : "Aplicar aumento"}
            </button>
          </div>
        </section>
        )}
      </div>
    </>
  );
}
