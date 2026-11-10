import { useEffect, useMemo, useState } from "react";
import { BrowserRouter, Routes, Route, Navigate, NavLink, Outlet, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth.jsx";
import { MARCA } from "./marca.js";
import Logo from "./Logo.jsx";
import Login from "./pages/Login.jsx";
import Registro from "./pages/Registro.jsx";
import Inicio from "./pages/Inicio.jsx";
import Pendientes from "./pages/Pendientes.jsx";
import CambiarPassword from "./pages/CambiarPassword.jsx";
import { GESTION, nombreRol } from "./roles.js";
import { PANTALLAS, SOLAPAS_PENDIENTES, menuDe } from "./menu.js";
import { usePendientes } from "./usePendientes.js";

// el menú, las rutas y los contadores salen de menu.js. Acá solo se dibujan

function Layout() {
  const { usuario, salir } = useAuth();
  const [abierto, setAbierto] = useState(false);
  const { pathname } = useLocation();

  const grupos = useMemo(() => menuDe(usuario.rol), [usuario.rol]);
  const solapas = useMemo(() => SOLAPAS_PENDIENTES.filter((s) => s.roles.includes(usuario.rol)), [usuario.rol]);
  const cuentas = usePendientes(solapas, pathname);
  const contadores = { pendientes: cuentas.total };

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
        {grupos.map((g, i) => (
          <div key={g.t || i} className="grupo">
            {/* con un solo grupo (el profe) el título no suma nada */}
            {g.t && grupos.length > 1 && <div className="grupo-titulo">{g.t}</div>}
            {g.items.map((m) =>
              m.pronto ? (
                <span key={m.t} className="item apagado">
                  {m.t}
                  <small>pronto</small>
                </span>
              ) : (
                <NavLink key={m.a} to={m.a} end={m.a === "/"} className={({ isActive }) => "item" + (isActive ? " activo" : "")}>
                  {m.t}
                  {contadores[m.contador] > 0 && (
                    <span className="contador" aria-label={`${contadores[m.contador]} pendientes`}>{contadores[m.contador]}</span>
                  )}
                </NavLink>
              )
            )}
          </div>
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
        aria-label={(abierto ? "Cerrar menú" : "Abrir menú") + (cuentas.total > 0 ? `, ${cuentas.total} pendientes` : "")}
      >
        {abierto ? "✕" : "☰"}
        {/* con el cajón cerrado, si no lo muestro acá en el celu no se ve nunca */}
        {!abierto && cuentas.total > 0 && <span className="contador" aria-hidden="true">{cuentas.total}</span>}
      </button>

      <main className="contenido">
        <Outlet context={cuentas} />
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
            <Route
              path="/pendientes/:solapa?"
              element={<SoloRoles roles={GESTION}><Pendientes solapas={SOLAPAS_PENDIENTES} /></SoloRoles>}
            />
            {PANTALLAS.map(({ a, roles, pagina: Pagina }) => (
              <Route key={a} path={a} element={<SoloRoles roles={roles}><Pagina /></SoloRoles>} />
            ))}
            {/* rutas de antes: van a su solapa de Pendientes */}
            {SOLAPAS_PENDIENTES.map((s) => (
              <Route key={s.viejo} path={s.viejo} element={<Navigate to={`/pendientes/${s.clave}`} replace />} />
            ))}
            <Route path="/cambiar-password" element={<CambiarPassword />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
