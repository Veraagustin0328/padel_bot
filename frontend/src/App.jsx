import { BrowserRouter, Routes, Route, Navigate, NavLink, Outlet } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth.jsx";
import Login from "./pages/Login.jsx";
import Inicio from "./pages/Inicio.jsx";
import Planes from "./pages/Planes.jsx";
import Comprobantes from "./pages/Comprobantes.jsx";

const GESTION = ["admin", "encargado"];

// lo que ya está hecho
const MENU = [
  { a: "/", t: "Inicio", roles: ["admin", "encargado", "profe", "jugador"] },
  { a: "/planes", t: "Planes y precios", roles: GESTION },
  { a: "/comprobantes", t: "Comprobantes", roles: GESTION },
];
// lo que viene (se ve apagado para que Gabi sepa que está en camino)
const PRONTO = ["Alumnos", "Cuotas", "Profes y horas", "Planificación", "Agente"];

function Layout() {
  const { usuario, salir } = useAuth();
  const esGestion = GESTION.includes(usuario.rol);

  return (
    <div className="app">
      <nav className="lateral" aria-label="Principal">
        <div className="marca">
          <span className="pelota" />
          Academia Arena Pádel
        </div>
        {MENU.filter((m) => m.roles.includes(usuario.rol)).map((m) => (
          <NavLink key={m.a} to={m.a} end={m.a === "/"} className={({ isActive }) => "item" + (isActive ? " activo" : "")}>
            {m.t}
          </NavLink>
        ))}
        {esGestion &&
          PRONTO.map((t) => (
            <span key={t} className="item apagado">
              {t}
              <small>pronto</small>
            </span>
          ))}
        <div className="usuario">
          <div className="usuario-nombre">{usuario.nombre}</div>
          <div className="usuario-rol">{usuario.rol}</div>
          <button className="boton chico claro" onClick={salir}>
            Salir
          </button>
        </div>
      </nav>
      <main className="contenido">
        <Outlet />
      </main>
    </div>
  );
}

function Protegida() {
  const { usuario, cargando } = useAuth();
  if (cargando) return <div className="cargando">Cargando…</div>;
  if (!usuario) return <Navigate to="/login" replace />;
  return <Layout />;
}

function SoloGestion({ children }) {
  const { usuario } = useAuth();
  if (!GESTION.includes(usuario.rol)) return <p>No tenés permiso para ver esta sección.</p>;
  return children;
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route element={<Protegida />}>
            <Route path="/" element={<Inicio />} />
            <Route path="/planes" element={<SoloGestion><Planes /></SoloGestion>} />
            <Route path="/comprobantes" element={<SoloGestion><Comprobantes /></SoloGestion>} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}