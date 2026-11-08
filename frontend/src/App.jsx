import { useEffect, useState } from "react";
import { BrowserRouter, Routes, Route, Navigate, NavLink, Outlet, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth.jsx";
import { api } from "./api.js";
import { MARCA } from "./marca.js";
import Logo from "./Logo.jsx";
import Login from "./pages/Login.jsx";
import Registro from "./pages/Registro.jsx";
import Solicitudes from "./pages/Solicitudes.jsx";
import Inicio from "./pages/Inicio.jsx";
import Planes from "./pages/Planes.jsx";
import Comprobantes from "./pages/Comprobantes.jsx";
import Alumnos from "./pages/Alumnos.jsx";
import Clases from "./pages/Clases.jsx";
import Cuotas from "./pages/Cuotas.jsx";
import MisClases from "./pages/MisClases.jsx";
import Novedades from "./pages/Novedades.jsx";

const GESTION = ["admin", "encargado"];

// lo que ya está hecho. El profe ve solo Mis clases (el backend igual le da 403 en lo demás)
const MENU = [
  { a: "/", t: "Inicio", roles: ["admin", "encargado", "jugador", "tutor"] },
  { a: "/mis-clases", t: "Mis clases", roles: ["admin", "encargado", "profe"] },
  { a: "/alumnos", t: "Alumnos", roles: GESTION },
  { a: "/clases", t: "Clases", roles: GESTION },
  { a: "/cuotas", t: "Cuotas", roles: GESTION },
  { a: "/comprobantes", t: "Comprobantes", roles: GESTION },
  { a: "/planes", t: "Planes y precios", roles: GESTION },
  { a: "/novedades", t: "Novedades", roles: GESTION },
  { a: "/solicitudes", t: "Solicitudes", roles: ["admin"] },
];
// lo que viene (se ve apagado para que Gabi sepa que está en camino)
const PRONTO = ["Profes y horas", "Planificación", "Agente"];

function Layout() {
  const { usuario, salir } = useAuth();
  const esGestion = GESTION.includes(usuario.rol);
  const [abierto, setAbierto] = useState(false);
  const { pathname } = useLocation();

  // cuántas solicitudes de acceso hay sin resolver (solo le importa al admin)
  const [pendientes, setPendientes] = useState(0);
  useEffect(() => {
    if (usuario.rol !== "admin") return;
    const contar = () => api("/api/solicitudes").then((l) => setPendientes(l.length)).catch(() => {});
    contar();
    window.addEventListener("solicitudes-cambiaron", contar);
    return () => window.removeEventListener("solicitudes-cambiaron", contar);
  }, [usuario.rol, pathname]);

  // al cambiar de página el cajón se cierra solo
  useEffect(() => setAbierto(false), [pathname]);

  // con el cajón abierto: Escape lo cierra y el fondo no scrollea
  useEffect(() => {
    if (!abierto) return;
    const alTeclear = (e) => e.key === "Escape" && setAbierto(false);
    window.addEventListener("keydown", alTeclear);
    document.body.classList.add("sin-scroll");
    return () => {
      window.removeEventListener("keydown", alTeclear);
      document.body.classList.remove("sin-scroll");
    };
  }, [abierto]);

  return (
    <div className="app">
      <nav id="menu" className={"lateral" + (abierto ? " abierto" : "")} aria-label="Principal">
        <div className="marca">
          <span className="logo"><Logo tam={34} /></span>
          {MARCA.nombre}
        </div>
        {MENU.filter((m) => m.roles.includes(usuario.rol)).map((m) => (
          <NavLink key={m.a} to={m.a} end={m.a === "/"} className={({ isActive }) => "item" + (isActive ? " activo" : "")}>
            {m.t}
            {m.a === "/solicitudes" && pendientes > 0 && (
              <span className="contador" aria-label={`${pendientes} pendientes`}>{pendientes}</span>
            )}
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

      {/* solo en el celu: fondo oscuro detrás del cajón y botón flotante abajo, a mano del pulgar */}
      {abierto && <div className="velo" onClick={() => setAbierto(false)} aria-hidden="true" />}
      <button
        className="hamburguesa"
        onClick={() => setAbierto(!abierto)}
        aria-expanded={abierto}
        aria-controls="menu"
        aria-label={abierto ? "Cerrar menú" : "Abrir menú"}
      >
        {abierto ? "✕" : "☰"}
      </button>

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

// el profe arranca directo en Mis clases
function PaginaInicial() {
  const { usuario } = useAuth();
  if (usuario.rol === "profe") return <Navigate to="/mis-clases" replace />;
  return <Inicio />;
}

function SoloGestion({ children }) {
  const { usuario } = useAuth();
  if (!GESTION.includes(usuario.rol)) return <p>No tenés permiso para ver esta sección.</p>;
  return children;
}

function SoloRoles({ roles, children }) {
  const { usuario } = useAuth();
  if (!roles.includes(usuario.rol)) return <p>No tenés permiso para ver esta sección.</p>;
  return children;
}

export default function App() {
  // el título de la pestaña sale de la marca
  useEffect(() => {
    document.title = MARCA.nombre;
  }, []);

  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/registro" element={<Registro />} />
          <Route element={<Protegida />}>
            <Route path="/" element={<PaginaInicial />} />
            <Route path="/mis-clases" element={<SoloRoles roles={["admin", "encargado", "profe"]}><MisClases /></SoloRoles>} />
            <Route path="/alumnos" element={<SoloGestion><Alumnos /></SoloGestion>} />
            <Route path="/clases" element={<SoloGestion><Clases /></SoloGestion>} />
            <Route path="/cuotas" element={<SoloGestion><Cuotas /></SoloGestion>} />
            <Route path="/comprobantes" element={<SoloGestion><Comprobantes /></SoloGestion>} />
            <Route path="/planes" element={<SoloGestion><Planes /></SoloGestion>} />
            <Route path="/novedades" element={<SoloGestion><Novedades /></SoloGestion>} />
            <Route path="/solicitudes" element={<SoloRoles roles={["admin"]}><Solicitudes /></SoloRoles>} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
