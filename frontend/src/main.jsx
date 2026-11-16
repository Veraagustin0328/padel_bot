import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import { cargarEntorno } from "./simulacion.js";
import "./styles.css";

// primero se fija si es simulación (en producción vuelve al toque sin preguntar nada)
cargarEntorno().finally(() => {
  createRoot(document.getElementById("root")).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>
  );
});
