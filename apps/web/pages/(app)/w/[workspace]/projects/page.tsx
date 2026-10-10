import { Button } from "@dotrix/ui/components/button";
import { Input } from "@dotrix/ui/components/input";
import { Skeleton } from "@dotrix/ui/components/skeleton";
import { cn } from "@dotrix/ui/lib/utils";
import { CalendarIcon, FolderPlusIcon, LockIcon, PlusIcon, SearchIcon, StarIcon } from "lucide-react";
import { Link } from "@/lib/navigation";
import { Suspense, useMemo, useState } from "react";

import { PageHeader } from "@/components/app-shell";
import { today } from "@/components/issues/workspace-issue-row";
import { HealthBadge, formatDay } from "@/components/project-health";
import { ProjectTile } from "@/components/project-tile";
import { UserAvatar } from "@/components/user-avatar";
import { EmptyState, NotFound } from "@/components/states";
import { useMembers, useWorkspaceIssues } from "@/lib/issues";
import { PROJECT_SOURCE_LABELS, ROLE_LABELS, canManageProjects, withArticle } from "@/lib/labels";
import { memberAvatarSrc } from "@/lib/profile";
import { useCurrentWorkspace, useProjects } from "@/lib/queries";
import { starredFirst, useStarredProjects, useToggleStar } from "@/lib/stars";
import { useSearchParam } from "@/lib/url-state";

type Sort = "active" | "name" | "progress";

function ProjectsPage() {
  const { workspace, notFound } = useCurrentWorkspace();
  const projects = useProjects(workspace?.id);
  const starred = useStarredProjects(workspace?.id);
  const toggleStar = useToggleStar(workspace?.id);
  const members = useMembers(workspace && workspace.role !== "guest" ? workspace.id : undefined);
  const issues = useWorkspaceIssues(workspace && workspace.role !== "guest" ? workspace.id : undefined, {});
  const [query, setQuery] = useState("");
  const [sortParam, setSort] = useSearchParam("sort");
  const [view, setView] = useSearchParam("view");
  const sort: Sort = sortParam === "name" || sortParam === "progress" ? sortParam : "active";

  const stats = useMemo(() => {
    const byProject = new Map<string, { total: number; done: number; overdue: number; lastActive: string; people: Set<string> }>();
    for (const issue of issues.data ?? []) {
      if (issue.type === "epic") continue;
      const s = byProject.get(issue.project_id) ?? { total: 0, done: 0, overdue: 0, lastActive: "", people: new Set() };
      s.total += 1;
      if (issue.status !== "done" && issue.assignee_user_id) s.people.add(issue.assignee_user_id);
      if (issue.status === "done") s.done += 1;
      else if (issue.due && issue.due < today()) s.overdue += 1;
      if (issue.updated_at > s.lastActive) s.lastActive = issue.updated_at;
      byProject.set(issue.project_id, s);
    }
    return byProject;
  }, [issues.data]);

  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const list = (projects.data ?? []).filter((p) => !needle || p.name.toLowerCase().includes(needle) || p.key.toLowerCase().includes(needle));
    const percent = (id: string) => {
      const s = stats.get(id);
      return s?.total ? s.done / s.total : 0;
    };
    const active = (p: (typeof list)[number]) => [stats.get(p.id)?.lastActive ?? "", p.updated_at].sort().at(-1)!;
    const sorted =
      sort === "name"
        ? [...list].sort((a, b) => a.name.localeCompare(b.name))
        : sort === "progress"
          ? [...list].sort((a, b) => percent(b.id) - percent(a.id))
          : [...list].sort((a, b) => active(b).localeCompare(active(a)));
    return starredFirst(sorted, starred.data); // your starred ones first, each group sorted
  }, [projects.data, query, sort, stats, starred.data]);

  if (notFound) return <NotFound what="workspace" />;
  const canCreate = canManageProjects(workspace?.role);
  const asList = view === "list";

  return (
    <>
      <PageHeader
        title="Projects"
        parent={workspace?.name}
        actions={
          canCreate && (
            <Button size="sm" asChild>
              <Link href={`/w/${workspace!.slug}/projects/new`}>
                <PlusIcon />
                New project
              </Link>
            </Button>
          )
        }
      />
      <div className="flex w-full max-w-6xl flex-col gap-4 p-4 md:p-6">
        {workspace && (
          <p className="text-muted-foreground text-sm">
            {workspace.kind === "personal"
              ? "Your personal workspace: just you. Create an organisation to work with others."
              : `You're ${withArticle(ROLE_LABELS[workspace.role].toLowerCase())} in ${workspace.name}.`}
          </p>
        )}
        {(projects.data?.length ?? 0) > 0 && (
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative w-full max-w-60">
              <SearchIcon className="text-muted-foreground absolute top-1/2 left-2.5 size-4 -translate-y-1/2" />
              <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search projects" aria-label="Search projects" className="h-8 pl-8" />
            </div>
            <select
              aria-label="Sort"
              value={sort}
              onChange={(e) => setSort(e.target.value === "active" ? null : e.target.value)}
              className="bg-background h-8 rounded-md border px-2 text-sm"
            >
              <option value="active">Recently active</option>
              <option value="name">Name</option>
              <option value="progress">Most done</option>
            </select>
            <div role="group" aria-label="Layout" className="bg-muted ml-auto flex gap-0.5 rounded-lg p-0.5 text-xs font-medium">
              {[
                ["grid", "Grid"],
                ["list", "List"],
              ].map(([id, label]) => {
                const on = (id === "list") === asList;
                return (
                  <button
                    key={id}
                    type="button"
                    aria-pressed={on}
                    onClick={() => setView(id === "list" ? "list" : null)}
                    className={cn("rounded-md px-2.5 py-1", on ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground")}
                  >
                    {label}
                  </button>
                );
              })}
            </div>
          </div>
        )}
        {projects.isLoading && (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {Array.from({ length: 3 }, (_, i) => (
              <Skeleton key={i} className="h-36" />
            ))}
          </div>
        )}
        {projects.data?.length === 0 && (
          <EmptyState
            icon={FolderPlusIcon}
            title="Start your first project"
            description={
              canCreate
                ? "Link its repo, add its documents, and the agents take it from there."
                : "An owner or admin creates projects. Once there is one, it appears here."
            }
            action={
              canCreate && (
                <Button asChild>
                  <Link href={`/w/${workspace!.slug}/projects/new`}>
                    <PlusIcon />
                    New project
                  </Link>
                </Button>
              )
            }
          />
        )}
        {workspace && shown.length > 0 && (
          <div className={asList ? "bg-card flex flex-col rounded-xl border" : "grid gap-4 sm:grid-cols-2 xl:grid-cols-3"}>
            {shown.map((project) => {
              const s = stats.get(project.id) ?? { total: 0, done: 0, overdue: 0, lastActive: "", people: new Set<string>() };
              const percent = s.total ? Math.round((s.done / s.total) * 100) : 0;
              const restricted = project.access === "restricted";
              const isStarred = starred.data?.includes(project.id) ?? false;
              const late = project.target_date && project.target_date < today() && percent < 100;
              const people = [...s.people].map((id) => members.data?.find((m) => m.user_id === id)).filter((m) => m !== undefined);
              return (
                // The whole card opens the project (a stretched link), with the star button above it.
                <div
                  key={project.id}
                  className={cn(
                    "hover:border-foreground/20 relative flex flex-col gap-3 transition-colors",
                    asList ? "border-b px-4 py-3 last:border-b-0 hover:bg-muted/40" : "bg-card rounded-xl border p-4",
                  )}
                >
                  <span className="flex items-center gap-2">
                    <ProjectTile projectKey={project.key} />
                    <Link href={`/w/${workspace.slug}/p/${project.key}`} className="min-w-0 truncate font-semibold after:absolute after:inset-0">
                      {project.name}
                    </Link>
                    {restricted && <LockIcon className="text-muted-foreground size-3.5 shrink-0" aria-label="Only people added" />}
                    {project.health && <HealthBadge health={project.health} />}
                    <span className="text-muted-foreground ml-auto font-mono text-xs">{project.key}</span>
                    <button
                      type="button"
                      onClick={() => toggleStar.mutate({ projectId: project.id, starred: !isStarred })}
                      aria-pressed={isStarred}
                      aria-label={isStarred ? `Unstar ${project.name}` : `Star ${project.name}`}
                      title={isStarred ? "Unstar" : "Star: show it first"}
                      className="text-muted-foreground hover:text-foreground relative z-10 -m-1 rounded p-1"
                    >
                      <StarIcon className={cn("size-4", isStarred && "fill-warning text-warning")} />
                    </button>
                  </span>
                  {!asList && (
                    <span className="text-muted-foreground line-clamp-2 text-sm">{project.description || PROJECT_SOURCE_LABELS[project.source]}</span>
                  )}
                  <span className="flex items-center gap-2">
                    <span className="bg-muted h-1.5 flex-1 overflow-hidden rounded-full">
                      <span className="bg-primary block h-full" style={{ width: `${percent}%` }} />
                    </span>
                    <span className="text-muted-foreground font-mono text-xs">{percent}%</span>
                  </span>
                  <span className="text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                    <span>
                      {s.done}/{s.total} done
                    </span>
                    {s.overdue > 0 && <span className="text-destructive font-medium">{s.overdue} overdue</span>}
                    {project.target_date && (
                      <span className={cn("flex items-center gap-1", late && "text-destructive font-medium")}>
                        <CalendarIcon className="size-3" />
                        Due {formatDay(project.target_date)}
                      </span>
                    )}
                    {restricted && <span>Only people added</span>}
                    {people.length > 0 && (
                      <span className="ml-auto flex -space-x-1.5" aria-label={`Working on it: ${people.map((m) => m.display_name).join(", ")}`}>
                        {people.slice(0, 4).map((m) => (
                          <UserAvatar
                            key={m.user_id}
                            name={m.display_name}
                            src={memberAvatarSrc(workspace.id, m)}
                            className="ring-card size-5 text-[9px] ring-2"
                          />
                        ))}
                        {people.length > 4 && (
                          <span className="bg-muted ring-card flex size-5 items-center justify-center rounded-full text-[9px] ring-2">
                            +{people.length - 4}
                          </span>
                        )}
                      </span>
                    )}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </>
  );
}

export default function Page() {
  return (
    <Suspense>
      <ProjectsPage />
    </Suspense>
  );
}
