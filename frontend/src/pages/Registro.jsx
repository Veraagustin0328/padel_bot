import { useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { useAuth } from "../auth.jsx";
import { api } from "../api.js";
import { MARCA } from "../marca.js";
import Logo from "../Logo.jsx";

// pantalla pública: la cuenta queda pendiente hasta que el admin la apruebe
export default function Registro() {
  const { usuario } = useAuth();
  const [nombre, setNombre] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [listo, setListo] = useState(false);
  const [enviando, setEnviando] = useState(false);

  if (usuario) return <Navigate to="/" replace />;

  async function enviar(e) {
    e.preventDefault();
    setError("");
    if (password.length < 8) {
      setError("La contraseña tiene que tener al menos 8 caracteres");
      return;
    }
    setEnviando(true);
    try {
      await api("/api/auth/registro", { metodo: "POST", cuerpo: { nombre: nombre.trim(), email: email.trim(), password } });
      setListo(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className="login">
      <form onSubmit={enviar} className="tarjeta">
        <div className="marca">
          <span className="logo"><Logo tam={72} pelota="#3667b8" /></span>
          {MARCA.nombre}
        </div>
        <h2>Pedí tu cuenta</h2>
        {listo ? (
          <div className="msg-ok" role="status">
            ¡Listo! Tu solicitud quedó pendiente. Cuando el admin la apruebe vas a poder entrar con tu email y contraseña.
          </div>
        ) : (
          <>
            <div className="campo">
              <label htmlFor="nombre">Nombre y apellido</label>
              <input id="nombre" autoComplete="name" maxLength={120} value={nombre} onChange={(e) => setNombre(e.target.value)} required />
            </div>
            <div className="campo">
              <label htmlFor="email">Email</label>
              <input id="email" type="email" autoComplete="email" maxLength={160} value={email} onChange={(e) => setEmail(e.target.value)} required />
            </div>
            <div className="campo">
              <label htmlFor="clave">Contraseña (mínimo 8)</label>
              <input id="clave" type="password" autoComplete="new-password" minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} required />
            </div>
            {error && <div className="msg-error" role="alert">{error}</div>}
            <button className="boton" disabled={enviando}>{enviando ? "Enviando…" : "Pedir acceso"}</button>
          </>
        )}
        <Link to="/login" className="login-link">Ya tengo cuenta, entrar</Link>
      </form>
    </div>
  );
}
