import "@fontsource-variable/geist";
import "@fontsource-variable/geist-mono";
import "./styles.css";

import { hydrateRoot } from "react-dom/client";

import { App } from "./App";

hydrateRoot(document.getElementById("root")!, <App />);

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
