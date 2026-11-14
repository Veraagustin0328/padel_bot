import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, guardarToken, borrarToken, leerToken } from "./api.js";

const Contexto = createContext(null);
export const useAuth = () => useContext(Contexto);

const VENCIDA = "Tu sesión venció, entrá de nuevo.";

// qué decirle en el login según por qué lo sacó el servidor
function motivoSalida(texto) {
  return /inactivo/i.test(texto || "") ? "Tu usuario está inactivo. Hablá con el encargado." : VENCIDA;
}

export function AuthProvider({ children }) {
  const [usuario, setUsuario] = useState(null);
  const [cargando, setCargando] = useState(Boolean(leerToken()));
  // aviso para el login cuando lo sacamos por sesión vencida
  const [avisoSesion, setAvisoSesion] = useState("");
  // si no se pudo hablar con el servidor al arrancar: no lo sacamos, dejamos reintentar
  const [errorConexion, setErrorConexion] = useState("");

  // si ya había una sesión guardada, la recuperamos
  const recuperar = useCallback(() => {
    if (!leerToken()) {
      setCargando(false);
      return;
    }
    setCargando(true);
    setErrorConexion("");
    api("/api/auth/me")
      .then(setUsuario)
      .catch((e) => {
        if (e.status === 401) {
          setUsuario(null); // el token no sirve: api() ya lo borró y avisó
        } else {
          setErrorConexion(e.message); // red caída o servidor despertando: el token sigue
        }
      })
      .finally(() => setCargando(false));
  }, []);

  useEffect(() => { recuperar(); }, [recuperar]);

  // si el servidor dice que la sesión venció, sacamos al usuario y le avisamos por qué
  useEffect(() => {
    // también sirve si venció con la pestaña cerrada: al volver ve el aviso en el login
    const alVencer = (e) => {
      setAvisoSesion(motivoSalida(e.detail));
      setUsuario(null);
    };
    window.addEventListener("sesion-vencida", alVencer);
    return () => window.removeEventListener("sesion-vencida", alVencer);
  }, []);

  async function entrar(email, password) {
    const datos = await api("/api/auth/login", { metodo: "POST", cuerpo: { email, password } });
    guardarToken(datos.token);
    setAvisoSesion("");
    setErrorConexion("");
    setUsuario(datos.usuario);
  }

  function salir() {
    borrarToken();
    setAvisoSesion("");
    setUsuario(null);
  }

  return (
    <Contexto.Provider value={{ usuario, cargando, entrar, salir, avisoSesion, errorConexion, reintentar: recuperar }}>
      {children}
    </Contexto.Provider>
  );
}
