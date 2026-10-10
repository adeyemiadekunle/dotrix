import type { Schemas } from "@dotrix/api-client";
import { Badge } from "@dotrix/ui/components/badge";
import { Button } from "@dotrix/ui/components/button";
import { Skeleton } from "@dotrix/ui/components/skeleton";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "@/lib/navigation";
import { useEffect, type ReactNode } from "react";
import { toast } from "sonner";

import { useConfirm } from "@/components/confirm-dialog";
import { GitHubMark } from "@/components/github-sign-in";
import { InstallGitHubButton } from "@/components/github-repos";
import {
  SettingsContent,
  SettingsDescription,
  SettingsHeader,
  SettingsSection,
  SettingsTitle,
} from "@/components/settings-section";
import { api, errorMessage, unwrap } from "@/lib/api";
import { useGitHubRepos, useGitHubStatus } from "@/lib/github";
import { useSetSearchParams } from "@/lib/url-state";

type Workspace = Schemas["WorkspaceWithRole"];

const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" });

/** Settings → GitHub (owners and admins): the accounts the GitHub App is installed on for this workspace. */
export function GitHubSettings({ workspace }: { workspace: Workspace }) {
  const queryClient = useQueryClient();
  const status = useGitHubStatus(workspace.id);
  const installed = status.data?.installations ?? [];
  const repos = useGitHubRepos(workspace.id, installed.length > 0);
  const [ask, confirmDialog] = useConfirm();

  // Back from GitHub after installing: say how it went, once.
  const params = useSearchParams();
  const setParams = useSetSearchParams();
  const outcome = params.get("github");
  const failure = params.get("github_error");
  useEffect(() => {
    if (outcome === "installed") toast.success("GitHub connected: pick a repo in each project's settings");
    if (outcome === "updated") toast.success("GitHub updated");
    if (failure) toast.error(failure);
    if (outcome || failure) {
      void queryClient.invalidateQueries({ queryKey: ["github", workspace.id] });
      setParams({ github: null, github_error: null });
    }
  }, [outcome, failure, queryClient, setParams, workspace.id]);

  const forget = useMutation({
    mutationFn: (ref: string) =>
      unwrap(
        api.DELETE("/v1/workspaces/{workspace_id}/github/installations/{installation_ref}", {
          params: { path: { workspace_id: workspace.id, installation_ref: ref } },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["github", workspace.id] });
      void queryClient.invalidateQueries({ queryKey: ["project-repository", workspace.id] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const repoCount = (ref: string) => repos.data?.filter((r) => r.installation_ref === ref).length;
  const connectedCount = (ref: string) => repos.data?.filter((r) => r.installation_ref === ref && r.project_key).length;

  return (
    <SettingsSection stacked>
      <SettingsHeader>
        <SettingsTitle>GitHub</SettingsTitle>
        <SettingsDescription>
          The dotrix GitHub App reads the repos you give it, so each project can connect to its code, private repos
          included. Agents use it to understand the codebase, and later to open pull requests. You choose which repos
          on GitHub.
        </SettingsDescription>
      </SettingsHeader>
      <SettingsContent className="p-0">
        {!status.data ? (
          <Skeleton className="m-5 h-24" />
        ) : !status.data.configured ? (
          <Notice
            title="The GitHub App isn't set up on this server"
            description="Whoever runs dotrix sets DOTRIX_GITHUB_APP_ID, DOTRIX_GITHUB_APP_SLUG, and the app's private key. Until then, projects link a repo by its address."
          />
        ) : (
          <>
            {installed.length === 0 ? (
              <Notice
                title="Not connected yet"
                description="Install the app on your GitHub account or organisation and choose its repos. You'll come straight back here."
                action={<InstallGitHubButton status={status.data} workspaceId={workspace.id} variant="default" />}
              />
            ) : (
              <ul className="divide-y" aria-label="GitHub accounts">
                {installed.map((installation) => (
                  <li key={installation.id} className="flex flex-wrap items-center gap-3 p-4">
                    <span className="bg-muted flex size-9 shrink-0 items-center justify-center rounded-md">
                      <GitHubMark />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="flex items-center gap-2 font-medium">
                        {installation.account_login}
                        <Badge variant="outline">{installation.account_type === "Organization" ? "Organisation" : "Personal"}</Badge>
                        {installation.suspended && <Badge variant="destructive">Suspended</Badge>}
                      </p>
                      <p className="text-muted-foreground text-xs">
                        Added {dateFormat.format(new Date(installation.created_at))}
                        {repoCount(installation.id) !== undefined &&
                          ` · ${repoCount(installation.id)} repo${repoCount(installation.id) === 1 ? "" : "s"}, ${connectedCount(installation.id)} connected to projects`}
                      </p>
                    </div>
                    <Button size="sm" variant="ghost" asChild>
                      <a
                        href={
                          installation.account_type === "Organization"
                            ? `https://github.com/organizations/${installation.account_login}/settings/installations/${installation.installation_id}`
                            : `https://github.com/settings/installations/${installation.installation_id}`
                        }
                        target="_blank"
                        rel="noreferrer"
                      >
                        Choose repos on GitHub
                      </a>
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() =>
                        ask({
                          title: `Forget ${installation.account_login}?`,
                          description:
                            "Projects using its repos are disconnected (their addresses stay). The app stays installed on GitHub until you uninstall it there.",
                          confirm: "Forget",
                          destructive: true,
                          action: () => forget.mutateAsync(installation.id),
                        })
                      }
                    >
                      Forget
                    </Button>
                  </li>
                ))}
              </ul>
            )}
            {installed.length > 0 && (
              <div className="border-t p-4">
                <InstallGitHubButton status={status.data} workspaceId={workspace.id} label="Add another GitHub account" />
              </div>
            )}
          </>
        )}
        {confirmDialog}
      </SettingsContent>
    </SettingsSection>
  );
}

function Notice({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return (
    <div className="grid justify-items-start gap-3 p-5">
      <div className="grid gap-1">
        <p className="font-medium">{title}</p>
        <p className="text-muted-foreground max-w-prose text-sm">{description}</p>
      </div>
      {action}
    </div>
  );
}
