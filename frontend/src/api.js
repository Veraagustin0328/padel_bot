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
  // 429: el servidor dice cuántos segundos esperar
  const espera = parseInt(resp.headers.get("Retry-After") || "", 10);
  if (espera > 0) e.reintentarEn = espera;
  return e;
}

function sesionVencida(datos) {
  borrarToken();
  // el motivo viaja en el evento para mostrarlo en el login
  window.dispatchEvent(new CustomEvent("sesion-vencida", { detail: datos.error || "" }));
}

// Render (plan gratis) duerme el servidor: el primer pedido puede tardar ~1 minuto o volver con 502/503.
// Si un pedido tarda más de LENTO_MS se avisa con el evento "servidor-lento" (lo muestra AvisoServidor).
const LENTO_MS = 3000;
const REINTENTO_MS = 2500;
let lentos = 0;
function avisarLentos(cambio) {
  lentos = Math.max(0, lentos + cambio);
  window.dispatchEvent(new CustomEvent("servidor-lento", { detail: lentos }));
}
const esperar = (ms) => new Promise((r) => setTimeout(r, ms));

// un GET igual a otro que ya está en vuelo no sale de nuevo: espera la misma respuesta
const enVuelo = new Map();

async function pedir(ruta, metodo, cuerpo) {
  const headers = {};
  const token = leerToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (cuerpo !== undefined) headers["Content-Type"] = "application/json";
  // solo los GET se reintentan: un POST repetido podría hacer la acción dos veces
  const intentos = metodo === "GET" ? 2 : 1;
  let marcado = false;
  const reloj = setTimeout(() => { marcado = true; avisarLentos(1); }, LENTO_MS);
  try {
    for (let i = 1; ; i++) {
      let resp;
      try {
        resp = await fetch(BASE + ruta, {
          method: metodo,
          headers,
          body: cuerpo !== undefined ? JSON.stringify(cuerpo) : undefined,
        });
      } catch {
        if (i < intentos) { await esperar(REINTENTO_MS); continue; }
        throw errorDeRed();
      }
      // 502/503/504 = el servidor todavía se está levantando. Un 429 (demasiados intentos) no se reintenta
      if ([502, 503, 504].includes(resp.status) && i < intentos) { await esperar(REINTENTO_MS); continue; }
      const datos = await resp.json().catch(() => ({}));
      if (resp.status === 401 && ruta !== "/api/auth/login") sesionVencida(datos);
      if (!resp.ok) throw errorDeServidor(resp, datos);
      return datos;
    }
  } finally {
    clearTimeout(reloj);
    if (marcado) avisarLentos(-1);
  }
}

export async function api(ruta, { metodo = "GET", cuerpo } = {}) {
  if (metodo !== "GET") return pedir(ruta, metodo, cuerpo);
  const clave = `${leerToken() || ""} ${ruta}`;
  if (enVuelo.has(clave)) {
    // copia: así dos pantallas no comparten el mismo objeto
    return enVuelo.get(clave).then((d) => structuredClone(d));
  }
  const promesa = pedir(ruta, "GET");
  enVuelo.set(clave, promesa);
  try {
    return await promesa;
  } finally {
    enVuelo.delete(clave);
  }
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
