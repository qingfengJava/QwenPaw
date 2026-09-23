import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// XianWork user frontend. Served by the QwenPaw backend under the
// `/xianwork` sub-path (same origin as the API — natural SSO with the
// console). Local dev proxies `/api` to the backend like the console.
//
// `--mode tauri` builds for desktop packaging: relative asset base +
// HashRouter (see src/App.tsx), mirroring the console/src-tauri flow.
export default defineConfig(({ mode }) => ({
  base: mode === "tauri" ? "./" : "/xianwork/",
  plugins: [react()],
  server: {
    port: 5174,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8088",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    target: "chrome110",
    chunkSizeWarningLimit: 1500,
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ["react", "react-dom", "react-router-dom"],
        },
      },
    },
  },
}));
