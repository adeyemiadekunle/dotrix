// The admin console: a separate origin from the web app (dev :3300), never bundled into it.
// Only the console's API routes (/v1/ops) are proxied; app/web session routes are not.
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 3300,
    proxy: {
      "^/v1/ops(?:/|$)": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
});
