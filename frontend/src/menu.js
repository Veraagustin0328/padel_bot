// único lugar donde se arma el menú: de acá salen el cajón, las rutas, las solapas de Pendientes,
// los contadores y las redirecciones de rutas viejas. Para sumar una pantalla, agregá una línea.
import Alumnos from "./pages/Alumnos.jsx";
import Clases from "./pages/Clases.jsx";
import Cuotas from "./pages/Cuotas.jsx";
import MisClases from "./pages/MisClases.jsx";
import Novedades from "./pages/Novedades.jsx";
import FaltasRecuperaciones, { FaltasPendientes } from "./pages/FaltasRecuperaciones.jsx";
import CambiosDias from "./pages/CambiosDias.jsx";
import Comprobantes from "./pages/Comprobantes.jsx";
import Consultas from "./pages/Consultas.jsx";
import Planes from "./pages/Planes.jsx";
import Solicitudes from "./pages/Solicitudes.jsx";
import Usuarios from "./pages/Usuarios.jsx";
import Notas from "./pages/Notas.jsx";
import { DUENO, GESTION } from "./roles.js";

// solapas de la pantalla Pendientes. `contar` dice de dónde sale el número del contador:
// - evento: lo dispara la página cuando cambia algo (si trae un número en detail, se usa directo)
// - lento: pega contra la planilla de Google, se pide poco (al cargar, al entrar a Pendientes y cada tanto)
// - viejo: la ruta de antes, que ahora redirige acá
export const SOLAPAS_PENDIENTES = [
  {
    clave: "comprobantes", t: "Comprobantes", roles: GESTION, pagina: Comprobantes, viejo: "/comprobantes",
    contar: { url: "/api/comprobantes?estado=pendiente", leer: (l) => l.length, evento: "comprobantes-cambiaron", lento: true },
  },
  {
    // sin `viejo`: es nueva, no tiene ruta de antes
    clave: "consultas", t: "Consultas", roles: GESTION, pagina: Consultas,
    contar: { url: "/api/consultas/pendientes", leer: (d) => d.total, evento: "consultas-cambiaron" },
  },
  {
    clave: "cambios-dias", t: "Cambios de días", roles: GESTION, pagina: CambiosDias, viejo: "/cambios-dias",
    contar: { url: "/api/cambios-dias", leer: (d) => d.total, evento: "cambios-cambiaron" },
  },
  {
    clave: "faltas", t: "Faltas y recuperaciones", roles: GESTION, pagina: FaltasPendientes, viejo: "/faltas",
    contar: { url: "/api/recuperaciones/pendientes", leer: (d) => d.total, evento: "faltas-cambiaron" },
  },
  {
    clave: "solicitudes", t: "Solicitudes de acceso", roles: GESTION, pagina: Solicitudes, viejo: "/solicitudes",
    contar: { url: "/api/solicitudes", leer: (l) => l.length, evento: "solicitudes-cambiaron" },
  },
];

// grupos del cajón. Sin título = va suelto arriba. Un grupo sin ítems visibles para el rol no se muestra.
// pagina: la pantalla de la ruta (Inicio y Pendientes las arma App aparte). pronto: se ve apagado.
// la plata fina (ganancias, pagos a profes, tarifas por hora) va solo con roles: [DUENO]
export const MENU = [
  {
    items: [
      { a: "/", t: "Inicio", roles: [...GESTION, "jugador", "tutor"] },
      { a: "/pendientes", t: "Pendientes", roles: GESTION, contador: "pendientes" },
    ],
  },
  {
    t: "Alumnos y clases",
    items: [
      { a: "/clases", t: "Clases", roles: GESTION, pagina: Clases },
      { a: "/alumnos", t: "Alumnos", roles: GESTION, pagina: Alumnos },
      { a: "/mis-clases", t: "Mis clases", roles: [...GESTION, "profe"], pagina: MisClases },
      { a: "/faltas-viajes", t: "Faltas y viajes", roles: GESTION, pagina: FaltasRecuperaciones },
      { t: "Planificación", roles: GESTION, pronto: true },
    ],
  },
  {
    t: "Plata",
    items: [
      { a: "/cuotas", t: "Cuotas", roles: GESTION, pagina: Cuotas },
      { a: "/planes", t: "Planes y precios", roles: GESTION, pagina: Planes },
      { t: "Profes y horas", roles: [DUENO], pronto: true },
    ],
  },
  {
    t: "Comunicación",
    items: [
      { a: "/novedades", t: "Novedades", roles: GESTION, pagina: Novedades },
      { a: "/notas", t: "Notas", roles: GESTION, pagina: Notas },
    ],
  },
  {
    t: "Administración",
    items: [
      { a: "/usuarios", t: "Usuarios", roles: GESTION, pagina: Usuarios },
      { t: "Agente", roles: GESTION, pronto: true },
    ],
  },
];

// el menú que le toca a cada rol: saca lo que no ve y los grupos que quedan vacíos
export function menuDe(rol) {
  return MENU.map((g) => ({ ...g, items: g.items.filter((i) => i.roles.includes(rol)) })).filter((g) => g.items.length);
}

// todas las pantallas con ruta propia, para armar las <Route>
export const PANTALLAS = MENU.flatMap((g) => g.items).filter((i) => i.pagina);
