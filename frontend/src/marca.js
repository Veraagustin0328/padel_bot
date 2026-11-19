// Lo que cambia de una academia a otra. Para un cliente nuevo se toca esto
// (el nombre también se puede poner con VITE_NOMBRE_ACADEMIA en el .env de ese cliente).
export const MARCA = {
  nombre: import.meta.env.VITE_NOMBRE_ACADEMIA || "Academia Arena Pádel",
  // Para cambiar la paleta, poné acá solo lo que quieras pisar. Ejemplo:
  // colores: { verde: "#1e3a8a", "verde-2": "#2f55b8", pelota: "#fbbf24" }
  // Los nombres son los de las variables de styles.css, sin los dos guiones.
  // Las pantallas del alumno/padre usan además alu-fondo, alu-tarjeta, alu-lateral, alu-tinta y alu-suave.
  colores: {},
  // Títulos de las pantallas del alumno/padre: condensada gruesa en mayúsculas.
  // Anton es libre y se parece a la del flyer; para poner la licenciada del club, cambiá
  // familia (y url, o vacía si la fuente ya se carga por otro lado).
  fuenteTitulos: {
    familia: import.meta.env.VITE_FUENTE_TITULOS || "Anton",
    url: import.meta.env.VITE_FUENTE_TITULOS_URL ?? "https://fonts.googleapis.com/css2?family=Anton&display=swap",
  },
  // días sin clases, que no aparecen en Mis clases (0 = lunes ... 6 = domingo)
  diasSinClases: [6],
  // para saber qué día es "hoy" en la academia; tiene que coincidir con ZONA_HORARIA del backend
  zonaHoraria: import.meta.env.VITE_ZONA_HORARIA || "America/Argentina/Buenos_Aires",
};

// se aplican apenas carga la página
for (const [nombre, valor] of Object.entries(MARCA.colores)) {
  document.documentElement.style.setProperty("--" + nombre, valor);
}

// la fuente de títulos se baja solo cuando entra alguien a las pantallas del alumno
let fuenteCargada = false;
export function cargarFuenteTitulos() {
  if (fuenteCargada) return;
  fuenteCargada = true;
  const { familia, url } = MARCA.fuenteTitulos;
  // si no carga, quedan las de respaldo de --fuente-titulos (styles.css)
  document.documentElement.style.setProperty(
    "--fuente-titulos", `"${familia}", "Bebas Neue", "Oswald", Impact, "Arial Narrow", sans-serif`);
  if (url) {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = url;
    document.head.appendChild(link);
  }
}
