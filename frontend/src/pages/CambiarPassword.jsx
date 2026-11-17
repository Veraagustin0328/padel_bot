import { useState } from "react";
import { api } from "../api.js";
import { useAuth } from "../auth.jsx";

const MINIMO = 8;

// obligatorio: primer ingreso o clave reseteada, no puede usar el panel hasta cambiarla
export default function CambiarPassword({ obligatorio = false }) {
  const { actualizarSesion, salir } = useAuth();
  const [actual, setActual] = useState("");
  const [nueva, setNueva] = useState("");
  const [repetida, setRepetida] = useState("");
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");
  const [enviando, setEnviando] = useState(false);

  async function enviar(e) {
    e.preventDefault();
    setError(""); setAviso("");
    if (nueva.length < MINIMO) return setError(`La contraseña nueva tiene que tener al menos ${MINIMO} caracteres`);
    if (nueva !== repetida) return setError("Las dos contraseñas nuevas no coinciden");
    setEnviando(true);
    try {
      const r = await api("/api/auth/cambiar-password", { metodo: "POST", cuerpo: { actual, nueva } });
      setAviso(r.mensaje || "Listo, cambiaste tu contraseña");
      setActual(""); setNueva(""); setRepetida("");
      actualizarSesion(r.token, r.usuario); // si era obligatorio, con esto ya entra al panel
    } catch (err) {
      setError(err.message);
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div>
      <div className="cabecera">
        <h1>Cambiar contraseña</h1>
        {obligatorio && <p className="sub">Estás entrando con una contraseña temporal. Elegí una tuya para seguir.</p>}
      </div>
      <form onSubmit={enviar} className="tarjeta form-clave">
        <div className="campo">
          <label htmlFor="clave-actual">{obligatorio ? "Contraseña temporal" : "Contraseña actual"}</label>
          <input id="clave-actual" type="password" autoComplete="current-password" value={actual} onChange={(e) => setActual(e.target.value)} required />
        </div>
        <div className="campo">
          <label htmlFor="clave-nueva">Contraseña nueva (mínimo {MINIMO} caracteres)</label>
          <input id="clave-nueva" type="password" autoComplete="new-password" minLength={MINIMO} value={nueva} onChange={(e) => setNueva(e.target.value)} required />
        </div>
        <div className="campo">
          <label htmlFor="clave-repetida">Repetí la nueva</label>
          <input id="clave-repetida" type="password" autoComplete="new-password" value={repetida} onChange={(e) => setRepetida(e.target.value)} required />
        </div>
        {error && <div className="msg-error" role="alert">{error}</div>}
        {aviso && <div className="msg-ok" role="status">{aviso}</div>}
        <button className="boton" disabled={enviando}>{enviando ? "Guardando…" : "Guardar"}</button>
        {obligatorio && <button type="button" className="boton claro" style={{ marginLeft: 8 }} onClick={salir}>Salir</button>}
      </form>
    </div>
  );
}
