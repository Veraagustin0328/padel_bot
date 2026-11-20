// "Ver como profe": el dueño elige un profe y ve su Mis clases tal cual, solo lectura.
// Mientras está abierta, api.js manda X-Ver-Como en cada pedido y el back rechaza cualquier escritura.
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, verComo } from "../api.js";
import MisClases from "./MisClases.jsx";
import "./misclases.css";

export default function VerComo() {
  const [params, setParams] = useSearchParams();
  const id = Number(params.get("profe")) || null;
  const [profes, setProfes] = useState(null);
  const [error, setError] = useState("");
  // recién con el header puesto se dibuja Mis clases (sus efectos corren antes que los de acá)
  const [activo, setActivo] = useState(null);

  useEffect(() => {
    api("/api/mis-clases/profes").then(setProfes).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (!id) return;
    verComo(id);
    setActivo(id);
    return () => {
      verComo(null);
      setActivo(null);
    };
  }, [id]);

  const elegido = profes?.find((p) => p.id === id);
  const salir = () => setParams({});

  if (id && activo === id && elegido) {
    return (
      <>
        <div className="vc-cartel" role="status">
          <span>Viendo como <b>{elegido.nombre}</b> · solo lectura</span>
          <button className="boton chico" onClick={salir}>Salir</button>
        </div>
        <MisClases key={id} verComo={elegido} />
      </>
    );
  }

  return (
    <div className="vc">
      <h1>Ver como profe</h1>
      <p className="sub">Elegí un profe para ver su pantalla de Mis clases tal cual la ve. Es solo para mirar: no se puede marcar nada.</p>
      {error && <div className="msg-error">{error}</div>}
      {!profes && !error && <div className="nota">Cargando…</div>}
      {profes && id && !elegido && <div className="msg-error">No encontré ese profe entre los activos.</div>}
      {profes && (
        <label className="vc-elegir">
          <span>Profe</span>
          <select value="" onChange={(e) => e.target.value && setParams({ profe: e.target.value })}>
            <option value="">Elegí un profe…</option>
            {profes.map((p) => <option key={p.id} value={p.id}>{p.nombre}</option>)}
          </select>
        </label>
      )}
    </div>
  );
}
