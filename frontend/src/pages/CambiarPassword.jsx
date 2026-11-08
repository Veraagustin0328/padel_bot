import { useState } from "react";
import { api } from "../api.js";

const MINIMO = 8;

export default function CambiarPassword() {
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
      </div>
      <form onSubmit={enviar} className="tarjeta form-clave">
        <div className="campo">
          <label htmlFor="clave-actual">Contraseña actual</label>
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
      </form>
    </div>
  );
}
