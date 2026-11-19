import { useEffect, useState } from "react";
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
  const [frenadoHasta, setFrenadoHasta] = useState(0); // con 429: hasta cuándo no dejo mandar

  // cuando vence la espera se habilita el botón solo
  useEffect(() => {
    if (!frenadoHasta) return;
    const t = setTimeout(() => setFrenadoHasta(0), Math.max(0, frenadoHasta - Date.now()));
    return () => clearTimeout(t);
  }, [frenadoHasta]);

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
      if (err.status === 429) setFrenadoHasta(Date.now() + (err.reintentarEn || 60) * 1000);
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
        <button className="boton" disabled={enviando || frenadoHasta > 0}>
          {enviando ? "Entrando…" : frenadoHasta ? "Esperá unos minutos" : "Entrar"}
        </button>
        <Link to="/registro" className="login-link">¿No tenés cuenta? Pedí acceso</Link>
      </form>
    </div>
  );
}