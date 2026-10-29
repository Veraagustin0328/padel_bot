import { createContext, useContext, useEffect, useState } from "react";
import { api, guardarToken, borrarToken, leerToken } from "./api.js";

const Contexto = createContext(null);
export const useAuth = () => useContext(Contexto);

export function AuthProvider({ children }) {
  const [usuario, setUsuario] = useState(null);
  const [cargando, setCargando] = useState(Boolean(leerToken()));

  // si ya había una sesión guardada, la recuperamos
  useEffect(() => {
    if (!leerToken()) return;
    api("/api/auth/me")
      .then(setUsuario)
      .catch(() => setUsuario(null))
      .finally(() => setCargando(false));
  }, []);

  // si el servidor dice que la sesión venció, sacamos al usuario
  useEffect(() => {
    const alVencer = () => setUsuario(null);
    window.addEventListener("sesion-vencida", alVencer);
    return () => window.removeEventListener("sesion-vencida", alVencer);
  }, []);

  async function entrar(email, password) {
    const datos = await api("/api/auth/login", { metodo: "POST", cuerpo: { email, password } });
    guardarToken(datos.token);
    setUsuario(datos.usuario);
  }

  function salir() {
    borrarToken();
    setUsuario(null);
  }

  return <Contexto.Provider value={{ usuario, cargando, entrar, salir }}>{children}</Contexto.Provider>;
}