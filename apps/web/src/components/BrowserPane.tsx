// The Browser pane beside a coding session, in the desktop app only: tabs of web pages (your running app,
// documentation, an issue tracker) in a profile of their own, apart from dotrix and from your everyday
// browser. Each tab is a <webview> the app checks before it exists (apps/desktop: browser.ts): web addresses
// only, no permissions, no downloads, and a page that asks for a new window gets a new tab here.
// A person chooses whether that profile's cookies outlive the app, and can clear what it saved.
// Kai, on a turn coding on this computer, gets one tab of its own here (apps/desktop: browserKai.ts): it asks
// for it at an address on this computer, this pane makes it and says which page it is, and the person
// watches Kai read, click and type there. A person can turn that off in the pane's menu.
import { ActionButton } from "@dotrix/ui/components/action-button";
import { createElement, memo, useCallback, useEffect, useRef, useState, type FormEvent } from "react";

import { hostOf, toAddress } from "../core/browserUrl";
import { desktopBrowser, setBrowserSettings as setSettings, useBrowserSettings, type KaiTabRequest } from "../core/desktop";
import { Ic } from "../core/icons";
import { CODING_AGENT } from "../data/seed-dotrix";
import { toast } from "../ui/toast";
import { PanelFrame } from "./SidePanel";

/** What Electron's <webview> offers the page that holds it (only what the pane uses). */
interface Webview extends HTMLElement {
  loadURL(url: string): Promise<void>;
  getURL(): string;
  getTitle(): string;
  canGoBack(): boolean;
  canGoForward(): boolean;
  goBack(): void;
  goForward(): void;
  reload(): void;
  stop(): void;
  getWebContentsId(): number;
}

interface Tab {
  id: string;
  /** The address its page was created with (null: a new tab, no page yet). Never changed: changing it would navigate. */
  initial: string | null;
  url: string | null;
  title: string;
  loading: boolean;
  back: boolean;
  forward: boolean;
  failed: string | null;
  /** Kai's tab: the request it was made for (null: a person's tab). */
  kai: number | null;
}

type Patch = Partial<Omit<Tab, "id" | "initial" | "kai">>;

let serial = 0;
const newTab = (url: string | null = null, kai: number | null = null): Tab => ({
  id: `tab-${++serial}`,
  initial: url,
  url,
  title: "",
  loading: Boolean(url),
  back: false,
  forward: false,
  failed: null,
  kai,
});

// A session's tabs while the app runs, so closing the pane (or opening another session) doesn't lose them.
const kept = new Map<string, { urls: (string | null)[]; active: number }>();

/** One tab's page. Its props never change after it's made (src would navigate again), so it never renders twice. */
const Page = memo(function Page({
  id,
  src,
  partition,
  kai,
  onChange,
  onElement,
}: {
  id: string;
  src: string;
  partition: string;
  kai: number | null;
  onChange: (id: string, patch: Patch) => void;
  onElement: (id: string, element: Webview | null) => void;
}) {
  const ref = useRef<Webview | null>(null);
  useEffect(() => {
    const page = ref.current;
    if (!page) return;
    let ready = false; // its methods throw until the first dom-ready
    const sync = (extra: Patch = {}) => {
      if (!ready) return onChange(id, extra);
      onChange(id, { url: page.getURL(), title: page.getTitle(), back: page.canGoBack(), forward: page.canGoForward(), ...extra });
    };
    const events: [string, (event: Event) => void][] = [
      [
        "dom-ready",
        () => {
          // Kai's tab, loaded for the first time: the app learns which page it is (and checks it).
          if (!ready && kai !== null) void desktopBrowser()?.kaiReady(kai, page.getWebContentsId());
          ready = true;
          onElement(id, page);
          sync();
        },
      ],
      ["did-start-loading", () => sync({ loading: true, failed: null })],
      ["did-stop-loading", () => sync({ loading: false })],
      ["did-navigate", () => sync()],
      ["did-navigate-in-page", () => sync()],
      ["page-title-updated", () => sync()],
      [
        "did-fail-load",
        (event) => {
          const failure = event as Event & { errorCode?: number; errorDescription?: string; isMainFrame?: boolean; validatedURL?: string };
          // -3 is a load given up for another (a second address typed, Stop): not a failure to show.
          if (!failure.isMainFrame || failure.errorCode === -3) return;
          onChange(id, { loading: false, failed: failure.errorDescription || "The page couldn't be loaded", url: failure.validatedURL || undefined });
        },
      ],
    ];
    for (const [name, listener] of events) page.addEventListener(name, listener);
    return () => {
      for (const [name, listener] of events) page.removeEventListener(name, listener);
      onElement(id, null);
    };
  }, [id, kai, onChange, onElement]);
  return createElement("webview", { ref, src, partition, allowpopups: "true", className: "browser-page" });
});

export function BrowserPane({
  sessionId,
  stacked,
  expanded,
  onExpand,
  onClose,
}: {
  sessionId: string;
  stacked: boolean;
  expanded: boolean;
  onExpand?: () => void;
  onClose: () => void;
}) {
  const bridge = desktopBrowser();
  const settings = useBrowserSettings();
  const [tabs, setTabs] = useState<Tab[]>(() => {
    const saved = kept.get(sessionId);
    return saved?.urls.length ? saved.urls.map((url) => newTab(url)) : [newTab()];
  });
  const [activeId, setActiveId] = useState(() => tabs[Math.min(kept.get(sessionId)?.active ?? 0, tabs.length - 1)]!.id);
  const active = tabs.find((tab) => tab.id === activeId) ?? tabs[0]!;
  const [draft, setDraft] = useState(active.url ?? "");
  const [problem, setProblem] = useState<string | null>(null);
  const [menu, setMenu] = useState(false);
  const pages = useRef(new Map<string, Webview>());
  const address = useRef<HTMLInputElement>(null);

  // Remembered for the next time this session's pane opens.
  useEffect(() => {
    kept.set(sessionId, { urls: tabs.map((tab) => tab.url), active: Math.max(0, tabs.indexOf(active)) });
  }, [sessionId, tabs, active]);

  // The address bar follows the tab and its page, unless a person is typing in it.
  const shownTab = useRef(active.id);
  useEffect(() => {
    if (shownTab.current !== active.id || document.activeElement !== address.current) setDraft(active.url ?? "");
    shownTab.current = active.id;
    setProblem(null);
  }, [active.id, active.url]);
  useEffect(() => {
    if (!active.url) address.current?.focus();
  }, [active.id, active.url]);

  const change = useCallback((id: string, patch: Patch) => {
    const defined = Object.fromEntries(Object.entries(patch).filter(([, value]) => value !== undefined)) as Patch;
    setTabs((all) => all.map((tab) => (tab.id === id ? { ...tab, ...defined } : tab)));
  }, []);
  const element = useCallback((id: string, page: Webview | null) => {
    if (page) pages.current.set(id, page);
    else pages.current.delete(id);
  }, []);

  const open = useCallback((url: string | null = null) => {
    const tab = newTab(url);
    setTabs((all) => [...all, tab]);
    setActiveId(tab.id);
  }, []);
  // A page that asks for a new window gets a tab.
  useEffect(() => bridge?.onOpen((url) => open(url)), [bridge, open]);
  // Kai asks for its tab (now, or before this pane opened): made once per request, and shown.
  const made = useRef(new Set<number>());
  useEffect(() => {
    if (!bridge) return;
    const make = (request: KaiTabRequest | null) => {
      if (!request || made.current.has(request.id)) return;
      made.current.add(request.id);
      const tab = newTab(request.url, request.id);
      setTabs((all) => [...all.filter((other) => other.initial !== null), tab]); // in place of an empty new tab
      setActiveId(tab.id);
    };
    void bridge.kaiRequest().then(make);
    return bridge.onKai(make);
  }, [bridge]);

  const close = (id: string) => {
    const index = tabs.findIndex((tab) => tab.id === id);
    const rest = tabs.filter((tab) => tab.id !== id);
    if (!rest.length) {
      const blank = newTab();
      setTabs([blank]);
      setActiveId(blank.id);
    } else {
      setTabs(rest);
      if (id === activeId) setActiveId(rest[Math.min(index, rest.length - 1)]!.id);
    }
  };

  const visit = (event: FormEvent) => {
    event.preventDefault();
    const url = toAddress(draft);
    if (!url) return setProblem("Enter a web address, like localhost:3000");
    setProblem(null);
    address.current?.blur();
    const page = pages.current.get(active.id);
    if (page) void page.loadURL(url).catch(() => undefined);
    // No page yet (a new tab, or one still starting): make it at this address.
    else {
      const next = newTab(url);
      setTabs((all) => all.map((tab) => (tab.id === active.id ? next : tab)));
      setActiveId(next.id);
    }
  };

  // Close the menu on a click elsewhere or Escape (a click inside a page never reaches this document: focus leaving does).
  useEffect(() => {
    if (!menu) return;
    const away = (event: Event) => {
      if (!(event.target instanceof HTMLElement) || !event.target.closest(".browser-menu, [data-browser-menu]")) setMenu(false);
    };
    const escape = (event: KeyboardEvent) => event.key === "Escape" && setMenu(false);
    document.addEventListener("mousedown", away);
    document.addEventListener("focusin", away);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("focusin", away);
      document.removeEventListener("keydown", escape);
    };
  }, [menu]);

  const keepCookies = async () => {
    if (!bridge || !settings) return;
    setMenu(false);
    try {
      const next = await bridge.setKeepCookies(!settings.keepCookies);
      // The other profile: every page starts again in it, at its address.
      const fresh = tabs.map((tab) => newTab(tab.url));
      setTabs(fresh);
      setActiveId(fresh[Math.max(0, tabs.indexOf(active))]!.id);
      setSettings(next);
      toast(next.keepCookies ? "Cookies are kept after you quit dotrix" : "Cookies are cleared when you quit dotrix");
    } catch {
      toast("The setting couldn't be saved");
    }
  };
  const kaiAllowed = async () => {
    if (!bridge || !settings) return;
    setMenu(false);
    try {
      const next = await bridge.setKaiAllowed(!settings.kaiAllowed);
      setSettings(next);
      toast(
        next.kaiAllowed ? `${CODING_AGENT.name} can use the browser on turns coding on this computer` : `${CODING_AGENT.name} can no longer use the browser`,
      );
    } catch {
      toast("The setting couldn't be saved");
    }
  };
  const clear = async () => {
    setMenu(false);
    try {
      await bridge?.clear();
      for (const page of pages.current.values()) page.reload();
      toast("Browsing data cleared");
    } catch {
      toast("The browsing data couldn't be cleared");
    }
  };

  const page = pages.current.get(active.id);
  return (
    <PanelFrame
      label="Browser"
      widthKey="dotrix.coding.panel.width"
      onClose={onClose}
      closeLabel="Close Browser"
      stacked={stacked}
      expanded={expanded}
      onExpand={onExpand}
      title={
        <span className="side-panel-title">
          <Ic n="globe" s={14} />
          <b>Browser</b>
        </span>
      }
      tools={
        <div className="cs-title-wrap">
          <ActionButton
            className="ibtn ibtn-sm"
            data-browser-menu
            onClick={() => setMenu(!menu)}
            aria-haspopup="menu"
            aria-expanded={menu}
            aria-label="Browser options"
            data-tip={menu ? undefined : "Options"}
          >
            <Ic n="dots-three" s={14} />
          </ActionButton>
          {menu && (
            <div className="pop cs-menu right browser-menu" role="menu" aria-label="Browser options">
              <button role="menuitemcheckbox" aria-checked={settings?.keepCookies ?? false} disabled={!settings} onClick={() => void keepCookies()}>
                <Ic n="cookie" s={14} />
                <span className="grow">Keep cookies after quitting</span>
                {settings?.keepCookies && <Ic n="check" s={14} />}
              </button>
              <button role="menuitem" onClick={() => void clear()}>
                <Ic n="trash" s={14} />
                <span className="grow">Clear browsing data</span>
              </button>
              <hr />
              <button role="menuitemcheckbox" aria-checked={settings?.kaiAllowed ?? false} disabled={!settings} onClick={() => void kaiAllowed()}>
                <Ic n="cursor-click" s={14} />
                <span className="grow">Let {CODING_AGENT.name} use the browser</span>
                {settings?.kaiAllowed && <Ic n="check" s={14} />}
              </button>
              {active.url && (
                <>
                  <hr />
                  <button role="menuitem" onClick={() => (setMenu(false), window.open(active.url!, "_blank", "noopener"))}>
                    <Ic n="arrow-square-out" s={14} />
                    <span className="grow">Open in your browser</span>
                  </button>
                </>
              )}
            </div>
          )}
        </div>
      }
    >
      <div className="browser">
        <div className="browser-tabs" role="tablist" aria-label="Browser tabs">
          {tabs.map((tab) => (
            <div key={tab.id} className={`browser-tab ${tab.id === active.id ? "on" : ""}`}>
              <button
                role="tab"
                aria-selected={tab.id === active.id}
                className="browser-tab-name"
                onClick={() => setActiveId(tab.id)}
                title={tab.url ?? "New tab"}
              >
                {tab.loading && <span className="browser-busy" aria-hidden />}
                {tab.kai !== null && <span className="badge">{CODING_AGENT.name}</span>}
                <span className="trunc">{tab.title || (tab.url ? hostOf(tab.url) : "New tab")}</span>
              </button>
              <button className="browser-tab-close" aria-label={`Close ${tab.title || "tab"}`} onClick={() => close(tab.id)}>
                <Ic n="x" s={11} />
              </button>
            </div>
          ))}
          <ActionButton className="ibtn ibtn-sm" onClick={() => open()} aria-label="New tab" data-tip="New tab">
            <Ic n="plus" s={13} />
          </ActionButton>
        </div>
        <form className="browser-bar" onSubmit={visit}>
          <ActionButton type="button" className="ibtn ibtn-sm" disabled={!active.back} onClick={() => page?.goBack()} aria-label="Back" data-tip="Back">
            <Ic n="arrow-left" s={14} />
          </ActionButton>
          <ActionButton
            type="button"
            className="ibtn ibtn-sm"
            disabled={!active.forward}
            onClick={() => page?.goForward()}
            aria-label="Forward"
            data-tip="Forward"
          >
            <Ic n="arrow-right" s={14} />
          </ActionButton>
          <ActionButton
            type="button"
            className="ibtn ibtn-sm"
            disabled={!page}
            onClick={() => (active.loading ? page?.stop() : page?.reload())}
            aria-label={active.loading ? "Stop loading" : "Reload"}
            data-tip={active.loading ? "Stop" : "Reload"}
          >
            <Ic n={active.loading ? "x" : "arrow-clockwise"} s={14} />
          </ActionButton>
          <input
            ref={address}
            className="input browser-address"
            value={draft}
            onChange={(event) => (setDraft(event.target.value), setProblem(null))}
            onFocus={(event) => event.target.select()}
            placeholder="localhost:3000 or a web address"
            aria-label="Address"
            aria-invalid={Boolean(problem)}
            spellCheck={false}
            autoCapitalize="off"
            autoCorrect="off"
          />
        </form>
        {problem && (
          <p className="browser-note" role="alert">
            {problem}
          </p>
        )}
        {active.failed && (
          <p className="browser-note" role="alert">
            {active.url ? `${hostOf(active.url)} didn't load: ` : ""}
            {active.failed}
          </p>
        )}
        <div className="browser-pages">
          {!active.initial && (
            <div className="browser-empty muted">
              <Ic n="globe" s={22} />
              <p>Open your running app or any web page here.</p>
              <p className="faint">
                Pages here don't share your everyday browser's sign-ins.{" "}
                {settings?.keepCookies ? "Cookies are kept after you quit dotrix." : "Cookies are cleared when you quit dotrix."}
              </p>
            </div>
          )}
          {settings &&
            tabs.map(
              (tab) =>
                tab.initial && (
                  <div key={`${settings.partition}:${tab.id}`} className={`browser-slot ${tab.id === active.id ? "on" : ""}`}>
                    <Page id={tab.id} src={tab.initial} partition={settings.partition} kai={tab.kai} onChange={change} onElement={element} />
                  </div>
                ),
            )}
        </div>
      </div>
    </PanelFrame>
  );
}
