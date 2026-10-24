// What the connected repository's knowledge covers: path coverage and domain coverage, separately.
// Every required domain shows its evidence or a named gap, and what isn't read says why.
import { useState, type ReactNode } from "react";

import {
  useExplainRepository,
  useRepoCoverage,
  useRepoDependencies,
  useRepoPages,
  useRepoPaths,
  useTakeInventory,
  type DomainCoverage,
  type PathStatus,
  type RepoPage,
} from "@/lib/repo-knowledge";
import { allowed } from "../core/can";
import { Ic } from "../core/icons";
import { ago } from "../core/utils";
import { live } from "../data/live";
import { proj } from "../data/store";
import { go } from "../core/nav";
import { Empty } from "../ui/helpers";

const STATES: Record<DomainCoverage["status"], [string, string]> = {
  gap: ["Gap", "red"],
  pending: ["Not read yet", "amber"],
  partial: ["Partly read", "amber"],
  covered: ["Read", "green"],
};
const STATUS_WORDS: Record<PathStatus, string> = {
  pending: "To read",
  analyzed: "Read",
  excluded: "Not read",
  unsupported: "No reader yet",
  inaccessible: "Not here",
};

const STALE_WORDS: Record<RepoPage["stale"][number]["why"], string> = {
  changed: "changed since read",
  removed: "removed",
  unread: "not read yet",
};

export function Coverage({ pid, lead }: { pid: string; lead?: ReactNode }) {
  const scope = live.ws ? { workspaceId: live.ws.id, projectId: pid } : undefined;
  const coverage = useRepoCoverage(scope);
  const take = useTakeInventory(scope);
  const [picked, setPicked] = useState<{ status?: PathStatus; domain?: string } | null>(null);
  const paths = useRepoPaths(scope, picked ?? {}, picked !== null);
  const c = coverage.data;
  const pages = useRepoPages(scope).data?.pages ?? [];
  const stale = pages.filter((p) => p.stale.length);
  const [showDeps, setShowDeps] = useState(false);
  const deps = useRepoDependencies(scope, showDeps).data;
  const canTake = allowed("knowledge:write");
  const canExplain = canTake; // (everyone who edits documents may chat)
  const explain = useExplainRepository(scope, (thread) => go("chat", {}, { search: `thread=${thread}&project=${proj(pid)?.key ?? ""}` }));
  return (
    <>
      <div className="toolbar">
        {lead}
        <span className="sp" />
        {canTake && (
          <button className="btn btn-sm btn-secondary" disabled={take.isPending} onClick={() => take.mutate()}>
            <Ic n="refresh-cw" s={12} />
            Take inventory now
          </button>
        )}
        {canExplain && c?.snapshot && stale.length > 0 && (
          <button className="btn btn-sm btn-secondary" disabled={explain.isPending} onClick={() => explain.mutate({ refresh: true })}>
            <Ic n="refresh-cw" s={12} />
            Refresh {stale.length} stale {stale.length === 1 ? "page" : "pages"}
          </button>
        )}
        {canExplain && c?.snapshot && !c.discovery_complete && (
          <button className="btn btn-sm btn-primary" disabled={explain.isPending} onClick={() => explain.mutate({})}>
            <Ic n="book-open" s={12} />
            Explain the repository
          </button>
        )}
      </div>
      <div className="page wide" style={{ paddingTop: 16 }}>
        {!c?.snapshot ? (
          <Empty
            icon="git-branch"
            title="No inventory yet"
            text="Connect the project's GitHub repository (project settings → Repository). Every tracked file is then listed and classified after each push, without running anything."
          />
        ) : (
          <>
            <div className="row muted" style={{ gap: 10, flexWrap: "wrap", fontSize: 12.5, marginBottom: 12 }}>
              <span>
                <Ic n="git-commit" s={12} /> {c.snapshot.repo_full_name} @ <code>{c.snapshot.commit_sha.slice(0, 7)}</code>
              </span>
              <span>{c.snapshot.path_count} paths</span>
              <span>taken {ago(new Date(c.snapshot.created_at).getTime())}</span>
              <span className="sp" />
              {Object.entries(c.statuses ?? {}).map(([s, n]) => (
                <button key={s} className="badge" onClick={() => setPicked({ status: s as PathStatus })}>
                  {STATUS_WORDS[s as PathStatus]} {n}
                </button>
              ))}
            </div>
            <p className="faint" style={{ fontSize: 12, margin: "0 0 12px" }}>
              {c.discovery_complete
                ? "Every path in scope has been read or is listed with why not. Gaps below can remain: the code alone can't say every requirement."
                : "Listing is complete; reading isn't. A read file isn't proof its meaning was understood."}
            </p>
            <div className="panel" role="table" aria-label="Domain coverage">
              {(c.domains ?? []).map((d) => (
                <div key={d.domain} className="row" role="row" style={{ padding: "8px 14px", gap: 10, borderTop: "1px solid var(--border)" }}>
                  <div className="grow" role="cell">
                    <b style={{ fontWeight: 500 }}>{d.title.split(":")[0]}</b>
                    <div className="muted" style={{ fontSize: 12 }}>
                      {d.gap ?? d.title.split(": ")[1]}
                    </div>
                  </div>
                  <span className="faint" role="cell" style={{ fontSize: 12 }}>
                    {d.analyzed}/{d.paths} read{d.excluded ? ` · ${d.excluded} not read` : ""}
                  </span>
                  <span className={`badge ${STATES[d.status][1]}`} role="cell">
                    {STATES[d.status][0]}
                  </span>
                  <button className="btn btn-sm btn-ghost" disabled={!d.paths && !d.excluded} onClick={() => setPicked({ domain: d.domain })}>
                    Paths
                  </button>
                </div>
              ))}
            </div>
            {pages.length > 0 && (
              <div className="panel" style={{ marginTop: 12 }} aria-label="Wiki pages">
                {pages.map((p) => (
                  <div key={p.path} className="row" style={{ padding: "8px 14px", gap: 10, borderTop: "1px solid var(--border)" }}>
                    <div className="grow">
                      <code>{p.path}</code>
                      <div className="muted" style={{ fontSize: 12 }}>
                        {p.stale.length
                          ? p.stale.map((s) => `${s.path} (${STALE_WORDS[s.why]})`).join(", ")
                          : `${p.citations} citations, all read at this commit`}
                      </div>
                    </div>
                    <span className={`badge ${p.stale.length ? "amber" : "green"}`}>{p.stale.length ? "Stale" : "Fresh"}</span>
                  </div>
                ))}
              </div>
            )}
            <div className="panel" style={{ marginTop: 12, padding: "8px 14px" }} aria-label="Dependencies">
              <div className="row">
                <b style={{ fontWeight: 500 }}>Dependencies</b>
                <span className="muted" style={{ fontSize: 12 }}>
                  {deps
                    ? `${deps.dependencies.length} direct, from ${new Set(deps.dependencies.map((d) => d.manifest)).size} manifests`
                    : "From manifests and lockfiles"}
                </span>
                <span className="sp" />
                <button className="btn btn-sm btn-ghost" onClick={() => setShowDeps(!showDeps)}>
                  {showDeps ? "Hide" : "Show"}
                </button>
              </div>
              {showDeps &&
                deps?.dependencies.slice(0, 200).map((d) => (
                  <div key={`${d.manifest}:${d.name}:${d.scope}`} className="row" style={{ gap: 8, fontSize: 12.5, padding: "3px 0" }}>
                    <code className="grow trunc">{d.name}</code>
                    <span className="faint">{d.declared}</span>
                    <span>{d.locked ?? "not locked"}</span>
                    <span className="badge">{d.scope}</span>
                    <span className="faint trunc" style={{ maxWidth: 220 }}>
                      {d.manifest}
                    </span>
                  </div>
                ))}
              {showDeps &&
                deps?.unread.map((u) => (
                  <div key={u.path} className="faint" style={{ fontSize: 12 }}>
                    {u.path}: {u.reason}
                  </div>
                ))}
            </div>
            {picked && (
              <div className="panel" style={{ marginTop: 12, padding: "8px 14px" }} aria-label="Paths">
                <div className="row" style={{ marginBottom: 6 }}>
                  <b style={{ fontWeight: 500 }}>
                    {picked.domain ? (c.domains ?? []).find((d) => d.domain === picked.domain)?.title.split(":")[0] : STATUS_WORDS[picked.status!]}
                  </b>
                  <span className="sp" />
                  <button className="ibtn ibtn-sm" onClick={() => setPicked(null)} aria-label="Close">
                    <Ic n="x" s={13} />
                  </button>
                </div>
                {(paths.data?.paths ?? []).map((p) => (
                  <div key={p.path} className="row" style={{ gap: 8, fontSize: 12.5, padding: "3px 0" }}>
                    <code className="grow trunc">{p.path}</code>
                    <span className="faint">{p.reason ?? STATUS_WORDS[p.status]}</span>
                  </div>
                ))}
                {paths.data?.next && (
                  <div className="faint" style={{ fontSize: 12 }}>
                    The first 200 are shown.
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </>
  );
}
