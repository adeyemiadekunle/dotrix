import { Button } from "@dotrix/ui/components/button";
import { Input } from "@dotrix/ui/components/input";
import { Skeleton } from "@dotrix/ui/components/skeleton";
import { cn } from "@dotrix/ui/lib/utils";
import { CheckIcon, LockIcon } from "lucide-react";
import { Link, usePathname } from "@/lib/navigation";
import { useState } from "react";

import { GitHubMark } from "@/components/github-sign-in";
import { type GitHubStatus, type RepoOption, installHref, useGitHubRepos, useGitHubStatus } from "@/lib/github";

/** "Install the GitHub App" for the workspace: GitHub's install page, then back here. */
export function InstallGitHubButton({
  status,
  workspaceId,
  label = "Install the GitHub App",
  variant = "outline",
}: {
  status: GitHubStatus;
  workspaceId: string;
  label?: string;
  variant?: "default" | "outline";
}) {
  const pathname = usePathname();
  const href = installHref(status, workspaceId, pathname);
  if (!href) return null;
  return (
    <Button size="sm" variant={variant} asChild>
      <a href={href}>
        <GitHubMark />
        {label}
      </a>
    </Button>
  );
}

/**
 * Pick one of the repos the workspace's GitHub App installations can see, private ones included.
 * Repos another project uses can't be picked. Says what to do when the app isn't set up or
 * installed yet (`settingsHref`: Settings → GitHub).
 */
export function RepoPicker({
  workspaceId,
  projectKey,
  value,
  onPick,
  settingsHref,
}: {
  workspaceId: string;
  /** The project being connected (its own repo stays pickable). */
  projectKey?: string;
  value: RepoOption | null;
  onPick: (repo: RepoOption) => void;
  settingsHref: string;
}) {
  const status = useGitHubStatus(workspaceId);
  const ready = !!status.data?.configured && status.data.installations.length > 0;
  const repos = useGitHubRepos(workspaceId, ready);
  const [filter, setFilter] = useState("");

  if (!status.data) return <Skeleton className="h-24" />;
  if (!status.data.configured) {
    return (
      <p className="text-muted-foreground text-sm">
        Connecting private repos needs the GitHub App, which isn&apos;t set up on this server yet. Paste the address instead.
      </p>
    );
  }
  if (status.data.installations.length === 0) {
    return (
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-dashed p-3 text-sm">
        <p className="text-muted-foreground min-w-0 flex-1">
          Install the GitHub App on your account or organisation to pick its repos here, private ones included.
        </p>
        <InstallGitHubButton status={status.data} workspaceId={workspaceId} />
      </div>
    );
  }
  if (!repos.data) return <Skeleton className="h-24" />;

  const query = filter.trim().toLowerCase();
  const shown = repos.data.filter((r) => !query || r.full_name.toLowerCase().includes(query));
  return (
    <div className="grid gap-2">
      <Input
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        placeholder={`Search ${repos.data.length} repo${repos.data.length === 1 ? "" : "s"}`}
        aria-label="Search repositories"
      />
      <ul role="listbox" aria-label="Repositories on GitHub" className="max-h-64 overflow-y-auto rounded-lg border">
        {shown.map((repo) => {
          const taken = !!repo.project_key && repo.project_key !== projectKey;
          const picked = value?.github_repo_id === repo.github_repo_id;
          return (
            <li key={repo.github_repo_id} role="option" aria-selected={picked} aria-disabled={taken}>
              <button
                type="button"
                disabled={taken}
                onClick={() => onPick(repo)}
                className={cn(
                  "hover:bg-muted flex w-full items-center gap-2 px-3 py-2 text-left text-sm disabled:cursor-not-allowed disabled:opacity-60",
                  picked && "bg-brand-muted",
                )}
              >
                <span className="min-w-0 flex-1 truncate">{repo.full_name}</span>
                {repo.private && <LockIcon aria-label="Private" className="text-muted-foreground size-3.5 shrink-0" />}
                {taken && <span className="text-muted-foreground shrink-0 text-xs">Used by {repo.project_key}</span>}
                {picked && <CheckIcon className="text-primary size-4 shrink-0" />}
              </button>
            </li>
          );
        })}
        {shown.length === 0 && (
          <li className="text-muted-foreground px-3 py-4 text-center text-sm">{repos.data.length ? "No repo matches." : "The app can't see any repos yet."}</li>
        )}
      </ul>
      <p className="text-muted-foreground text-xs">
        Missing one? Give the app access to it on GitHub, or add another account in{" "}
        <Link href={settingsHref} className="underline underline-offset-4">
          Settings → GitHub
        </Link>
        .
      </p>
    </div>
  );
}
