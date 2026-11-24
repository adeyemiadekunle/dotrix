// Each route as HTML, for prerender.mjs.
import { renderToString } from "react-dom/server";

import { App } from "./App";

export function render(pathname = "/"): string {
  return renderToString(<App pathname={pathname} />);
}
