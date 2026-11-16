// ¿El backend está en simulación? Se pregunta una vez, antes de dibujar el panel.
// En el build de producción no se pregunta nada (salvo VITE_SIMULACION=1, para un Render de prueba):
// la ruta ni existe en el backend real, así que el panel queda igual que siempre.
import { fijarDesfase } from "./fechas.js";

const BASE = import.meta.env.VITE_API_URL || "";
const PREGUNTAR = import.meta.env.DEV || import.meta.env.VITE_SIMULACION === "1";

let estado = { simulacion: false };

export async function cargarEntorno() {
  if (!PREGUNTAR) return estado;
  try {
    const r = await fetch(BASE + "/api/simulacion/estado");
    if (r.ok) {
      estado = await r.json();
      // con el reloj simulado el server está en otra fecha: el panel se acomoda a esa
      const delServer = Date.parse(estado.ahora);
      if (!Number.isNaN(delServer)) fijarDesfase(delServer - Date.now());
    }
  } catch {
    // sin backend o backend real: sin cartel
  }
  return estado;
}

export const entorno = () => estado;
