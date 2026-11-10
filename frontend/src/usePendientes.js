import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api.js";

const CADA = 150000; // las lentas (planilla) se piden como mucho cada 2 minutos y medio
const AL_ENTRAR = 30000; // al entrar a Pendientes se repiden si pasaron más de 30 s

// cuenta lo pendiente de cada solapa (solo las que ve el rol) y el total para el menú
export function usePendientes(solapas, pathname) {
  const [cuentas, setCuentas] = useState({});
  const ultimo = useRef({}); // cuándo se pidió cada una por última vez

  const anotar = useCallback((clave, n) => {
    ultimo.current[clave] = Date.now();
    setCuentas((c) => (c[clave] === n ? c : { ...c, [clave]: n }));
  }, []);

  const pedir = useCallback(
    (s) => {
      ultimo.current[s.clave] = Date.now();
      api(s.contar.url).then((d) => anotar(s.clave, s.contar.leer(d))).catch(() => {});
    },
    [anotar]
  );

  // cuando una página avisa que cambió algo: si manda el número lo uso, si no lo vuelvo a pedir
  useEffect(() => {
    const bajas = solapas.map((s) => {
      const alAvisar = (e) => (typeof e.detail === "number" ? anotar(s.clave, e.detail) : pedir(s));
      window.addEventListener(s.contar.evento, alAvisar);
      return () => window.removeEventListener(s.contar.evento, alAvisar);
    });
    return () => bajas.forEach((b) => b());
  }, [solapas, anotar, pedir]);

  // las rápidas (base de datos) se refrescan en cada cambio de página, como antes
  useEffect(() => {
    solapas.filter((s) => !s.contar.lento).forEach(pedir);
  }, [solapas, pathname, pedir]);

  // las lentas: al cargar, al entrar a Pendientes y cada tanto (con la pestaña a la vista)
  const enPendientes = pathname === "/pendientes" || pathname.startsWith("/pendientes/");
  const activa = enPendientes ? pathname.split("/")[2] || solapas[0]?.clave : null;
  useEffect(() => {
    const lentas = solapas.filter((s) => s.contar.lento);
    const tocar = (lista, espera) =>
      lista.forEach((s) => {
        if (Date.now() - (ultimo.current[s.clave] || 0) >= espera) pedir(s);
      });
    // si la solapa abierta es la lenta, la página ya la carga y avisa el número: no la leo dos veces
    if (enPendientes) tocar(lentas.filter((s) => s.clave !== activa), AL_ENTRAR);
    else tocar(lentas, CADA);
    const id = setInterval(() => !document.hidden && tocar(lentas, CADA), CADA);
    return () => clearInterval(id);
  }, [solapas, enPendientes, activa, pedir]);

  const total = solapas.reduce((suma, s) => suma + (cuentas[s.clave] || 0), 0);
  return { ...cuentas, total };
}
