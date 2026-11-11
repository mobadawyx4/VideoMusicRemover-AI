import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const devHost = process.env.VITE_DEV_HOST || "localhost";
const devPort = Number(process.env.VITE_DEV_PORT || 5173);

export default defineConfig({
  plugins: [react()],
  server: {
    host: devHost,
    port: devPort,
    strictPort: true,
    proxy: {
      "/api": {
        target: process.env.VITE_BACKEND_ORIGIN || "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  preview: {
    host: devHost,
    port: 4173,
    proxy: {
      "/api": {
        target: process.env.VITE_BACKEND_ORIGIN || "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
