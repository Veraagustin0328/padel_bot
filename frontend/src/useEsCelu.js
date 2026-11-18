import { useEffect, useState } from "react";

// mismo corte que el CSS: hasta 820px es celu (menú en cajón, hoja inferior, etc.)
export const CORTE_CELU = "(max-width: 820px)";

export function useEsCelu() {
  const [celu, setCelu] = useState(() => window.matchMedia(CORTE_CELU).matches);
  useEffect(() => {
    const mq = window.matchMedia(CORTE_CELU);
    const alCambiar = () => setCelu(mq.matches);
    mq.addEventListener("change", alCambiar);
    return () => mq.removeEventListener("change", alCambiar);
  }, []);
  return celu;
}
