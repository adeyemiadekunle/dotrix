import "@dotrix/ui/fonts.css";
import "@fontsource-variable/geist-mono";
import "@dotrix/ui/globals.css";
import "./styles.css";

import { hydrateRoot } from "react-dom/client";

import { App } from "./App";
import { DesignProvider } from "@dotrix/ui/theme";

hydrateRoot(
  document.getElementById("root")!,
  <DesignProvider>
    <App />
  </DesignProvider>,
);

const dark = matchMedia("(prefers-color-scheme: dark)");
const applyTheme = () => document.documentElement.classList.toggle("dark", dark.matches);
applyTheme();
dark.addEventListener("change", applyTheme);

// Sections fade in as they come into view (CSS skips it for people who prefer less motion).
const seen = new IntersectionObserver(
  (entries) => {
    for (const entry of entries) {
      if (entry.isIntersecting) {
        entry.target.classList.add("in");
        seen.unobserve(entry.target);
      }
    }
  },
  { rootMargin: "0px 0px -10% 0px" },
);
document.querySelectorAll(".reveal").forEach((el) => seen.observe(el));
