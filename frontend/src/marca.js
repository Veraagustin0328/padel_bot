// Lo que cambia de una academia a otra. Para un cliente nuevo se toca esto
// (el nombre también se puede poner con VITE_NOMBRE_ACADEMIA en el .env de ese cliente).
export const MARCA = {
  nombre: import.meta.env.VITE_NOMBRE_ACADEMIA || "Academia Arena Pádel",
  // Para cambiar la paleta, poné acá solo lo que quieras pisar. Ejemplo:
  // colores: { verde: "#1e3a8a", "verde-2": "#2f55b8", pelota: "#fbbf24" }
  // Los nombres son los de las variables de styles.css, sin los dos guiones.
  colores: {},
  // días sin clases, que no aparecen en Mis clases (0 = lunes ... 6 = domingo)
  diasSinClases: [6],
  // para saber qué día es "hoy" en la academia; tiene que coincidir con ZONA_HORARIA del backend
  zonaHoraria: import.meta.env.VITE_ZONA_HORARIA || "America/Argentina/Buenos_Aires",
};

// se aplican apenas carga la página
for (const [nombre, valor] of Object.entries(MARCA.colores)) {
  document.documentElement.style.setProperty("--" + nombre, valor);
}