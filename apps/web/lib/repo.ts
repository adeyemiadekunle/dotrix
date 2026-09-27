"use client";

import { useQuery } from "@tanstack/react-query";

/** owner/name from a GitHub URL in any usual form (https, ssh, with or without .git). */
export function parseGithub(url: string): { owner: string; name: string } | null {
  const match = url
    .trim()
    .match(/^(?:https?:\/\/(?:[^@/]+@)?github\.com\/|git@github\.com:|ssh:\/\/git@github\.com\/)([\w.-]+)\/([\w.-]+?)(?:\.git)?\/?$/i);
  return match ? { owner: match[1]!, name: match[2]! } : null;
}

/** Looks like a repo address from any host; the backend canonicalises it. */
export function looksLikeRepoUrl(url: string): boolean {
  return /^(https?:\/\/[^/\s]+\/[^/\s]+\/[^\s]+|[\w.-]+@[\w.-]+:[^\s]+|ssh:\/\/[^\s]+)$/.test(url.trim());
}

export interface PublicRepo {
  fullName: string;
  description: string;
  defaultBranch: string;
  private: boolean;
  htmlUrl: string;
}

/**
 * Public details of a GitHub repo, straight from GitHub's API (no sign-in, so private repos
 * come back as not found). Used only to confirm the link and prefill the name.
 */
export function usePublicGithubRepo(url: string) {
  const repo = parseGithub(url);
  return useQuery({
    queryKey: ["github-repo", repo?.owner.toLowerCase(), repo?.name.toLowerCase()],
    queryFn: async (): Promise<PublicRepo | null> => {
      const response = await fetch(`https://api.github.com/repos/${repo!.owner}/${repo!.name}`, {
        headers: { Accept: "application/vnd.github+json" },
      });
      if (response.status === 404) return null;
      if (!response.ok) throw new Error(`GitHub answered ${response.status}`);
      const data = (await response.json()) as {
        full_name: string;
        description: string | null;
        default_branch: string;
        private: boolean;
        html_url: string;
      };
      return {
        fullName: data.full_name,
        description: data.description ?? "",
        defaultBranch: data.default_branch,
        private: data.private,
        htmlUrl: data.html_url,
      };
    },
    enabled: Boolean(repo),
    staleTime: 10 * 60_000,
    retry: false,
  });
}
