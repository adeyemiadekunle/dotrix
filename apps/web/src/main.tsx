import "@fontsource-variable/geist";
import "@fontsource-variable/geist-mono";
import "@dotrix/ui/globals.css";
import "./fonts.css";
import "./dotrix.css";

import { applyPrefs } from "./core/theme";

import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { Providers } from "./providers";
import { router } from "./router";

// Preferences (theme, accent) on <html> before the first paint, so nothing flashes.
applyPrefs();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Providers>
      <RouterProvider router={router} />
    </Providers>
  </StrictMode>,
);
