import type { Schemas } from "@pmagent/api-client";
import { Badge } from "@pmagent/ui/components/badge";
import { Button } from "@pmagent/ui/components/button";
import { Skeleton } from "@pmagent/ui/components/skeleton";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { GlobeIcon, KeyRoundIcon, LaptopIcon, SmartphoneIcon } from "lucide-react";
import { toast } from "sonner";

import {
  SettingsContent,
  SettingsDescription,
  SettingsHeader,
  SettingsSection,
  SettingsTitle,
} from "@/components/settings-section";
import { timeAgo } from "@/components/issues/issue-activity";
import { api, authPost, errorMessage, unwrap } from "@/lib/api";

function when(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleDateString() : "never";
}

type Session = Schemas["SessionRead"];

function SessionIcon({ session }: { session: Session }) {
  const Icon =
    session.client === "desktop" ? LaptopIcon : /iOS|Android/.test(session.device) ? SmartphoneIcon : GlobeIcon;
  return <Icon className="text-muted-foreground size-4 shrink-0" />;
}

async function signOutHere() {
  await authPost("logout").catch(() => undefined);
  window.location.assign("/login");
}

/** The browsers and desktop apps you're signed in on; sign any of them out. */
function Sessions() {
  const queryClient = useQueryClient();
  const sessions = useQuery({ queryKey: ["sessions"], queryFn: () => unwrap(api.GET("/v1/me/sessions")) });
  const done = (message: string) => {
    toast.success(message);
    return queryClient.invalidateQueries({ queryKey: ["sessions"] });
  };
  const signOut = useMutation({
    mutationFn: (session_id: string) =>
      unwrap(api.DELETE("/v1/me/sessions/{session_id}", { params: { path: { session_id } } })),
    onSuccess: () => done("Signed out"),
    onError: (e) => toast.error(errorMessage(e)),
  });
  const signOutOthers = useMutation({
    mutationFn: () => unwrap(api.POST("/v1/me/sessions/sign-out-others")),
    onSuccess: ({ signed_out }) => done(`Signed out ${signed_out} ${signed_out === 1 ? "session" : "sessions"}`),
    onError: (e) => toast.error(errorMessage(e)),
  });
  const others = (sessions.data ?? []).filter((s) => !s.current);

  return (
    <SettingsSection>
      <SettingsHeader>
        <SettingsTitle>Browsers and apps</SettingsTitle>
        <SettingsDescription>
          Where you&apos;re signed in to the web app and the desktop app. Sign out any you don&apos;t recognise.
        </SettingsDescription>
      </SettingsHeader>
      <SettingsContent>
        {sessions.isLoading && <Skeleton className="h-16" />}
        {sessions.data && sessions.data.length > 0 && (
          <ul className="divide-y rounded-md border" aria-label="Signed-in browsers and apps">
            {sessions.data.map((session) => (
              <li key={session.id} className="flex items-center gap-3 p-3 text-sm">
                <SessionIcon session={session} />
                <div className="grid min-w-0 flex-1 gap-0.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="truncate font-medium">{session.device}</span>
                    {session.current && <Badge variant="secondary">This device</Badge>}
                  </div>
                  <span className="text-muted-foreground text-xs">
                    {session.current ? "Active now" : `Last active ${timeAgo(session.last_used_at)}`}
                    {session.ip && ` · ${session.ip}`} · signed in {when(session.created_at)}
                  </span>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={signOut.isPending && signOut.variables === session.id}
                  onClick={() => (session.current ? void signOutHere() : signOut.mutate(session.id))}
                  aria-label={`Sign out ${session.device}${session.current ? " (this device)" : ""}`}
                >
                  Sign out
                </Button>
              </li>
            ))}
          </ul>
        )}
        {others.length > 0 && (
          <Button
            size="sm"
            variant="outline"
            className="justify-self-start"
            disabled={signOutOthers.isPending}
            onClick={() => signOutOthers.mutate()}
          >
            Sign out all other sessions
          </Button>
        )}
      </SettingsContent>
    </SettingsSection>
  );
}

/** Where you're signed in: browsers and the desktop app, then the CLI and tools (API tokens). */
export function Devices() {
  return (
    <>
      <Sessions />
      <Tokens />
    </>
  );
}

/** Signed-in CLIs and tokens (the CLI, MCP servers, CI), which you can revoke. */
function Tokens() {
  const queryClient = useQueryClient();
  const tokens = useQuery({ queryKey: ["tokens"], queryFn: () => unwrap(api.GET("/v1/me/tokens")) });
  const revoke = useMutation({
    mutationFn: (token_id: string) => unwrap(api.DELETE("/v1/me/tokens/{token_id}", { params: { path: { token_id } } })),
    onSuccess: () => {
      toast.success("Access revoked");
      return queryClient.invalidateQueries({ queryKey: ["tokens"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  return (
    <SettingsSection>
      <SettingsHeader>
        <SettingsTitle>CLI and tools</SettingsTitle>
        <SettingsDescription>
          The CLI, coding tools, and CI you&apos;ve signed in with <code className="font-mono">pmagent login</code>.
        </SettingsDescription>
      </SettingsHeader>
      <SettingsContent>
        {tokens.isLoading && <Skeleton className="h-16" />}
        {tokens.data?.length === 0 && <p className="text-muted-foreground text-sm">Nothing signed in yet.</p>}
        {tokens.data && tokens.data.length > 0 && (
          <ul className="divide-y rounded-md border">
            {tokens.data.map((token) => (
              <li key={token.id} className="flex items-center gap-3 p-3 text-sm">
                <KeyRoundIcon className="text-muted-foreground size-4 shrink-0" />
                <div className="grid min-w-0 flex-1 gap-0.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="truncate font-medium">{token.name}</span>
                    {token.scopes.map((s) => (
                      <Badge key={s} variant="secondary">
                        {s}
                      </Badge>
                    ))}
                  </div>
                  <span className="text-muted-foreground text-xs">
                    <code className="font-mono">{token.display_prefix}…</code> · created {when(token.created_at)} · last
                    used {when(token.last_used_at)}
                    {token.expires_at && ` · expires ${when(token.expires_at)}`}
                  </span>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={revoke.isPending && revoke.variables === token.id}
                  onClick={() => revoke.mutate(token.id)}
                >
                  Revoke
                </Button>
              </li>
            ))}
          </ul>
        )}
      </SettingsContent>
    </SettingsSection>
  );
}
