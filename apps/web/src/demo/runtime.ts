// Isolated demo runtime: loaded on demand only when visiting /demo or /w/dotrix.
import { confirmDlg } from "../core/more";
import { go } from "../core/nav";
import { live } from "../data/live";
import { DEFAULT_PREFS, S, registerDemoHooks, render, save, setLiveData } from "../data/store";
import type { Data } from "../data/types";
import { toast } from "../ui/toast";
import { demoAlwaysAllow, demoAnswerCheckpoint, demoContinueLimited, demoDecideChange, demoDecideCoding, demoStartCoding } from "./agents";
import { openDemoRequest } from "./request";
import { seed } from "./seed";
import { demoCodingSessions } from "./sessions";

const DEMO_STORE_KEY = "dotrix.demo.v2";
const LEGACY_STORE_KEY = "dotrix.studio.v2";

export const DEMO_PREFS = {
  name: "John Doe",
  title: "Head of Product",
};

function loadDemoData(): Data {
  try {
    const raw = localStorage.getItem(DEMO_STORE_KEY) ?? localStorage.getItem(LEGACY_STORE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Data | { data?: Data };
      const candidate = "tasks" in parsed ? parsed : parsed?.data;
      if (candidate?.tasks && candidate.threads && candidate.ws?.url === "dotrix") {
        const owner = candidate.members?.find((m) => m.id === "m1");
        if (owner?.name === "Tanjim Islam") owner.name = DEMO_PREFS.name;
        return candidate;
      }
    }
  } catch {
    /* storage blocked or corrupt: start from the seed */
  }
  return seed();
}

function saveDemoData(data: Data) {
  try {
    localStorage.setItem(DEMO_STORE_KEY, JSON.stringify(data));
  } catch {
    /* storage full or blocked: keep working in memory */
  }
}

export function resetDemo() {
  S.ui.pop = null;
  confirmDlg({
    title: "Reset demo data?",
    body: "All projects, tasks, and settings in this browser go back to the original sample workspace.",
    ok: "Reset data",
    danger: true,
    icon: "rotate-ccw",
    run: () => {
      S.data = seed();
      S.views = {};
      S.prefs = { ...DEFAULT_PREFS, ...DEMO_PREFS, theme: S.prefs.theme };
      S.ui.drawer = null;
      save();
      go("home");
      toast("Demo data restored");
    },
  });
}

registerDemoHooks({
  saveData: saveDemoData,
  reset: resetDemo,
  openRequest: openDemoRequest,
  codingSessions: demoCodingSessions,
  decideChange: demoDecideChange,
  alwaysAllow: demoAlwaysAllow,
  answerCheckpoint: demoAnswerCheckpoint,
  startCoding: demoStartCoding,
  decideCoding: demoDecideCoding,
  continueLimited: demoContinueLimited,
});

/** Mount the browser-only sample workspace (/demo or /w/dotrix). */
export function mountDemo() {
  if (live.mode === "demo" && S.data.projects.length > 0) return;
  S.data = loadDemoData();
  if (!S.prefs.name || S.prefs.name === "Tanjim Islam") S.prefs.name = DEMO_PREFS.name;
  if (!S.prefs.title) S.prefs.title = DEMO_PREFS.title;
  if (S.ui.expanded.p1 === undefined) S.ui.expanded.p1 = true;
  setLiveData(null);
  live.mode = "demo";
  live.slug = null;
  live.ws = null;
  live.dirReady = false;
  Object.assign(S.ui, { drawer: null, modals: [], pop: null, palette: null, sel: new Set<string>(), composer: null, editCell: null });
  render();
}

export { demoCodingSessions, openDemoRequest, seed };
