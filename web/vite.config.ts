import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dev server proxies /api/* to the FastAPI backend so the UI can use
// relative URLs. Overridable via env:
//   VITE_API_URL  where /api is proxied (default localhost:8000 — the
//                 Docker backend is published there, so `npm run dev`
//                 works against it out of the box).
//   DEV_PORT      local dev-server port. Defaults to 5174 to avoid the
//                 Docker web port (5273) and anything on 5173.
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: Number(process.env.DEV_PORT) || 5174,
    proxy: {
      "/api": {
        target: process.env.VITE_API_URL ?? "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
