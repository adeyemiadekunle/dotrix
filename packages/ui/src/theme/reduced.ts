import { defineTheme } from "@astryxdesign/core/theme";
import { dotrixTheme } from "./source";
// The published API follows OS motion automatically. Explicit product preference
// also removes CSS animation/transition through the shared stylesheet.
export const reducedTheme = defineTheme({
  name: "dotrix-reduced",
  extends: dotrixTheme,
  tokens: { "--duration-fast": "0ms", "--duration-medium": "0ms", "--duration-exit": "0ms" },
});
