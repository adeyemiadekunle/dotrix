import { CircleCheckIcon, Loader2Icon, LockIcon } from "lucide-react";

import { looksLikeRepoUrl, parseGithub, usePublicGithubRepo } from "@/lib/repo";

/** Confirms a pasted repo address: public GitHub repos are looked up; others are linked by address. */
export function RepoPreview({ url }: { url: string }) {
  const github = parseGithub(url);
  const repo = usePublicGithubRepo(url);
  if (!url.trim()) return null;
  if (!github) {
    return looksLikeRepoUrl(url) ? (
      <p className="text-muted-foreground text-xs">Linked by address; pmagent only reads GitHub repos for now.</p>
    ) : (
      <p className="text-destructive text-xs">Paste the repo&apos;s address, like https://github.com/acme/app.</p>
    );
  }
  if (repo.isLoading) {
    return (
      <p className="text-muted-foreground flex items-center gap-1.5 text-xs">
        <Loader2Icon className="size-3.5 animate-spin" /> Looking up {github.owner}/{github.name} on GitHub…
      </p>
    );
  }
  if (repo.data) {
    return (
      <div className="bg-muted/40 flex items-start gap-2 rounded-md border p-3 text-sm">
        <CircleCheckIcon className="mt-0.5 size-4 shrink-0 text-emerald-600" />
        <div className="grid gap-0.5">
          <a href={repo.data.htmlUrl} target="_blank" rel="noreferrer" className="font-medium underline-offset-4 hover:underline">
            {repo.data.fullName}
          </a>
          {repo.data.description && <span className="text-muted-foreground">{repo.data.description}</span>}
          <span className="text-muted-foreground text-xs">Public · default branch {repo.data.defaultBranch}</span>
        </div>
      </div>
    );
  }
  return (
    <p className="text-muted-foreground flex items-start gap-1.5 text-xs">
      <LockIcon className="mt-0.5 size-3.5 shrink-0" />
      {repo.isError
        ? "Couldn't check the repo on GitHub right now. You can still link it."
        : `No public repo at ${github.owner}/${github.name}. If it's private, you can still link it; reading private code needs the GitHub connection.`}
    </p>
  );
}
