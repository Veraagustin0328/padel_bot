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
import FaltasRecuperaciones from "./pages/FaltasRecuperaciones.jsx";
import CambiosDias from "./pages/CambiosDias.jsx";
import CambiarPassword from "./pages/CambiarPassword.jsx";
import Usuarios from "./pages/Usuarios.jsx";
import Notas from "./pages/Notas.jsx";
import { DUENO, GESTION, nombreRol } from "./roles.js";

// lo que ya está hecho. El profe ve solo Mis clases (el backend igual le da 403 en lo demás)
// la plata (ganancias, estadísticas, pagos a profes, tarifas por hora) va solo con roles: [DUENO]
const MENU = [
  { a: "/", t: "Inicio", roles: [...GESTION, "jugador", "tutor"] },
  { a: "/mis-clases", t: "Mis clases", roles: [...GESTION, "profe"] },
  { a: "/alumnos", t: "Alumnos", roles: GESTION },
  { a: "/clases", t: "Clases", roles: GESTION },
  { a: "/faltas", t: "Faltas y recuperaciones", roles: GESTION },
  { a: "/cambios-dias", t: "Cambios de días", roles: GESTION },
  { a: "/cuotas", t: "Cuotas", roles: GESTION },
  { a: "/comprobantes", t: "Comprobantes", roles: GESTION },
  { a: "/planes", t: "Planes y precios", roles: GESTION },
  { a: "/novedades", t: "Novedades", roles: GESTION },
  { a: "/notas", t: "Notas", roles: GESTION },
  { a: "/solicitudes", t: "Solicitudes", roles: GESTION },
  { a: "/usuarios", t: "Usuarios", roles: GESTION },
];
// lo que viene (se ve apagado para que sepan que está en camino). Profes y horas es plata: solo dueño
const PRONTO = [
  { t: "Profes y horas", roles: [DUENO] },
  { t: "Planificación", roles: GESTION },
  { t: "Agente", roles: GESTION },
];

function Layout() {
  const { usuario, salir } = useAuth();
  const esGestion = GESTION.includes(usuario.rol);
  const [abierto, setAbierto] = useState(false);
  const { pathname } = useLocation();

  // cuántas solicitudes de acceso hay sin resolver (dueño y encargado)
  const [pendientes, setPendientes] = useState(0);
  useEffect(() => {
    if (!esGestion) return;
    const contar = () => api("/api/solicitudes").then((l) => setPendientes(l.length)).catch(() => {});
    contar();
    window.addEventListener("solicitudes-cambiaron", contar);
    return () => window.removeEventListener("solicitudes-cambiaron", contar);
  }, [esGestion, pathname]);

  // recuperaciones y viajes que esperan que el encargado los apruebe (muchos los pide el agente)
  const [faltasPend, setFaltasPend] = useState(0);
  useEffect(() => {
    if (!esGestion) return;
    const contar = () => api("/api/recuperaciones/pendientes").then((d) => setFaltasPend(d.total)).catch(() => {});
    contar();
    window.addEventListener("faltas-cambiaron", contar);
    return () => window.removeEventListener("faltas-cambiaron", contar);
  }, [esGestion, pathname]);
  // cambios de días que pidieron los alumnos y esperan que el encargado los apruebe
  const [cambiosPend, setCambiosPend] = useState(0);
  useEffect(() => {
    if (!esGestion) return;
    const contar = () => api("/api/cambios-dias").then((d) => setCambiosPend(d.total)).catch(() => {});
    contar();
    window.addEventListener("cambios-cambiaron", contar);
    return () => window.removeEventListener("cambios-cambiaron", contar);
  }, [esGestion, pathname]);
  const contadores = { "/solicitudes": pendientes, "/faltas": faltasPend, "/cambios-dias": cambiosPend };

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
            {contadores[m.a] > 0 && (
              <span className="contador" aria-label={`${contadores[m.a]} pendientes`}>{contadores[m.a]}</span>
            )}
          </NavLink>
        ))}
        {PRONTO.filter((p) => p.roles.includes(usuario.rol)).map(({ t }) => (
            <span key={t} className="item apagado">
              {t}
              <small>pronto</small>
            </span>
          ))}
        <div className="usuario">
          <div className="usuario-nombre">{usuario.nombre}</div>
          <div className="usuario-rol">{nombreRol(usuario.rol)}</div>
          <div className="botones">
            {/* es un link: al navegar el cajón del celu se cierra solo */}
            <NavLink to="/cambiar-password" className="boton chico claro">
              Cambiar contraseña
            </NavLink>
            <button className="boton chico claro" onClick={salir}>
              Salir
            </button>
          </div>
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
            <Route path="/mis-clases" element={<SoloRoles roles={[...GESTION, "profe"]}><MisClases /></SoloRoles>} />
            <Route path="/alumnos" element={<SoloGestion><Alumnos /></SoloGestion>} />
            <Route path="/clases" element={<SoloGestion><Clases /></SoloGestion>} />
            <Route path="/faltas" element={<SoloGestion><FaltasRecuperaciones /></SoloGestion>} />
            <Route path="/cambios-dias" element={<SoloGestion><CambiosDias /></SoloGestion>} />
            <Route path="/cuotas" element={<SoloGestion><Cuotas /></SoloGestion>} />
            <Route path="/comprobantes" element={<SoloGestion><Comprobantes /></SoloGestion>} />
            <Route path="/planes" element={<SoloGestion><Planes /></SoloGestion>} />
            <Route path="/novedades" element={<SoloGestion><Novedades /></SoloGestion>} />
            <Route path="/notas" element={<SoloGestion><Notas /></SoloGestion>} />
            <Route path="/solicitudes" element={<SoloGestion><Solicitudes /></SoloGestion>} />
            <Route path="/usuarios" element={<SoloGestion><Usuarios /></SoloGestion>} />
            <Route path="/cambiar-password" element={<CambiarPassword />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
