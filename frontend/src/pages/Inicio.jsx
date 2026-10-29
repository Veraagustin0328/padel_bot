import { useAuth } from "../auth.jsx";

export default function Inicio() {
  const { usuario } = useAuth();
  return (
    <>
      <div className="cabecera">
        <div>
          <h1>Hola, {usuario.nombre.split(" ")[0]}</h1>
          <div className="sub">Bienvenido al panel de Academia Arena Pádel</div>
        </div>
      </div>
      <section className="tarjeta">
        <h2>Lo que ya funciona</h2>
        <p className="nota">Planes y precios, con historial y aumento por porcentaje. El resto de las secciones se va sumando.</p>
      </section>
    </>
  );
}