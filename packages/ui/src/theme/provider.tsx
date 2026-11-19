import { useSyncExternalStore, type ReactNode } from "react";
import { Theme } from "@astryxdesign/core/theme";
import { LayerProvider } from "@astryxdesign/core/Layer";
import { InternationalizationProvider } from "@astryxdesign/core/i18n";
import { dotrixTheme } from "./dotrix.js";
import { dotrixReducedTheme } from "./dotrix-reduced.js";
import { ToastHost } from "../lib/toast";

function subscribe(update: () => void) {
  const observer = new MutationObserver(update);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class", "data-motion"] });
  return () => observer.disconnect();
}
function snapshot() {
  const root = document.documentElement;
  return `${root.classList.contains("dark") ? "dark" : "light"}:${root.dataset.motion ?? "system"}`;
}

/** Shares the product's pre-paint preference state with Astryx, including portals. */
export function DesignProvider({ children }: { children: ReactNode }) {
  const preference = useSyncExternalStore(subscribe, snapshot, () => "system:system");
  const [mode, motion] = preference.split(":") as ["system" | "light" | "dark", string];
  return (
    <Theme theme={motion === "reduce" ? dotrixReducedTheme : dotrixTheme} mode={mode}>
      <InternationalizationProvider locale="en-US">
        <LayerProvider toast={{ position: "bottomEnd", maxVisible: 4 }}>
          {children}
          <ToastHost />
        </LayerProvider>
      </InternationalizationProvider>
    </Theme>
  );
}
