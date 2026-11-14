// Todo lo que sale hacia el backend pasa por acá.
// En desarrollo apunta a localhost:5000 (ver .env.development).
const BASE = import.meta.env.VITE_API_URL || "";
const CLAVE = "arena_token";

export const guardarToken = (t) => localStorage.setItem(CLAVE, t);
export const leerToken = () => localStorage.getItem(CLAVE);
export const borrarToken = () => localStorage.removeItem(CLAVE);

// el error lleva .red (no llegó al servidor) o .status (el servidor contestó mal),
// así quien lo agarra distingue "sin conexión" de "sesión vencida"
function errorDeRed() {
  const e = new Error("No pude conectar con el servidor");
  e.red = true;
  return e;
}

function errorDeServidor(resp, datos) {
  const e = new Error(datos.error || "Algo salió mal");
  e.status = resp.status;
  return e;
}

function sesionVencida(datos) {
  borrarToken();
  // el motivo viaja en el evento para mostrarlo en el login
  window.dispatchEvent(new CustomEvent("sesion-vencida", { detail: datos.error || "" }));
}

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
    throw errorDeRed();
  }

  const datos = await resp.json().catch(() => ({}));
  if (resp.status === 401 && ruta !== "/api/auth/login") sesionVencida(datos);
  if (!resp.ok) throw errorDeServidor(resp, datos);
  return datos;
}

// para archivos (CSV): misma sesión que api(), pero baja el archivo en vez de leer JSON
export async function descargar(ruta, nombre) {
  const token = leerToken();
  let resp;
  try {
    resp = await fetch(BASE + ruta, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  } catch {
    throw errorDeRed();
  }
  if (!resp.ok) {
    const datos = await resp.json().catch(() => ({}));
    if (resp.status === 401) sesionVencida(datos);
    throw errorDeServidor(resp, datos);
  }
  const url = URL.createObjectURL(await resp.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = nombre;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
