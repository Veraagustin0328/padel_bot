// Fechas como texto AAAA-MM-DD, con la cuenta en UTC para que no joda el horario de verano.
// Sin imports a propósito: así se puede probar con node pelado.

const aFecha = (s) => {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d));
};

export const sumarDias = (s, n) => {
  const d = aFecha(s);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
};

export const diaSemana = (s) => (aFecha(s).getUTCDay() + 6) % 7; // 0 = lunes, como en el backend
export const numeroDia = (s) => aFecha(s).getUTCDate();
export const mesDe = (s) => aFecha(s).getUTCMonth(); // 0 = enero
export const lunesDe = (s) => sumarDias(s, -diaSemana(s));

// qué día es hoy en la academia, no en el navegador del que mira
export function hoyEn(zona, ahora = new Date()) {
  const partes = Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", { timeZone: zona, year: "numeric", month: "2-digit", day: "2-digit" })
      .formatToParts(ahora)
      .map((p) => [p.type, p.value]),
  );
  return `${partes.year}-${partes.month}-${partes.day}`;
}

// si hoy no hay clases (ej: domingo), el último día que sí hubo
export function ultimoDiaConClases(fecha, sinClases) {
  let f = fecha;
  for (let i = 0; i < 7 && sinClases.includes(diaSemana(f)); i++) f = sumarDias(f, -1);
  return f;
}

// los días con clases de la semana que arranca ese lunes, en orden
export const diasDeSemana = (lunes, sinClases) =>
  Array.from({ length: 7 }, (_, i) => sumarDias(lunes, i)).filter((f) => !sinClases.includes(diaSemana(f)));
