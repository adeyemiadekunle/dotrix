import "@fontsource-variable/geist";
import "@fontsource-variable/geist-mono";
import "@pmagent/ui/globals.css";
import "./fonts.css";

import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { applyStoredAccent } from "@/lib/accent";

import { Providers } from "./providers";
import { router } from "./router";

applyStoredAccent();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Providers>
      <RouterProvider router={router} />
    </Providers>
  </StrictMode>,
);
