import { defineTheme } from "@astryxdesign/core/theme";
import { icons } from "./icons";

// Website theme reference: meta/astryx 56680f6. Brand marks remain Dotrix-owned.
export const dotrixTheme = defineTheme({
  name: "dotrix",
  tokens: {
    "--color-accent": "light-dark(#15110C, #DFE2E5)",
    "--color-text-accent": "var(--color-accent)",
    "--color-icon-accent": "var(--color-accent)",
    "--color-accent-muted": "light-dark(rgba(21,17,12,.08), rgba(223,226,229,.14))",
    "--color-on-accent": "light-dark(#FFFFFF, #15110C)",
    "--color-background-body": "light-dark(#F8F4ED, #111112)",
    "--color-text-primary": "light-dark(#15110C, #DFE2E5)",
    "--color-icon-primary": "var(--color-text-primary)",
    "--radius-inner": "8px",
    "--radius-element": "12px",
    "--radius-container": "16px",
    "--radius-page": "32px",
    "--text-display-1-weight": "var(--font-weight-semibold)",
    "--text-display-2-weight": "var(--font-weight-semibold)",
    "--text-display-3-weight": "var(--font-weight-semibold)",
  },
  typography: {
    body: { family: "Figtree Variable", fallbacks: "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" },
    code: { family: "Geist Mono Variable", fallbacks: "ui-monospace, monospace" },
    heading: { family: "Figtree Variable", fallbacks: "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" },
  },
  adaptations: { widthBreakpoints: { sm: 640, md: 900, lg: 1024, xl: 1280, "2xl": 1536 } },
  components: { button: { base: { borderRadius: "var(--radius-full)" } } },
  icons,
});
