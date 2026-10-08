// Gr8r's preferences on <html> (gr8r-studio/src/core/theme.js): theme (the .dark class), accent,
// sidebar and row density, reduced motion; and the date format.
import { S } from "../data/store";
import { setDateFormat } from "./utils";

const darkQuery = typeof matchMedia !== "undefined" ? matchMedia("(prefers-color-scheme: dark)") : null;

export function effectiveDark(): boolean {
  if (S.prefs.theme === "dark") return true;
  if (S.prefs.theme === "light") return false;
  return Boolean(darkQuery?.matches);
}

export function applyPrefs() {
  const r = document.documentElement;
  const p = S.prefs;
  setDateFormat(p.dateFmt);
  r.classList.toggle("dark", effectiveDark());
  r.style.colorScheme = effectiveDark() ? "dark" : "light";
  if (p.accent === "indigo") r.removeAttribute("data-accent");
  else r.setAttribute("data-accent", p.accent);
  r.setAttribute("data-side", p.side);
  r.setAttribute("data-density", p.density);
  if (p.motion === "reduce") r.setAttribute("data-motion", "reduce");
  else r.removeAttribute("data-motion");
}

/** Following the system: re-apply when it changes. */
darkQuery?.addEventListener("change", () => {
  if (S.prefs.theme === "system") applyPrefs();
});
