import "@fontsource-variable/geist";
import "@fontsource-variable/geist-mono";
import "@pmagent/ui/globals.css";
import "./fonts.css";

import { applyPrefs } from "./core/theme";

import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { Providers } from "./providers";
import { router } from "./router";

// Gr8r's preferences (theme, accent) on <html> before the first paint, so nothing flashes.
applyPrefs();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Providers>
      <RouterProvider router={router} />
    </Providers>
  </StrictMode>,
);
