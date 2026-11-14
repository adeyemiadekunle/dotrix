// dotrix.cc: the landing page, prerendered to static HTML at build time (prerender.mjs).
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 3200 },
  preview: { port: 3200 },
});
