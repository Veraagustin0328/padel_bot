import { Navigate, NavLink, useOutletContext, useParams } from "react-router-dom";
import { useAuth } from "../auth.jsx";
import "./pendientes.css";

// todo lo que espera que alguien lo resuelva, en solapas. No tiene título propio:
// cada solapa es la pantalla de siempre, con su h1
export default function Pendientes({ solapas }) {
  const { usuario } = useAuth();
  const cuentas = useOutletContext() || {};
  const { solapa } = useParams();

  const visibles = solapas.filter((s) => s.roles.includes(usuario.rol));
  if (!visibles.length) return <p>No tenés permiso para ver esta sección.</p>;
  const activa = visibles.find((s) => s.clave === solapa);
  // sin solapa o con una que no existe: a la primera
  if (!activa) return <Navigate to={`/pendientes/${visibles[0].clave}`} replace />;
  const Pagina = activa.pagina;

  return (
    <>
      <nav className="pend-solapas" aria-label="Pendientes">
        {visibles.map((s) => (
          <NavLink key={s.clave} to={`/pendientes/${s.clave}`} className={({ isActive }) => "pend-solapa" + (isActive ? " activo" : "")}>
            {s.t}
            {cuentas[s.clave] > 0 && (
              <span className="contador" aria-label={`${cuentas[s.clave]} pendientes`}>{cuentas[s.clave]}</span>
            )}
          </NavLink>
        ))}
      </nav>
      {/* key: al cambiar de solapa la pantalla arranca de cero, como cuando era otra ruta */}
      <Pagina key={activa.clave} />
    </>
  );
}
