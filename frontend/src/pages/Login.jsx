import { useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { useAuth } from "../auth.jsx";
import { MARCA } from "../marca.js";
import Logo from "../Logo.jsx";

export default function Login() {
  const { usuario, entrar, avisoSesion } = useAuth();
  const navegar = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [enviando, setEnviando] = useState(false);

  if (usuario) return <Navigate to="/" replace />;

  async function enviar(e) {
    e.preventDefault();
    setError("");
    setEnviando(true);
    try {
      await entrar(email.trim(), password);
      navegar("/");
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
        <h2>Entrá a tu cuenta</h2>
        {avisoSesion && !error && <div className="msg-error" role="status">{avisoSesion}</div>}
        <div className="campo">
          <label htmlFor="email">Email</label>
          <input id="email" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </div>
        <div className="campo">
          <label htmlFor="clave">Contraseña</label>
          <input id="clave" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </div>
        {error && <div className="msg-error" role="alert">{error}</div>}
        <button className="boton" disabled={enviando}>{enviando ? "Entrando…" : "Entrar"}</button>
        <Link to="/registro" className="login-link">¿No tenés cuenta? Pedí acceso</Link>
      </form>
    </div>
  );
}