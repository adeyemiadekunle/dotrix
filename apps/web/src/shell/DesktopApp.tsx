import { ActionButton } from "@dotrix/ui/components/action-button";
// The desktop app's own parts of the shell (core/desktop.ts): a bar when a new version is ready
// ("dotrix 0.2.0 is ready", Restart), and What's new, the releases in the app's CHANGELOG.md, opened from
// the sidebar or the bar and once on its own after the app updated. In a browser none of it shows.
import { useEffect, useState } from "react";

import { Markdown } from "@/components/markdown";
import { desktopApp, desktopBrowser, useDesktopUpdate, type DesktopRelease, type KaiTabRequest } from "../core/desktop";
import { Ic } from "../core/icons";
import { go } from "../core/nav";
import { CODING_AGENT } from "../data/seed-dotrix";
import { openModal } from "../core/more";
import { toast } from "../ui/toast";

const SEEN = "dotrix.desktop.version"; // the version this browser profile last opened in

export const openWhatsNew = () => openModal({ type: "whatsNew" });

/** Opens What's new once after the app updated to a new version (not on a first install). */
export function useWhatsNewAfterUpdate() {
  useEffect(() => {
    const bridge = desktopApp();
    if (!bridge) return;
    void bridge.app.info().then(({ version, packaged }) => {
      if (!packaged) return;
      let seen: string | null = null;
      try {
        seen = localStorage.getItem(SEEN);
        localStorage.setItem(SEEN, version);
      } catch {
        return;
      }
      if (seen && seen !== version) openWhatsNew();
    });
  }, []);
}

/** Whether a coding session is the one open in Codes now. */
function showing(sessionId: string): boolean {
  return window.location.pathname.endsWith("/codes") && new URLSearchParams(window.location.search).get("session") === sessionId;
}

/** Kai, coding on this computer, wants its browser tab while its session isn't open: a notice offers to open it (with its Browser
 *  pane, which makes the tab). Kai waits about a minute, then goes on without the browser. */
export function useKaiBrowserNotice() {
  useEffect(() => {
    const bridge = desktopBrowser();
    if (!bridge) return;
    const told = new Set<number>();
    const tell = (request: KaiTabRequest) => {
      if (told.has(request.id) || showing(request.sessionId)) return;
      told.add(request.id);
      toast(`${CODING_AGENT.name} wants to check its change on ${request.issueKey} in the browser`, {
        action: "Open the session",
        onAction: () => go("codes", {}, { search: `session=${encodeURIComponent(request.sessionId)}&panel=browser` }),
        ms: 60_000,
      });
    };
    void bridge.kaiRequests().then((waiting) => waiting.forEach(tell));
    return bridge.onKai(tell);
  }, []);
}

/** "dotrix X is ready": restart into it now, or it installs when the app quits. */
export function UpdateBar() {
  const update = useDesktopUpdate();
  const [later, setLater] = useState<string | null>(null);
  const [restarting, setRestarting] = useState(false);
  if (update?.state !== "ready" || later === update.version) return null;
  const restart = () => {
    setRestarting(true);
    desktopApp()
      ?.updates.install()
      .catch((e: unknown) => {
        setRestarting(false);
        toast(e instanceof Error ? e.message : "The update couldn't be installed", { kind: "err" });
      });
  };
  return (
    <div className="update-bar" role="status">
      <Ic n="arrow-circle-down" s={16} />
      <span className="grow">
        <b>dotrix {update.version} is ready.</b> <span className="muted">Restart to use it, or it installs when you quit. A turn coding here stops first.</span>
      </span>
      <ActionButton className="btn btn-sm btn-ghost hide-m" onClick={() => setLater(update.version)}>
        Later
      </ActionButton>
      <ActionButton className="btn btn-sm btn-primary" onClick={restart} disabled={restarting}>
        {restarting ? "Restarting…" : "Restart"}
      </ActionButton>
    </div>
  );
}

const day = (iso: string | null) =>
  iso ? new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" }) : null;

/** What's new: each release's changes, newest first, with its version. */
export function WhatsNew({ onClose }: { onClose: () => void }) {
  const [releases, setReleases] = useState<DesktopRelease[] | null>(null);
  const [version, setVersion] = useState<string | null>(null);
  const update = useDesktopUpdate();
  useEffect(() => {
    const bridge = desktopApp();
    if (!bridge) return setReleases([]);
    void bridge.app.info().then((i) => setVersion(i.version));
    bridge.app.changelog().then(setReleases, () => setReleases([]));
  }, []);
  return (
    <>
      <div className="modal-h">
        <div>
          <h2 id="mt-whatsNew">What&apos;s new</h2>
          {version && (
            <div className="muted" style={{ fontSize: 12.5, marginTop: 2 }}>
              You have dotrix {version}
              {update?.state === "ready" ? `; ${update.version} is ready to install` : ""}
            </div>
          )}
        </div>
        <ActionButton className="ibtn ibtn-sm" onClick={onClose} aria-label="Close">
          <Ic n="x" s={16} />
        </ActionButton>
      </div>
      <div className="modal-b wn">
        {releases === null && <p className="muted">Loading…</p>}
        {releases?.length === 0 && <p className="muted">No release notes in this build.</p>}
        {releases?.map((r) => (
          <section key={r.version} className="wn-rel">
            <div className="wn-head">
              <h3>{day(r.date) ?? r.version}</h3>
              <span className="wn-ver mono">{r.version}</span>
            </div>
            {r.sections.map((s) => (
              <div key={s.title}>
                <div className="eyebrow wn-sec">{s.title}</div>
                <ul>
                  {s.items.map((item, i) => (
                    <li key={i}>
                      <Markdown>{item}</Markdown>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </section>
        ))}
      </div>
    </>
  );
}
