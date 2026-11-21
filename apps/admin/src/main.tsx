import "@fontsource-variable/geist";
import "@fontsource-variable/geist-mono";
import "@dotrix/ui/globals.css";
import "./admin.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";

// Follow the system theme like the web app does (design.css dark tokens via .dark).
const dark = matchMedia("(prefers-color-scheme: dark)");
const applyTheme = () => {
  document.documentElement.classList.toggle("dark", dark.matches);
  document.documentElement.style.colorScheme = dark.matches ? "dark" : "light";
};
applyTheme();
dark.addEventListener("change", applyTheme);

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
