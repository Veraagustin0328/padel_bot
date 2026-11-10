// roles del panel. En el código el encargado sigue siendo "encargado", pero se muestra como "Admin"
export const DUENO = "dueno";
export const GESTION = [DUENO, "encargado"];

export const NOMBRE_ROL = {
  dueno: "Dueño",
  encargado: "Admin",
  profe: "Profe",
  jugador: "Jugador",
  tutor: "Tutor",
};

export const nombreRol = (rol) => NOMBRE_ROL[rol] || rol;
export const esDueno = (usuario) => usuario?.rol === DUENO;
