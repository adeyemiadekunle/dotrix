// dotrix.cc: the landing page, prerendered to static HTML at build time (prerender.mjs).
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

const appRoot = fileURLToPath(new URL(".", import.meta.url));
export default defineConfig({
  root: appRoot,
  envDir: appRoot,
  envPrefix: "VITE_",
  plugins: [react(), tailwindcss()],
  server: { port: 3200 },
  preview: { port: 3200 },
});
