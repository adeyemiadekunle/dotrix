import { describe, expect, it } from "vitest";

import type { AnyRouter } from "@tanstack/react-router";

import { go, routeOf, setRouter, type Params, type Route } from "./nav";

// href isn't exported, so the round trip captures what go() hands the router.
let last = "";
setRouter({ navigate: (o: { href: string }) => void (last = o.href) } as unknown as AnyRouter);
function hrefOf(route: Route, params: Params = {}, search?: string): string {
  go(route, params, { search });
  return last;
}

// Every Route, as a record so a new member fails the typecheck until it is added here.
const CASES: Record<Route, Params> = {
  home: {},
  inbox: {},
  mytasks: {},
  favorites: {},
  notifications: {},
  search: {},
  overview: {},
  projects: {},
  project: { id: "KUN", tab: "list" },
  tasks: {},
  calendar: {},
  timeline: {},
  members: {},
  member: { id: "m2" },
  teams: {},
  team: { id: "design" },
  activity: {},
  settings: { sec: "models" },
  archive: {},
  chat: {},
  codes: {},
};

describe("href and routeOf", () => {
  it.each(Object.keys(CASES) as Route[])("round-trips the %s page", (route) => {
    const params = CASES[route];
    expect(routeOf(hrefOf(route, params))).toEqual({ route, params: expect.objectContaining(params) });
  });

  it("round-trips settings without a section", () => {
    expect(routeOf(hrefOf("settings"))).toEqual({ route: "settings", params: { sec: undefined } });
  });

  it("defaults a project to its board", () => {
    expect(hrefOf("project", { id: "KUN" })).toBe("/w/dotrix/p/KUN/board");
    expect(routeOf("/w/dotrix/p/KUN/board")).toEqual({ route: "project", params: { id: "KUN", tab: "board" } });
  });

  it("keeps a task opened through the search string out of the path", () => {
    const h = hrefOf("project", { id: "KUN", tab: "board" }, "task=KUN-4");
    expect(h).toBe("/w/dotrix/p/KUN/board?task=KUN-4");
    expect(routeOf(h.split("?")[0]!)).toEqual({ route: "project", params: { id: "KUN", tab: "board" } });
  });
});

describe("routeOf", () => {
  it("reads params from project, member, team and settings addresses", () => {
    expect(routeOf("/w/dotrix/p/KUN/list")).toEqual({ route: "project", params: { id: "KUN", tab: "list" } });
    expect(routeOf("/w/dotrix/p/KUN")).toEqual({ route: "project", params: { id: "KUN", tab: "board" } });
    expect(routeOf("/w/dotrix/members/m2")).toEqual({ route: "member", params: { id: "m2" } });
    expect(routeOf("/w/dotrix/teams/design")).toEqual({ route: "team", params: { id: "design" } });
    expect(routeOf("/w/dotrix/settings/models")).toEqual({ route: "settings", params: { sec: "models" } });
    expect(routeOf("/w/dotrix/settings")).toEqual({ route: "settings", params: { sec: undefined } });
  });

  it("accepts a workspace slug and project key containing a hyphen", () => {
    expect(routeOf("/w/my-team/")).toEqual({ route: "home", params: {} });
    expect(routeOf("/w/my-team/p/MY-APP/board")).toEqual({ route: "project", params: { id: "MY-APP", tab: "board" } });
  });

  it("answers notfound for unknown paths", () => {
    expect(routeOf("/nope")).toEqual({ route: "notfound", params: {} });
    expect(routeOf("/w/dotrix/unknown")).toEqual({ route: "notfound", params: {} });
    expect(routeOf("/w/dotrix/inbox/extra")).toEqual({ route: "notfound", params: {} });
  });
});
