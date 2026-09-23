import React from "react";
import ReactDOM from "react-dom/client";
import "@fontsource-variable/inter";
import "@fortawesome/fontawesome-free/css/all.min.css";
import App from "./App";
import { ToastProvider } from "./components/Toast";
import "./styles/global.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ToastProvider>
      <App />
    </ToastProvider>
  </React.StrictMode>,
);
