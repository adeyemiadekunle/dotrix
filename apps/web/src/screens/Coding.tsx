import { ActionButton } from "@dotrix/ui/components/action-button";
// dotrix's Codes: Kai's sessions, apart from Chat's conversations. The list holds every coding session
// you can see in one list (pinned first, then the latest); one started from a conversation is marked,
// links back to it, and still shows as a card there. Stopping, archiving, or deleting a session here leaves the
// conversation alone, and the other way round.
// URL: ?session=ID (a session, with &panel=, &turn=, &file=, &line=), ?new=1 (a new session, &issue=KEY), else the list.
import { useEffect, useRef, useState } from "react";

import { APPROVAL_MODES, modelName, type ApprovalMode } from "@/lib/agent";
import { useCodingSessions, type CodingRun, type CodingSession } from "@/lib/coding";
import { approvalModes, defaultApproval } from "../core/can";
import { Ic } from "../core/icons";
import { useRoute } from "../core/nav";
import { ago } from "../core/utils";
import { isLive, live } from "../data/live";
import { D, S, demoRuntime, render } from "../data/store";
import { Checkpoint } from "../components/AgentTrace";
import { SessionDetails } from "../components/SessionDetails";
import {
  ApprovalPick,
  ComposerModel,
  SAMPLE_COMPOSER_MODELS,
  copyText,
  LineCounts,
  Message,
  NewSession,
  Pending,
  Session,
  SessionRow,
  SessionHeader,
  STATUS,
  openCoding,
} from "./Chat";
import { ChatComposer, ChatComposerInput, ChatLayout, ChatMessageList, ChatSendButton, CodingOptions } from "../components/chat-ui";

import { buildTree, parseDiff } from "../core/kaiWork";
import { ChangeList, CommandList, FilesEmpty, FileTree } from "../components/TurnViews";
import {
  CODE_PANE_ITEMS,
  CodePaneAside,
  PaneTabs,
  PanelFrame,
  codingPaneType,
  newCodingPane,
  useActivePane,
  type CodingPaneId,
  type CodingView,
} from "../components/SidePanel";
import { SessionTabs } from "../components/SessionTabs";

const ms = (at: string | null | undefined) => (at ? new Date(at).getTime() : Date.now());
const toList = (): [string, () => void] => ["Back to sessions", () => openCoding("")];
const parseDemoPanes = (value: string | null): CodingPaneId[] =>
  (value ?? "")
    .split(",")
    .filter((v): v is CodingPaneId => /^(changes|files|terminal|review|browser)$|^(terminal|browser)-[1-9]\d{0,5}$/.test(v))
    .filter((v, i, all) => all.indexOf(v) === i);

export function Coding() {
  const { search } = useRoute();
  const ws = isLive() ? live.ws?.id : undefined;
  const sessionId = search.get("session");
  // With nothing picked, the main column is the new-session form, as Chat's is a new chat.
  const issue = search.get("issue");
  const sessionsQ = useCodingSessions(ws);
  const all = isLive() ? (sessionsQ.data ?? []) : (demoRuntime()?.codingSessions(D()) ?? []);
  const cs = all.find((c) => c.session_id === sessionId) ?? null;
  const q = S.ui.codingQ.toLowerCase();
  const ordered = all.slice().sort((a, b) => Number(b.pinned) - Number(a.pinned) || ms(b.updated_at) - ms(a.updated_at));
  const found = ordered.filter((c) => !q || `${c.issue_key} ${c.title ?? c.issue_title}`.toLowerCase().includes(q));
  const archivedCount = found.filter((c) => c.archived).length;
  const sessions = found.filter((c) => c.archived === Boolean(S.ui.showArchivedSessions));
  return (
    <div className="page flush session-page">
      <SessionTabs
        area="code"
        activeId={sessionId}
        tabs={ordered
          .filter((c) => !c.archived || c.session_id === sessionId)
          .map((c) => ({
            id: c.session_id,
            title: [c.issue_key, c.title ?? c.issue_title].filter(Boolean).join(" "),
            waiting: c.status === "awaiting_approval" || c.status === "changes_ready",
            onSelect: () => openCoding(`session=${c.session_id}`),
          }))}
        onNew={() => openCoding("new=1")}
        copyLink={() => copyText(location.href)}
        query={S.ui.codingQ}
        setQuery={(next) => ((S.ui.codingQ = next), render())}
      >
        {(close) => (
          <nav className="chat-list" aria-label="Sessions">
            {sessions.length ? (
              sessions.map((c) => <SessionRow key={c.session_id} cs={c} on={sessionId === c.session_id} onPick={close} />)
            ) : (
              <p className="session-list-empty">{q ? "No session matches." : "No sessions yet"}</p>
            )}
            {(archivedCount > 0 || S.ui.showArchivedSessions) && (
              <button className="linkbtn cs-archived" onClick={() => ((S.ui.showArchivedSessions = !S.ui.showArchivedSessions), render())}>
                {S.ui.showArchivedSessions ? "Hide archived sessions" : `Show archived sessions (${archivedCount})`}
              </button>
            )}
          </nav>
        )}
      </SessionTabs>
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
  );
}

function SampleBrowser() {
  return (
    <div className="browser">
      <form className="browser-bar" onSubmit={(event) => event.preventDefault()}>
        <ActionButton className="ibtn ibtn-sm" aria-label="Back" disabled>
          <Ic n="arrow-left" s={14} />
        </ActionButton>
        <ActionButton className="ibtn ibtn-sm" aria-label="Forward" disabled>
          <Ic n="arrow-right" s={14} />
        </ActionButton>
        <ActionButton className="ibtn ibtn-sm" aria-label="Reload" disabled>
          <Ic n="arrow-clockwise" s={14} />
        </ActionButton>
        <input
          className="input browser-address"
          aria-label="Address"
          placeholder="localhost:3000 or a web address"
          spellCheck={false}
          autoCapitalize="off"
          autoCorrect="off"
        />
      </form>
      <div className="browser-pages">
        <div className="browser-empty muted">
          <Ic n="globe" s={22} />
          <p>Sample Browser</p>
          <p className="faint">Open a live Code session in the Dotrix desktop app to browse here.</p>
        </div>
      </div>
    </div>
  );
}

function DemoSession({ id }: { id: string }) {
  const { search } = useRoute();
  const session = D().coding.find((item) => item.id === id);
  const [openViews, setOpenViews] = useState<CodingPaneId[]>(() => parseDemoPanes(search.get("panel")));
  const [activeView, setActiveView] = useActivePane(openViews);
  const [expanded, setExpanded] = useState(false);
  const [draft, setDraft] = useState("");
  const [mode, setMode] = useState<"build" | "plan">("build");
  const approvals = APPROVAL_MODES.filter(([v]) => approvalModes().includes(v));
  const [approval, setApproval] = useState<ApprovalMode>(defaultApproval());
  const modelOptions = SAMPLE_COMPOSER_MODELS.map((item): [string, string] => [item, modelName(item)]);
  const [chosenModel, setModel] = useState<string>(SAMPLE_COMPOSER_MODELS[0] ?? "");
  const draftRef = useRef<HTMLTextAreaElement>(null);
  const closeView = (view: CodingPaneId) => setOpenViews((current) => current.filter((item) => item !== view));
  const [opened, setOpened] = useState<string | null>(null);
  const [detailsPop, setDetailsPop] = useState(false);
  useEffect(() => {
    setDetailsPop(false);
  }, [id]);
  useEffect(() => {
    if (!detailsPop) return;
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setDetailsPop(false);
    const away = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      if (!target.closest(".cs-details-pop, [data-details]")) setDetailsPop(false);
    };
    document.addEventListener("keydown", esc);
    document.addEventListener("mousedown", away);
    return () => {
      document.removeEventListener("keydown", esc);
      document.removeEventListener("mousedown", away);
    };
  }, [detailsPop]);
  const turn = session ? session.turns.length - 1 : 0;
  if (!session) return <Pending text="This sample session is no longer available." back={toList()} />;
  const [statusLabel, statusColor] = STATUS[session.status];
  // Seeded diffs are excerpts; parse each file independently so a truncated hunk cannot consume the next file.
  const files = Object.entries(session.diffs ?? {}).flatMap(([path, diff]) => {
    const status = session.files?.find((file) => file.path === path)?.status;
    const mode = status === "added" ? "new file mode 100644\n" : status === "deleted" ? "deleted file mode 100644\n" : "";
    return parseDiff(`diff --git a/${path} b/${path}\n${mode}--- a/${path}\n+++ b/${path}\n${diff}`);
  });
  const totalAdded = files.reduce((sum, file) => sum + file.added, 0);
  const totalRemoved = files.reduce((sum, file) => sum + file.removed, 0);
  const entries = (session.tree ?? session.files?.map((item) => item.path) ?? []).map((path) => ({
    path,
    status: session.files?.find((item) => item.path === path)?.status ?? "unchanged",
    size: 0,
  }));
  const tree = buildTree(entries);
  const title = session.title ?? D().tasks.find((item) => item.id === session.task)?.title ?? "Coding session";
  const active = session.turns[turn];
  const labels: Record<CodingView, string> = { changes: "Changes", files: "Files", terminal: "Terminal", review: "Review", browser: "Browser" };
  const showPanel = openViews.length > 0;
  const activeType = activeView ? codingPaneType(activeView) : null;
  const openChanges = () => {
    setDetailsPop(false);
    setOpenViews((current) => (current.includes("changes") ? current : ["changes", ...current]));
    setActiveView("changes");
  };
  const openPath = (path: string) => {
    setDetailsPop(false);
    setOpened(path);
    setOpenViews((current) => (current.includes("files") ? current : [...current, "files"]));
    setActiveView("files");
  };
  const detailsOn = detailsPop;
  const toggleDetails = () => setDetailsPop((open) => !open);
  const demoProject = D().projects.find((item) => item.id === session.project);
  const demoIssue = D().tasks.find((item) => item.id === session.task || item.key === session.task);
  const demoCs: CodingSession = (demoRuntime()?.codingSessions(D()) ?? []).find((item) => item.session_id === session.id) ?? {
    session_id: session.id,
    project_id: session.project,
    project_key: demoProject?.key ?? "WEB",
    project_name: demoProject?.name ?? "Workspace",
    issue_key: demoIssue?.key ?? session.task,
    issue_title: demoIssue?.title ?? title,
    agent: session.tool,
    status: session.status,
    turns: session.turns.length,
    branch: session.branch ?? null,
    pr_number: session.pr?.number ?? null,
    pr_url: session.pr?.url ?? null,
    pr_state: session.pr?.state ?? null,
    state: session.state ?? "idle",
    title,
    pinned: Boolean(session.pinned),
    archived: Boolean(session.archived),
    location: "cloud",
    sandbox: "warm",
    started_at: new Date(session.at).toISOString(),
    updated_at: new Date(session.at).toISOString(),
  };
  if (!demoCs.sandbox) demoCs.sandbox = "warm";
  const demoTurns: CodingRun[] = session.turns.map((t, index) => {
    const demoBgEvents =
      index === session.turns.length - 1
        ? (session.tasks ?? []).map((bg) => ({
            kind: `background-${bg.status === "running" ? "running" : bg.status === "done" ? "done" : bg.status === "failed" ? "failed" : "stopped"}`,
            text: `${bg.name} · ${bg.cmd}`,
            ref: `command:${bg.id}`,
            at: new Date(t.at).toISOString(),
          }))
        : [];
    return {
      id: `${session.id}-turn-${index}`,
      project_id: demoCs.project_id,
      issue_key: demoCs.issue_key,
      agent: session.tool,
      model: chosenModel,
      session_id: session.id,
      turn: index + 1,
      origin: index === 0 ? "start" : "follow_up",
      status: session.status,
      work_mode: mode,
      brief: t.ask,
      note: null,
      repo_full_name: session.repo ?? "",
      base_branch: session.base?.branch ?? "main",
      base_sha: session.base?.sha ?? null,
      branch: session.branch ?? null,
      commit_sha: session.commits?.[index]?.sha ?? session.commits?.[0]?.sha ?? null,
      pr_number: session.pr?.number ?? null,
      pr_url: session.pr?.url ?? null,
      pr_state: session.pr?.state ?? null,
      files_changed: index === session.turns.length - 1 ? (session.files ?? []).map((f) => ({ ...f })) : [],
      events: demoBgEvents,
      event_count: (t.events?.length ?? 0) + demoBgEvents.length,
      summary: t.summary ?? null,
      error: null,
      input_tokens: null,
      output_tokens: null,
      cost_usd: null,
      requested_by_id: session.by,
      decided_by_id: null,
      decision_reason: null,
      review_run_id: null,
      review_thread_id: null,
      created_at: new Date(t.at).toISOString(),
      decided_at: null,
      started_at: new Date(t.at).toISOString(),
      finished_at: new Date(t.at).toISOString(),
      can_decide: false,
      can_stop: false,
      approval_mode: approval,
      can_recover: false,
      can_revert: false,
      location: "cloud",
      accepts_steering: false,
    };
  });
  const details = (
    <SessionDetails
      cs={demoCs}
      turns={demoTurns}
      onOpenFile={openPath}
      onOpenChanges={openChanges}
      onShot={() => {}}
      shotSrc={() => ""}
      onClose={() => setDetailsPop(false)}
    />
  );
  return (
    <div className="conv">
      <div className="conv-main">
        <SessionHeader>
          <ActionButton className="ibtn ibtn-sm cs-back" onClick={() => openCoding("")} aria-label="Back to sessions">
            <Ic n="arrow-left" s={16} />
          </ActionButton>
          <b className="trunc cs-demo-title">{title}</b>
          <span className={`badge ${statusColor}`}>{statusLabel}</span>
          <span className="sp" />
          {files.length > 0 && (
            <LineCounts files={files.map((file) => ({ added: file.added, removed: file.removed }))} onClick={openChanges} tip="Open changes" />
          )}
          <ActionButton
            className={`cs-view ${detailsOn ? "on" : ""}`}
            data-details
            onClick={toggleDetails}
            aria-pressed={detailsOn}
            aria-label="Session details"
            data-tip={detailsOn ? undefined : "Details"}
          >
            <Ic n="list-bullets" s={16} />
          </ActionButton>
          {/* Last in the bar, where the session meets the panes: shows them (Changes first) or hides them all. */}
          <button
            className={`cs-view cs-pane-toggle ${showPanel ? "on" : ""}`}
            onClick={() => setOpenViews(showPanel ? [] : ["changes"])}
            aria-pressed={showPanel}
            aria-label={showPanel ? "Hide the panes" : "Show the panes"}
            data-tip={showPanel ? "Hide panes" : "Show panes"}
          >
            <Ic n="panel-right" s={16} />
          </button>
        </SessionHeader>
        {detailsPop && (
          <div className="pop cs-details-pop" role="dialog" aria-label="Session details">
            {details}
          </div>
        )}
        <ChatLayout
          composer={
            <div className="chat-input">
              <ChatComposer
                value={draft}
                input={
                  <ChatComposerInput
                    textareaRef={draftRef}
                    value={draft}
                    onChange={(event) => setDraft(event.currentTarget.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) event.preventDefault();
                    }}
                    label="Follow-up"
                    placeholder="Draft a follow-up"
                  />
                }
                footerActions={
                  <div className="cmp-footer-left">
                    <CodingOptions mode={mode} setMode={setMode} local={false} placement="above" focusInput={() => draftRef.current?.focus()} />
                    <span className="cmp-status-badge accent" aria-label={`Coding mode: ${mode === "plan" ? "Plan" : "Build"}`} data-tip="Mode">
                      <Ic n={mode === "plan" ? "list-checks" : "hammer"} s={12} />
                      <span>{mode === "plan" ? "Plan" : "Build"}</span>
                    </span>
                    {approvals.length > 1 && <ApprovalPick value={approval} onChange={setApproval} options={approvals} />}
                  </div>
                }
                sendActions={<ComposerModel model={chosenModel} models={modelOptions} onChange={setModel} empty="Sample model" />}
                sendButton={<ChatSendButton isDisabled />}
              />
            </div>
          }
        >
          <ChatMessageList>
            <div className="chat-col">
              <p className="muted">
                Sample session · <a href="/login">Sign in to work with Kai.</a>
              </p>
              {session.turns.map((item, index) => (
                <div key={index}>
                  <Message m={{ id: `${index}-user`, role: "user", by: session.by, at: item.at, text: item.ask }} projectId={session.project} />
                  {item.summary && (
                    <Message
                      m={{ id: `${index}-agent`, role: "agent", by: "agent:coding-agent", at: item.at, text: item.summary, activity: item.events }}
                      projectId={session.project}
                    >
                      <div className="kt-actions">
                        <ActionButton className="ibtn ibtn-xs" onClick={() => copyText(item.summary ?? "")} aria-label="Copy Kai's reply" data-tip="Copy">
                          <Ic n="copy" s={13} />
                        </ActionButton>
                        <span className="faint">{ago(item.at)}</span>
                        {index === session.turns.length - 1 && files.length > 0 && (
                          <button className="kt-lines" onClick={openChanges} data-tip="Open these changes">
                            <Ic n="git-compare" s={12} />
                            {files.length} file{files.length > 1 ? "s" : ""}
                            <span className="plus">+{totalAdded}</span>
                            <span className="minus">−{totalRemoved}</span>
                          </button>
                        )}
                      </div>
                    </Message>
                  )}
                </div>
              ))}
              {session.commits?.map((commit, index) => (
                <Checkpoint
                  key={commit.sha}
                  label={
                    <span>
                      Turn {index + 1} · <span className="mono">{commit.sha.slice(0, 7)}</span>
                      {session.branch ? <span className="faint"> on {session.branch}</span> : null}
                    </span>
                  }
                />
              ))}
              {session.status === "awaiting_approval" && (
                <div className="change">
                  <div className="change-h">
                    <Ic n="shield-check" s={14} />
                    <b style={{ fontWeight: 500 }}>Waiting for someone who may approve agent changes</b>
                  </div>
                  <div className="change-f">
                    <span className="faint" style={{ fontSize: 12 }}>
                      Sample session · <a href="/login">Sign in</a> to approve coding turns.
                    </span>
                  </div>
                </div>
              )}
            </div>
          </ChatMessageList>
        </ChatLayout>
      </div>
      {showPanel && activeView && (
        <CodePaneAside expanded={expanded}>
          <PaneTabs
            items={CODE_PANE_ITEMS}
            open={openViews}
            active={activeView}
            idPrefix="demo-panes"
            onSelect={setActiveView}
            onClose={closeView}
            onAdd={(view) => {
              const id = newCodingPane(view, openViews);
              if (!openViews.includes(id)) setOpenViews([...openViews, id]);
              setActiveView(id);
            }}
            onCloseAll={() => setOpenViews([])}
            expanded={expanded}
            onExpand={() => setExpanded((current) => !current)}
          >
            {openViews
              .filter((id) => codingPaneType(id) === "browser")
              .map((id) => (
                <div
                  key={id}
                  className="ptabs-panel"
                  data-inactive={id !== activeView || undefined}
                  inert={id !== activeView}
                  role="tabpanel"
                  id={`demo-panes-panel-${id}`}
                  aria-labelledby={`demo-panes-tab-${id}`}
                >
                  <PanelFrame label="Browser" title={null} widthKey="dotrix.demo.panes.width" tabbed onClose={() => closeView(id)}>
                    <SampleBrowser />
                  </PanelFrame>
                </div>
              ))}
            {activeType && activeType !== "browser" && (
              <div className="ptabs-panel" role="tabpanel" id={`demo-panes-panel-${activeView}`} aria-labelledby={`demo-panes-tab-${activeView}`}>
                <PanelFrame
                  label={labels[activeType]}
                  title={activeType === "terminal" ? <span className="faint">Recorded sample commands</span> : null}
                  widthKey="dotrix.demo.panes.width"
                  tabbed
                  onClose={() => closeView(activeView)}
                >
                  <div className={`side-panel-body ${activeType === "files" ? "is-files" : ""}`}>
                    {activeType === "changes" && <ChangeList files={files} turn={{ status: session.status, turn: turn + 1 }} loading={false} />}
                    {activeType === "files" && (
                      <div className="kp-files" data-open={Boolean(opened)}>
                        <div className="kp-files-tree">
                          <p className="faint kp-files-repo">
                            Sample repository: {session.repo ?? "Not recorded"} · {session.branch ?? "No branch"}
                          </p>
                          <FileTree nodes={tree.children} onOpen={setOpened} activePath={opened} />
                        </div>
                        <div className="kp-files-viewer">
                          {opened ? (
                            <>
                              <div className="kp-file-bar">
                                <ActionButton className="ibtn ibtn-sm kp-files-back" onClick={() => setOpened(null)} aria-label="Back to the files">
                                  <Ic n="arrow-left" s={13} />
                                </ActionButton>
                                <Ic n="file-code" s={14} cls="kp-file-icon" />
                                <span className="kp-crumbs mono" title={opened}>
                                  {opened}
                                </span>
                              </div>
                              {files.some((file) => file.path === opened) ? (
                                <ChangeList
                                  files={files.filter((file) => file.path === opened)}
                                  turn={{ status: session.status, turn: turn + 1 }}
                                  loading={false}
                                />
                              ) : (
                                <p className="muted">This sample includes the file path; its contents were not recorded.</p>
                              )}
                            </>
                          ) : (
                            <FilesEmpty />
                          )}
                        </div>
                      </div>
                    )}
                    {activeType === "terminal" && (
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
                    )}
                    {activeType === "review" && <p className="muted">No saved Juno review for this sample session.</p>}
                  </div>
                </PanelFrame>
              </div>
            )}
          </PaneTabs>
        </CodePaneAside>
      )}
    </div>
  );
}
