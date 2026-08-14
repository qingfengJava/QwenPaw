import React from "react";
import ReactDOM from "react-dom/client";
import { ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import "@fontsource-variable/inter";
import "@fortawesome/fontawesome-free/css/all.min.css";
import App from "./App";
import "./styles/global.css";

// antd ConfigProvider is transitional — removed once every page is ported
// off antd (plan stage 5).
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ConfigProvider locale={zhCN}>
      <App />
    </ConfigProvider>
  </React.StrictMode>,
);
