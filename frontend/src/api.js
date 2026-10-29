// Todo lo que sale hacia el backend pasa por acá.
// En desarrollo apunta a localhost:5000 (ver .env.development).
const BASE = import.meta.env.VITE_API_URL || "";
const CLAVE = "arena_token";

export const guardarToken = (t) => localStorage.setItem(CLAVE, t);
export const leerToken = () => localStorage.getItem(CLAVE);
export const borrarToken = () => localStorage.removeItem(CLAVE);

export async function api(ruta, { metodo = "GET", cuerpo } = {}) {
  const headers = {};
  const token = leerToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (cuerpo !== undefined) headers["Content-Type"] = "application/json";

  let resp;
  try {
    resp = await fetch(BASE + ruta, {
      method: metodo,
      headers,
      body: cuerpo !== undefined ? JSON.stringify(cuerpo) : undefined,
    });
  } catch {
    throw new Error("No pude conectar con el servidor");
  }

  const datos = await resp.json().catch(() => ({}));
  if (resp.status === 401 && ruta !== "/api/auth/login") {
    borrarToken();
    window.dispatchEvent(new Event("sesion-vencida"));
  }
  if (!resp.ok) throw new Error(datos.error || "Algo salió mal");
  return datos;
}