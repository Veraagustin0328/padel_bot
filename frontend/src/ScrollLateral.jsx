import { useEffect, useRef, useState } from "react";

// tabla ancha que scrollea de costado: en el celu avisa que hay más (sombra en el borde + "Deslizá")
// className va al div que scrollea, así cada pantalla conserva su estilo de siempre
export default function ScrollLateral({ className = "", children }) {
  const ref = useRef(null);
  const [lados, setLados] = useState({ ancha: false, izq: false, der: false });

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const medir = () => {
      const ancha = el.scrollWidth > el.clientWidth + 2;
      const izq = el.scrollLeft > 2;
      const der = el.scrollLeft + el.clientWidth < el.scrollWidth - 2;
      setLados((v) => (v.ancha === ancha && v.izq === izq && v.der === der ? v : { ancha, izq, der }));
    };
    medir();
    el.addEventListener("scroll", medir, { passive: true });
    // cuando llegan los datos la tabla cambia de ancho: se vuelve a medir
    const ro = new ResizeObserver(medir);
    ro.observe(el);
    if (el.firstElementChild) ro.observe(el.firstElementChild);
    return () => {
      el.removeEventListener("scroll", medir);
      ro.disconnect();
    };
  }, []);

  return (
    <div className={"scroll-lateral" + (lados.izq ? " hay-izq" : "") + (lados.der ? " hay-der" : "")}>
      {/* el renglón queda siempre que la tabla sea ancha: si se sacara al llegar al final, la tabla saltaría */}
      {lados.ancha && (
        <div className={"scroll-pista" + (lados.der ? "" : " fin")} aria-hidden="true">Deslizá para ver más →</div>
      )}
      <div ref={ref} className={className}>{children}</div>
    </div>
  );
}
