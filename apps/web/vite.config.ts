import { fileURLToPath } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv, type ProxyOptions } from "vite";

// The web app and the API share one origin, so the session cookies the API sets are first-party
// and the page never handles tokens. Locally Vite's server forwards the API's paths; in
// production a reverse proxy does the same (serve dist/, send /v1, /api, /health to the API).
export default defineConfig(({ mode }) => {
  const env = { ...loadEnv(mode, process.cwd(), ""), ...process.env };
  const api = (env.PMAGENT_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
  // xfwd: the API sees the browser's address (it trusts X-Forwarded-For from 127.0.0.1).
  const forward: ProxyOptions = { target: api, xfwd: true };
  const proxy = { "/v1": forward, "/api": forward, "/health": forward };
  return {
    plugins: [react(), tailwindcss()],
    resolve: { alias: { "@": fileURLToPath(new URL(".", import.meta.url)) } },
    server: { port: 3000, strictPort: true, proxy },
    preview: { port: 3000, strictPort: true, proxy },
    build: { outDir: env.PMAGENT_WEB_OUT_DIR || "dist" },
  };
});
