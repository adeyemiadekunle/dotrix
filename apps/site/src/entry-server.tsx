// The page as HTML, for prerender.mjs.
import { renderToString } from "react-dom/server";

import { App } from "./App";
import { DesignProvider } from "@dotrix/ui/theme";

export function render(): string {
  return renderToString(
    <DesignProvider>
      <App />
    </DesignProvider>,
  );
}
