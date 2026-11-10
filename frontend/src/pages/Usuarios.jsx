import { useEffect, useState } from "react";
import { api } from "../api.js";
import { nombreRol } from "../roles.js";

export default function Usuarios() {
  const [lista, setLista] = useState(null);
  const [error, setError] = useState("");
  const [nueva, setNueva] = useState(null); // { nombre, password }: se muestra una sola vez
  const [ocupado, setOcupado] = useState(null);

  useEffect(() => {
    api("/api/auth/usuarios").then(setLista).catch((e) => { setError(e.message); setLista([]); });
  }, []);

  async function resetear(u) {
    if (!window.confirm(`¿Resetear la contraseña de ${u.nombre}? La actual deja de andar.`)) return;
    setError(""); setNueva(null); setOcupado(u.id);
    try {
      const r = await api(`/api/auth/usuarios/${u.id}/resetear-password`, { metodo: "POST" });
      setNueva({ nombre: u.nombre, password: r.password });
    } catch (e) {
      setError(e.message);
    } finally {
      setOcupado(null);
    }
  }

  return (
    <div>
      <div className="cabecera">
        <h1>Usuarios</h1>
        <p className="sub">Gente con acceso al panel. Desde acá podés resetearle la contraseña a alguien.</p>
      </div>
      {error && <div className="msg-error" role="alert">{error}</div>}
      {nueva && (
        <div className="msg-ok clave-nueva" role="status">
          <div>Contraseña nueva de <strong>{nueva.nombre}</strong>:</div>
          <code>{nueva.password}</code>
          <div className="nota">Pasásela ahora: no se vuelve a mostrar. Después puede cambiarla desde su menú.</div>
          <button className="boton chico claro" onClick={() => setNueva(null)}>Listo, ya la anoté</button>
        </div>
      )}

      {lista === null && <p>Cargando…</p>}
      <div className="solicitudes">
        {(lista || []).map((u) => (
          <div key={u.id} className="tarjeta usuario-fila">
            <div>
              <strong>{u.nombre}</strong>
              <div className="sub">{u.email} · {nombreRol(u.rol)}{!u.activo && " · inactivo"}</div>
            </div>
            {/* el backend dice a quién se puede: el admin no resetea a dueños ni a otros admins */}
            {u.puede_resetear && (
              <button className="boton chico claro" disabled={ocupado === u.id} onClick={() => resetear(u)}>
                Resetear contraseña
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
