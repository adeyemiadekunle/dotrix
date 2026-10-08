// The workspace app (Gr8r's render loop, gr8r-studio/src/shell/render.js): your preferences on
// <html>, the page title, the shell with the screen for the URL, and the overlay layers.
import { useEffect, type ReactNode } from "react";

import { applyPrefs } from "../core/theme";
import { useRoute, type Route } from "../core/nav";
import { D, projByKey, team, useStudio } from "../data/store";
import { ModalLayer } from "../overlays/Modals";
import { Home } from "../screens/Home";
import { Empty } from "../ui/helpers";
import { ROUTE_NAMES, Shell } from "./Shell";

const SCREENS: Partial<Record<Route, () => ReactNode>> = {
  home: Home,
};

function NotFound() {
  return (
    <div className="page">
      <Empty icon="file-question" title="Page not found" text="The page you're looking for doesn't exist or was moved." />
    </div>
  );
}

function Screen() {
  const { route } = useRoute();
  if (route === "notfound") return <NotFound />;
  const C = SCREENS[route];
  if (C) return <C />;
  return (
    <div className="page">
      <Empty icon="hammer" title={ROUTE_NAMES[route] ?? "Coming next"} text="This screen is being brought over from Gr8r Studio." />
    </div>
  );
}

export function Studio() {
  useStudio();
  const { route, params } = useRoute();
  applyPrefs();
  useEffect(() => {
    let t = ROUTE_NAMES[route] || "Not found";
    if (route === "project") {
      const p = projByKey(params.id);
      if (p) t = `${params.tab ? params.tab[0]!.toUpperCase() + params.tab.slice(1) : "Board"} · ${p.name}`;
    }
    if (route === "member") t = D().members.find((m) => m.id === params.id)?.name ?? t;
    if (route === "team") t = team(params.id)?.name ?? t;
    document.title = `${t} · ${D().ws.name}`;
  });
  return (
    <>
      <Shell>
        <Screen />
      </Shell>
      <ModalLayer />
    </>
  );
}
