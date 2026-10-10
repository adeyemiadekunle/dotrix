import { Input } from "@dotrix/ui/components/input";
import { Skeleton } from "@dotrix/ui/components/skeleton";
import { ChevronDownIcon, ChevronRightIcon, ListTodoIcon, SearchIcon } from "lucide-react";
import { Suspense, useMemo, useState } from "react";

import { PageHeader } from "@/components/app-shell";
import { STATUSES, STATUS_META, StatusIcon } from "@/components/issues/meta";
import { WorkspaceIssueRow } from "@/components/issues/workspace-issue-row";
import { EmptyState, NotFound } from "@/components/states";
import { useMembers, useWorkspaceIssues } from "@/lib/issues";
import { useCurrentWorkspace, useProjects } from "@/lib/queries";
import { useSearchParam } from "@/lib/url-state";

/** Every issue in the projects you can see, by status; filter by project, assignee, or words. */
function Tasks() {
  const { workspace, notFound } = useCurrentWorkspace();
  const canSee = Boolean(workspace && workspace.role !== "guest");
  const [project, setProject] = useSearchParam("project");
  const [assignee, setAssignee] = useSearchParam("assignee");
  const issues = useWorkspaceIssues(canSee ? workspace?.id : undefined, assignee ? { assignee } : {});
  const projects = useProjects(workspace?.id);
  const members = useMembers(workspace?.id);
  const [query, setQuery] = useState("");
  const [toggled, setToggled] = useState<Record<string, boolean>>({});

  const groups = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const shown = (issues.data ?? []).filter(
      (i) => (!project || i.project_key === project) && (!needle || i.title.toLowerCase().includes(needle) || i.key.toLowerCase().includes(needle)),
    );
    return STATUSES.map((status) => ({ status, issues: shown.filter((i) => i.status === status) }));
  }, [issues.data, project, query]);
  const total = groups.reduce((n, g) => n + g.issues.length, 0);

  if (notFound) return <NotFound what="workspace" />;
  return (
    <>
      <PageHeader title="Tasks" parent={workspace?.name} />
      <div className="flex w-full max-w-6xl flex-col gap-4 p-4 md:p-6">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative w-full max-w-60">
            <SearchIcon className="text-muted-foreground absolute top-1/2 left-2.5 size-4 -translate-y-1/2" />
            <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search issues" aria-label="Search issues" className="h-8 pl-8" />
          </div>
          <select
            aria-label="Project"
            value={project ?? ""}
            onChange={(e) => setProject(e.target.value || null)}
            className="bg-background h-8 rounded-md border px-2 text-sm"
          >
            <option value="">All projects</option>
            {projects.data?.map((p) => (
              <option key={p.id} value={p.key}>
                {p.name}
              </option>
            ))}
          </select>
          <select
            aria-label="Assignee"
            value={assignee ?? ""}
            onChange={(e) => setAssignee(e.target.value || null)}
            className="bg-background h-8 rounded-md border px-2 text-sm"
          >
            <option value="">Anyone</option>
            <option value="me">Me</option>
            <option value="none">No one</option>
            {members.data?.map((m) => (
              <option key={m.user_id} value={m.user_id}>
                {m.display_name}
              </option>
            ))}
          </select>
          <span className="text-muted-foreground text-xs">{issues.data ? `${total} issues` : ""}</span>
        </div>

        {issues.isLoading && <Skeleton className="h-64" />}
        {issues.data && total === 0 && (
          <EmptyState icon={ListTodoIcon} title="No issues here" description="Issues from every project you can see show up here." />
        )}
        {workspace &&
          total > 0 &&
          groups.map(({ status, issues: list }) => {
            if (list.length === 0) return null;
            const collapsed = toggled[status] ?? status === "done";
            return (
              <section key={status} className="bg-card rounded-xl border">
                <button
                  type="button"
                  onClick={() => setToggled((t) => ({ ...t, [status]: !collapsed }))}
                  aria-expanded={!collapsed}
                  className="flex h-11 w-full items-center gap-2 px-4 text-sm font-semibold"
                >
                  {collapsed ? <ChevronRightIcon className="size-4" /> : <ChevronDownIcon className="size-4" />}
                  <StatusIcon status={status} />
                  {STATUS_META[status].label}
                  <span className="text-muted-foreground font-normal">{list.length}</span>
                </button>
                {!collapsed && (
                  <div className="border-t">
                    {list.map((issue) => (
                      <WorkspaceIssueRow key={issue.key} issue={issue} workspaceSlug={workspace.slug} />
                    ))}
                  </div>
                )}
              </section>
            );
          })}
      </div>
    </>
  );
}

export default function TasksPage() {
  return (
    <Suspense>
      <Tasks />
    </Suspense>
  );
}
