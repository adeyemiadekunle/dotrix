// The Admin app: a separate origin from the web app (dev :3200), never bundled into it.
// It talks only to /v1/ops/* — its own accounts and sign-in — plus nothing public.
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 3200,
    proxy: {
      "/v1": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
});
