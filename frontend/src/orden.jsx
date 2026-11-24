// orden alfabético de nombres: sin mayúsculas ni tildes, los vacíos al final
const sinTildes = (s) => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();
const col = new Intl.Collator("es", { sensitivity: "base", numeric: true });

// sentido: 1 = A–Z, -1 = Z–A. Los vacíos quedan al final en los dos sentidos.
export function compararNombre(a, b, sentido = 1) {
  const x = sinTildes(a), y = sinTildes(b);
  if (!x || !y) return x === y ? 0 : x ? -1 : 1;
  return sentido * col.compare(x, y);
}

// copia ordenada por a.nombre (no toca la lista original)
export const ordenarPorNombre = (lista, sentido = 1) =>
  [...(lista || [])].sort((a, b) => compararNombre(a.nombre, b.nombre, sentido));

// título de columna "Nombre" que alterna A–Z / Z–A, con flechita
export function ThNombre({ sentido, alCambiar, children = "Nombre" }) {
  const az = sentido === 1;
  return (
    <th className="nombre" aria-sort={az ? "ascending" : "descending"}>
      <button type="button" className="th-orden" onClick={() => alCambiar(-sentido)}
              title={az ? "Ordenado A–Z. Tocá para Z–A" : "Ordenado Z–A. Tocá para A–Z"}>
        {children} <span className="th-flecha" aria-hidden="true">{az ? "▲" : "▼"}</span>
      </button>
    </th>
  );
}
