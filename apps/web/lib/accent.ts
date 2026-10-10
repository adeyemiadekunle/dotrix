// The accent colour (Settings → Appearance): a choice per browser, like the theme. It sets
// `data-accent` on <html>, which swaps the primary colour (packages/ui globals.css).
import { useState } from "react";

export const ACCENTS = [
  { value: "indigo", label: "Indigo", light: "#4b5bd6" },
  { value: "blue", label: "Blue", light: "#2f6cd4" },
  { value: "violet", label: "Violet", light: "#7348cc" },
  { value: "teal", label: "Teal", light: "#1a7f7a" },
  { value: "rose", label: "Rose", light: "#b93d68" },
  { value: "graphite", label: "Graphite", light: "#34332f" },
] as const;

export type Accent = (typeof ACCENTS)[number]["value"];

const KEY = "dotrix.accent";

function stored(): Accent {
  try {
    const value = localStorage.getItem(KEY);
    return ACCENTS.some((a) => a.value === value) ? (value as Accent) : "indigo";
  } catch {
    return "indigo"; // storage blocked: the default
  }
}

function apply(accent: Accent) {
  if (accent === "indigo") delete document.documentElement.dataset.accent;
  else document.documentElement.dataset.accent = accent;
}

/** At startup, before the first paint, so the colour doesn't flash. */
export function applyStoredAccent() {
  apply(stored());
}

export function useAccent(): [Accent, (accent: Accent) => void] {
  const [accent, setAccent] = useState<Accent>(stored);
  return [
    accent,
    (next) => {
      setAccent(next);
      apply(next);
      try {
        localStorage.setItem(KEY, next);
      } catch {
        // only a convenience: it lasts until the page reloads
      }
    },
  ];
}
