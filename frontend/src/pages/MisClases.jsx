import { useEffect, useState } from "react";
import { api } from "../api.js";
import { useAuth } from "../auth.jsx";
import "./misclases.css";

const DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"];
const ESTADOS = [
  ["presente", "Presente"],
  ["ausente", "Ausente"],
  ["ausente_avisa", "Avisó"],
];
const TIPOS = { grupal: "Grupal", particular: "Particular", particular_2: "Particular de 2", otro: "Otra" };

// fecha local en AAAA-MM-DD (no toISOString, que pasa a UTC)
const iso = (d) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const diaSemana = (d) => (d.getDay() + 6) % 7; // 0 = lunes, como en el backend

// hoy primero y después los 6 días anteriores, para marcar lo que quedó colgado
function ultimosDias() {
  const hoy = new Date();
  return Array.from({ length: 7 }, (_, i) => {
    const d = new Date(hoy.getFullYear(), hoy.getMonth(), hoy.getDate() - i);
    const titulo = i === 0 ? "Hoy" : i === 1 ? "Ayer" : DIAS[diaSemana(d)].slice(0, 3);
    return { fecha: iso(d), dia: diaSemana(d), titulo, numero: d.getDate() };
  });
}

function Clase({ clase, fecha, verProfe }) {
  const [abierta, setAbierta] = useState(false);
  const [datos, setDatos] = useState(null);
  const [error, setError] = useState("");
  const [guardando, setGuardando] = useState({});
  const [notaAbierta, setNotaAbierta] = useState({});

  // si cambia el día, se vuelve a cargar
  useEffect(() => {
    setDatos(null);
    setError("");
    if (!abierta) return;
    api(`/api/mis-clases/${clase.id}/asistencia?fecha=${fecha}`)
      .then(setDatos)
      .catch((e) => setError(e.message));
  }, [abierta, fecha, clase.id]);

  function cambiarLocal(alumnoId, cambios) {
    setDatos((d) => ({ ...d, alumnos: d.alumnos.map((a) => (a.id === alumnoId ? { ...a, ...cambios } : a)) }));
  }

  async function guardar(alumno, cambios) {
    const antes = { estado: alumno.estado, nota: alumno.nota };
    const estado = cambios.estado || alumno.estado;
    if (!estado) return; // la nota sola no alcanza: primero hay que marcar
    cambiarLocal(alumno.id, cambios);
    setGuardando((g) => ({ ...g, [alumno.id]: "…" }));
    setError("");
    try {
      const r = await api(`/api/mis-clases/${clase.id}/asistencia`, {
        metodo: "POST",
        cuerpo: { fecha, alumno_id: alumno.id, estado, ...("nota" in cambios ? { nota: cambios.nota } : {}) },
      });
      cambiarLocal(alumno.id, { estado: r.estado, nota: r.nota });
      setGuardando((g) => ({ ...g, [alumno.id]: "✓" }));
    } catch (e) {
      cambiarLocal(alumno.id, antes);
      setGuardando((g) => ({ ...g, [alumno.id]: "" }));
      setError(`${alumno.nombre}: ${e.message}`);
    }
  }

  const presentes = datos ? datos.alumnos.filter((a) => a.estado === "presente").length : 0;
  const marcados = datos ? datos.alumnos.filter((a) => a.estado).length : 0;

  return (
    <div className="mc-clase">
      <button className="mc-cabeza" onClick={() => setAbierta(!abierta)} aria-expanded={abierta}>
        <span className="mc-hora">{clase.hora}</span>
        <span className="mc-info">
          <span className="mc-titulo">
            {TIPOS[clase.tipo] || clase.tipo}
            {clase.nivel && ` · ${clase.nivel}`}
          </span>
          <span className="mc-sub">
            {verProfe && clase.profe ? `${clase.profe} · ` : ""}
            {datos
              ? `${presentes} presentes · ${marcados}/${datos.alumnos.length} marcados`
              : `${clase.alumnos} ${clase.alumnos === 1 ? "alumno" : "alumnos"}`}
          </span>
        </span>
        <span className="mc-flecha">{abierta ? "▲" : "▼"}</span>
      </button>

      {abierta && (
        <div className="mc-cuerpo">
          {error && <div className="msg-error">{error}</div>}
          {!datos && !error && <div className="nota">Cargando…</div>}
          {datos && datos.alumnos.length === 0 && <div className="nota">No hay alumnos anotados ese día.</div>}
          {datos?.alumnos.map((a) => (
            <div key={a.id} className="mc-alumno">
              <div className="mc-nombre">
                <span>{a.nombre}</span>
                {a.recupera && <span className="mc-tag">recupera</span>}
                <span className="mc-guardado">{guardando[a.id]}</span>
              </div>
              <div className="mc-botones">
                {ESTADOS.map(([valor, texto]) => (
                  <button
                    key={valor}
                    className={`mc-estado ${valor}` + (a.estado === valor ? " activo" : "")}
                    aria-pressed={a.estado === valor}
                    onClick={() => a.estado !== valor && guardar(a, { estado: valor })}
                  >
                    {texto}
                  </button>
                ))}
              </div>
              {a.estado &&
                (notaAbierta[a.id] || a.nota ? (
                  <input
                    className="mc-nota"
                    placeholder="Nota (opcional)"
                    defaultValue={a.nota}
                    maxLength={255}
                    onBlur={(e) => e.target.value.trim() !== a.nota && guardar(a, { nota: e.target.value.trim() })}
                  />
                ) : (
                  <button className="mc-agregar-nota" onClick={() => setNotaAbierta((n) => ({ ...n, [a.id]: true }))}>
                    + nota
                  </button>
                ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function MisClases() {
  const { usuario } = useAuth();
  const verTodas = usuario.rol === "admin" || usuario.rol === "encargado";
  const dias = ultimosDias();
  const [elegido, setElegido] = useState(dias[0].fecha);
  const [clases, setClases] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api("/api/mis-clases")
      .then((d) => setClases(d.clases))
      .catch((e) => {
        setError(e.message);
        setClases([]);
      });
  }, []);

  const dia = dias.find((d) => d.fecha === elegido);
  const delDia = (clases || []).filter((c) => c.dia === dia.dia);

  return (
    <div className="mc">
      <div className="cabecera">
        <div>
          <h1>Mis clases</h1>
          <div className="sub">
            {DIAS[dia.dia]} {dia.numero} · tocá un estado y se guarda solo
          </div>
        </div>
      </div>

      <div className="mc-dias" role="tablist">
        {dias.map((d) => (
          <button
            key={d.fecha}
            role="tab"
            aria-selected={d.fecha === elegido}
            className={"mc-dia" + (d.fecha === elegido ? " activo" : "")}
            onClick={() => setElegido(d.fecha)}
          >
            <span>{d.titulo}</span>
            <strong>{d.numero}</strong>
          </button>
        ))}
      </div>

      {error && <div className="msg-error">{error}</div>}
      {clases === null && <div className="nota">Cargando…</div>}
      {clases && !error && delDia.length === 0 && (
        <div className="mc-vacio">{verTodas ? "No hay clases este día." : "No tenés clases este día."}</div>
      )}
      <div className="mc-lista">
        {delDia.map((c) => (
          <Clase key={c.id} clase={c} fecha={elegido} verProfe={verTodas} />
        ))}
      </div>
    </div>
  );
}
