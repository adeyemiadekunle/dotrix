// dotrix's Codes: Kai's sessions, apart from Chat's conversations. The list holds every coding session
// you can see, grouped by project (pinned first, then the latest); one started from a conversation is marked,
// links back to it, and still shows as a card there. Stopping, archiving, or deleting a session here leaves the
// conversation alone, and the other way round.
// URL: ?session=ID (a session, with &panel=, &turn=, &file=, &line=), ?new=1 (a new session, &issue=KEY), else the list.
import { useEffect, useState, type CSSProperties } from "react";

import { useCodingSessions } from "@/lib/coding";
import { Ic } from "../core/icons";
import { useRoute } from "../core/nav";
import { isLive, live } from "../data/live";
import { S, canSee, pColor, render, visibleProjects } from "../data/store";
import { Splitter, useStoredFlag, useStoredSize } from "../ui/splitter";
import { NewSession, Pending, Session, SessionRow, openCoding } from "./Chat";

const css = (o: Record<string, string | number>) => o as CSSProperties;
const ms = (at: string | null | undefined) => (at ? new Date(at).getTime() : Date.now());
const toList = (): [string, () => void] => ["Back to sessions", () => openCoding("")];

export function Coding() {
  const { search } = useRoute();
  const ws = live.ws?.id;
  const sessionId = search.get("session");
  // With nothing picked, the main column is the new-session form, as Chat's is a new chat.
  const issue = search.get("issue");
  const sessionsQ = useCodingSessions(ws);
  const all = sessionsQ.data ?? [];
  const cs = all.find((c) => c.session_id === sessionId) ?? null;
  const q = S.ui.codingQ.toLowerCase();
  const found = all.filter((c) => !q || `${c.issue_key} ${c.title ?? c.issue_title}`.toLowerCase().includes(q));
  const archivedCount = found.filter((c) => c.archived).length;
  const sessions = found.filter((c) => c.archived === Boolean(S.ui.showArchivedSessions));
  const ps = visibleProjects().filter(canSee);
  const hasSel = Boolean(sessionId || search.get("new") || issue);
  const [listW, setListW] = useStoredSize("dotrix.coding.listWidth", 300, 220, 480);
  const [listMinSet, setListMin] = useStoredFlag("dotrix.coding.listMin");
  // While a session's side panel is open on a screen without room for all three, the list folds to its rail
  // (unless you open it again); it comes back when the panel closes.
  const [keepList, setKeepList] = useState(false);
  const crowded = Boolean(sessionId && search.get("panel")) && window.matchMedia("(max-width: 1799px)").matches;
  useEffect(() => setKeepList(false), [crowded]);
  const listMin = (listMinSet || (crowded && !keepList)) && !window.matchMedia("(max-width: 900px)").matches;
  const itemsOf = (projectId: string) =>
    sessions
      .filter((c) => c.project_id === projectId)
      .sort((a, b) => Number(b.pinned) - Number(a.pinned) || ms(b.updated_at) - ms(a.updated_at))
      .map((c) => <SessionRow key={c.session_id} cs={c} on={sessionId === c.session_id} />);
  return (
    <div className="page flush">
      <div className={`chat-grid ${hasSel ? "has-sel" : ""}`} style={css({ "--list-w": listMin ? "52px" : `${listW}px` })}>
        <aside className={`chat-side ${listMin ? "min" : ""}`}>
          {listMin ? (
            <div className="chat-rail">
              <button
                className="ibtn"
                onClick={() => (listMinSet ? setListMin(false) : setKeepList(true))}
                aria-label="Show the list"
                data-tip="Show the list"
                data-tip-pos="right"
              >
                <Ic n="panel-left-open" s={16} />
              </button>
              <button className="ibtn" onClick={() => openCoding("new=1")} aria-label="New session" data-tip="New session" data-tip-pos="right">
                <Ic n="square-pen" s={16} />
              </button>
            </div>
          ) : (
            <>
              <Splitter dir="col" className="edge-r" label="Resize the list" onDrag={(d) => setListW((w) => w + d)} />
              <div style={{ padding: "18px 16px 8px" }} className="row">
                <h1 style={{ fontSize: "var(--fs-xl)", margin: 0, fontWeight: 600, letterSpacing: "-.015em" }}>Codes</h1>
                <span className="sp" />
                <button
                  className="ibtn ibtn-sm chat-fold"
                  onClick={() => {
                    setListMin(true);
                    setKeepList(false);
                  }}
                  aria-label="Hide the list"
                  data-tip="Hide the list"
                >
                  <Ic n="panel-left-close" s={15} />
                </button>
              </div>
              <div className="chat-new">
                <button className="btn btn-secondary" onClick={() => openCoding("new=1")}>
                  <Ic n="square-pen" s={14} /> New session
                </button>
              </div>
              <div style={{ padding: "0 14px 8px" }}>
                <div className="inwrap">
                  <Ic n="search" s={13} />
                  <input
                    className="input search-sm"
                    style={{ width: "100%" }}
                    placeholder="Find a session"
                    value={S.ui.codingQ}
                    onChange={(e) => ((S.ui.codingQ = e.target.value), render())}
                    aria-label="Find"
                  />
                </div>
              </div>
              <nav className="chat-list" aria-label="Sessions">
                {ps.map((p) => {
                  const list = itemsOf(p.id);
                  if (!list.length && q) return null;
                  return (
                    <div className="chat-group" key={p.id}>
                      <div className="row" style={{ padding: "0 8px", height: 26, fontSize: 11.5, color: "var(--text-3)", fontWeight: 500 }}>
                        <span className="pdot" style={css({ "--c": pColor(p), width: 7, height: 7 })} />
                        <span className="grow trunc">{p.name}</span>
                      </div>
                      {list.length ? (
                        list
                      ) : (
                        <div className="faint" style={{ fontSize: 12, padding: "2px 8px 4px" }}>
                          No sessions yet
                        </div>
                      )}
                    </div>
                  );
                })}
                {(archivedCount > 0 || S.ui.showArchivedSessions) && (
                  <button className="linkbtn cs-archived" onClick={() => ((S.ui.showArchivedSessions = !S.ui.showArchivedSessions), render())}>
                    {S.ui.showArchivedSessions ? "Hide archived sessions" : `Show archived sessions (${archivedCount})`}
                  </button>
                )}
              </nav>
            </>
          )}
        </aside>
        <section className="chat-main">
          {!isLive() && sessionId ? (
            <Pending text="This session isn't available in the demo. Review the request in Inbox." inbox back={toList()} />
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
  );
}
