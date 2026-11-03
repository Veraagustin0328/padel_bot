// Logo de la academia: la "A" con la pelota. Hereda el color del texto (currentColor).
// Uso: <Logo tam={34} />  o  <Logo tam={90} pelota="#3667b8" />
export default function Logo({ tam = 34, pelota }) {
  return (
    <svg
      viewBox="170 60 570 510"
      width={tam}
      height={(tam * 510) / 570}
      aria-label="Logo"
      role="img"
      style={{ color: "inherit", flex: "none" }}
    >
      <g fill="currentColor">
        <polygon points="178,552 440,82 512,82 590,252 420,357 420,335 500,268 458,177 322,452 236,552" />
        <polygon points="250,552 704,207 704,255 305,552" />
        <polygon points="272,552 560,412 622,325 727,552 624,552 560,432 310,552" />
      </g>
      <circle cx="647" cy="124" r="52" fill={pelota || "currentColor"} />
    </svg>
  );
}