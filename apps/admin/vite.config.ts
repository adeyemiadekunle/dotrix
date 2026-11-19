// The admin console: a separate origin from the web app (dev :3300), never bundled into it.
// Only the console's API routes (/v1/admin) are proxied; app/web session routes are not.
import { fileURLToPath } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const appRoot = fileURLToPath(new URL(".", import.meta.url));
  const env = { ...loadEnv(mode, appRoot, ""), ...process.env };
  return {
    root: appRoot,
    envDir: appRoot,
    envPrefix: "VITE_",
    plugins: [react(), tailwindcss()],
    server: {
      port: 3300,
      proxy: {
        "^/v1/admin(?:/|$)": { target: env.DOTRIX_API_URL || "http://127.0.0.1:8000", changeOrigin: true },
      },
    },
  };
});
