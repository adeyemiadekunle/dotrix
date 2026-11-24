import "@fontsource-variable/geist";
import "@fontsource-variable/geist-mono";
import "./styles.css";

import { createRoot, hydrateRoot } from "react-dom/client";

import { App } from "./App";

const pathname = window.location.pathname;
const route = pathname.replace(/\/+$/, "") || "/";
if (route === "/terms") document.title = "Terms of Service · dotrix";
else if (route === "/privacy") document.title = "Privacy Policy · dotrix";

const rootEl = document.getElementById("root")!;
if (rootEl.firstElementChild) hydrateRoot(rootEl, <App pathname={pathname} />);
else createRoot(rootEl).render(<App pathname={pathname} />);
