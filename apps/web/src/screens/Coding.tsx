import { Input as DesignInput } from "@dotrix/ui/components/input";
import { ActionButton } from "@dotrix/ui/components/action-button";
// dotrix's Codes: Kai's sessions, apart from Chat's conversations. The list holds every coding session
// you can see in one list (pinned first, then the latest); one started from a conversation is marked,
// links back to it, and still shows as a card there. Stopping, archiving, or deleting a session here leaves the
// conversation alone, and the other way round.
// URL: ?session=ID (a session, with &panel=, &turn=, &file=, &line=), ?new=1 (a new session, &issue=KEY), else the list.
import { useState, type CSSProperties } from "react";

import { useCodingSessions } from "@/lib/coding";
import { Ic } from "../core/icons";
import { useRoute } from "../core/nav";
import { isLive, live } from "../data/live";
import { D, S, render } from "../data/store";
import { Splitter, useStoredSize } from "../ui/splitter";
import { Message, NewSession, Pending, Session, SessionRow, SessionHeader, openCoding } from "./Chat";

import { buildTree, parseDiff } from "../core/kaiWork";
import { ChangeList, CommandList, FileTree } from "../components/TurnViews";
import { PanelFrame, type CodingView } from "../components/SidePanel";
import { SessionListToggle, SessionSidebarContext, useSessionSidebar } from "../components/SessionSidebar";
import { demoCodingSessions } from "../core/demoSessions";

const css = (o: Record<string, string | number>) => o as CSSProperties;
const ms = (at: string | null | undefined) => (at ? new Date(at).getTime() : Date.now());
const toList = (): [string, () => void] => ["Back to sessions", () => openCoding("")];

export function Coding() {
  const { search } = useRoute();
  const ws = isLive() ? live.ws?.id : undefined;
  const sessionId = search.get("session");
  // With nothing picked, the main column is the new-session form, as Chat's is a new chat.
  const issue = search.get("issue");
  const sessionsQ = useCodingSessions(ws);
  const all = isLive() ? (sessionsQ.data ?? []) : demoCodingSessions(D());
  const cs = all.find((c) => c.session_id === sessionId) ?? null;
  const q = S.ui.codingQ.toLowerCase();
  const found = all.filter((c) => !q || `${c.issue_key} ${c.title ?? c.issue_title}`.toLowerCase().includes(q));
  const archivedCount = found.filter((c) => c.archived).length;
  const sessions = found.filter((c) => c.archived === Boolean(S.ui.showArchivedSessions));
  const hasSel = Boolean(sessionId || search.get("new") || issue);
  const [listW, setListW] = useStoredSize("dotrix.coding.listWidth", 272, 240, 480);
  const crowded = Boolean(sessionId && search.get("panel")) && window.matchMedia("(max-width: 1799px)").matches;
  const sidebar = useSessionSidebar("coding", hasSel ? search.toString() : "", crowded);
  // One list, pinned first, then the latest; each row names its issue, so its project.
  const items = sessions
    .slice()
    .sort((a, b) => Number(b.pinned) - Number(a.pinned) || ms(b.updated_at) - ms(a.updated_at))
    .map((c) => <SessionRow key={c.session_id} cs={c} on={sessionId === c.session_id} />);
  return (
    <SessionSidebarContext value={sidebar}>
      <div className="page flush">
        <div
          className={`chat-grid ${hasSel ? "has-sel" : ""} ${sidebar.listOpen ? "list-open" : ""}`}
          style={css({ "--list-w": sidebar.hidden ? "0px" : `${listW}px` })}
        >
          <aside className="chat-side" id={sidebar.id} hidden={sidebar.hidden}>
            <Splitter dir="col" className="edge-r" label="Resize the list" size={listW} min={240} max={480} onResize={setListW} />
            <div style={{ padding: "18px 16px 8px" }} className="row">
              <h1 style={{ fontSize: "var(--fs-xl)", margin: 0, fontWeight: 600, letterSpacing: "-.015em" }}>Codes</h1>
              <span className="sp" />
              <SessionListToggle />
            </div>
            <div className="chat-new">
              <ActionButton className="btn btn-secondary" onClick={() => openCoding("new=1")}>
                <Ic n="square-pen" s={14} /> New session
              </ActionButton>
            </div>
            <div style={{ padding: "0 14px 8px" }}>
              <div className="inwrap">
                <Ic n="search" s={13} />
                <DesignInput
                  className="input search-sm"
                  style={{ width: "100%" }}
                  placeholder="Find a session"
                  value={S.ui.codingQ}
                  onChange={(e) => ((S.ui.codingQ = e.target.value), render())}
                  aria-label="Find"
                />
              </div>
            </div>
            <nav className="chat-list" aria-label="Sessions" onClick={sidebar.closeList}>
              {items.length ? (
                items
              ) : (
                <div className="faint" style={{ fontSize: 12, padding: "6px 8px" }}>
                  {q ? "No session matches." : "No sessions yet"}
                </div>
              )}
              {(archivedCount > 0 || S.ui.showArchivedSessions) && (
                <button className="linkbtn cs-archived" onClick={() => ((S.ui.showArchivedSessions = !S.ui.showArchivedSessions), render())}>
                  {S.ui.showArchivedSessions ? "Hide archived sessions" : `Show archived sessions (${archivedCount})`}
                </button>
              )}
            </nav>
          </aside>
          <section className="chat-main">
            {!isLive() && sessionId ? (
              <DemoSession key={sessionId} id={sessionId} />
            ) : sessionId ? (
              cs ? (
                <Session key={cs.session_id} cs={cs} />
              ) : sessionsQ.isError ? (
                <Pending text="The session couldn't be loaded." onRetry={() => void sessionsQ.refetch()} back={toList()} />
              ) : (
                <Pending
                  text={sessionsQ.isFetched ? "This session isn't here: it was deleted, or isn't one you can see." : "Loading the session…"}
                  loading={!sessionsQ.isFetched}
                  back={toList()}
                />
              )
            ) : (
              <NewSession key={issue ?? ""} issue0={issue} />
            )}
          </section>
        </div>
      </div>
    </SessionSidebarContext>
  );
}

function DemoSession({ id }: { id: string }) {
  const session = D().coding.find((item) => item.id === id);
  const [views, setViews] = useState<CodingView[]>([]);
  const [opened, setOpened] = useState<string | null>(null);
  const turn = session ? session.turns.length - 1 : 0;
  if (!session) return <Pending text="This sample session is no longer available." back={toList()} />;
  // Seeded diffs are excerpts; parse each file independently so a truncated hunk cannot consume the next file.
  const files = Object.entries(session.diffs ?? {}).flatMap(([path, diff]) => {
    const status = session.files?.find((file) => file.path === path)?.status;
    const mode = status === "added" ? "new file mode 100644\n" : status === "deleted" ? "deleted file mode 100644\n" : "";
    return parseDiff(`diff --git a/${path} b/${path}\n${mode}--- a/${path}\n+++ b/${path}\n${diff}`);
  });
  const entries = (session.tree ?? session.files?.map((item) => item.path) ?? []).map((path) => ({
    path,
    status: session.files?.find((item) => item.path === path)?.status ?? "unchanged",
    size: 0,
  }));
  const tree = buildTree(entries);
  const title = session.title ?? D().tasks.find((item) => item.id === session.task)?.title ?? "Coding session";
  const active = session.turns[turn];
  const labels: Record<CodingView, string> = { changes: "Changes", files: "Files", terminal: "Terminal", review: "Review" };
  return (
    <div style={{ display: "flex", height: "100%", minWidth: 0 }}>
      <div style={{ display: "flex", flexDirection: "column", flex: 1, minWidth: 0 }}>
        <SessionHeader>
          <ActionButton className="ibtn ibtn-sm cs-back" onClick={() => openCoding("")} aria-label="Back to sessions">
            <Ic n="arrow-left" s={16} />
          </ActionButton>
          <b className="trunc cs-demo-title">{title}</b>
          <span className="sp" />
          <div className="cs-views" role="group" aria-label="Session panes">
            {(Object.keys(labels) as CodingView[]).map((view) => (
              <button
                key={view}
                className={`cs-view ${views.includes(view) ? "on" : ""}`}
                aria-label={labels[view]}
                title={labels[view]}
                aria-pressed={views.includes(view)}
                onClick={() => setViews((current) => (current.includes(view) ? current.filter((item) => item !== view) : [...current, view]))}
              >
                <Ic n={{ changes: "plus-minus", files: "folder-simple", terminal: "terminal", review: "shield-check" }[view]} s={16} />
              </button>
            ))}
          </div>
        </SessionHeader>
        <div className="chat-scroll">
          <div className="chat-col">
            <p className="muted">Sample session · Sign in to work with Kai.</p>
            {session.turns.map((item, index) => (
              <div key={index}>
                <Message m={{ id: `${index}-user`, role: "user", by: session.by, at: item.at, text: item.ask }} projectId={session.project} />
                {item.summary && (
                  <Message
                    m={{ id: `${index}-agent`, role: "agent", by: "agent:coding-agent", at: item.at, text: item.summary, activity: item.events }}
                    projectId={session.project}
                  />
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
      {views.length > 0 && (
        <aside className="side-panel panes" style={{ width: 460 }} aria-label="Session panes">
          {views.map((view) => (
            <PanelFrame
              key={view}
              label={labels[view]}
              title={<b>{labels[view]}</b>}
              widthKey="dotrix.demo.panes.width"
              stacked
              onClose={() => setViews((current) => current.filter((item) => item !== view))}
              tools={<span className="badge">Recorded excerpts</span>}
            >
              {view === "changes" && <ChangeList files={files} turn={{ status: session.status, turn: turn + 1 }} loading={false} />}
              {view === "files" && (
                <>
                  <p className="faint">
                    Sample repository: {session.repo ?? "Not recorded"} · {session.branch ?? "No branch"}
                  </p>
                  {opened ? (
                    <>
                      <ActionButton className="btn btn-ghost" onClick={() => setOpened(null)}>
                        Back to the files
                      </ActionButton>
                      <p className="mono">{opened}</p>
                      {files.some((file) => file.path === opened) ? (
                        <ChangeList files={files.filter((file) => file.path === opened)} turn={{ status: session.status, turn: turn + 1 }} loading={false} />
                      ) : (
                        <p className="muted">This sample includes the file path; its contents were not recorded.</p>
                      )}
                    </>
                  ) : (
                    <FileTree nodes={tree.children} onOpen={setOpened} />
                  )}
                </>
              )}
              {view === "terminal" && (
                <>
                  <p className="faint">Recorded sample commands</p>
                  <CommandList
                    working={false}
                    entries={(session.terminal ?? []).map((command, index) => ({
                      ref: String(index),
                      command: command.cmd,
                      output: command.out ?? null,
                      failed: false,
                      at: new Date(active?.at ?? session.at).toISOString(),
                    }))}
                  />
                </>
              )}
              {view === "review" && <p className="muted">No saved Juno review for this sample session.</p>}
            </PanelFrame>
          ))}
        </aside>
      )}
    </div>
  );
}
