"use client";

import { Badge } from "@pmagent/ui/components/badge";
import { Button } from "@pmagent/ui/components/button";
import { Skeleton } from "@pmagent/ui/components/skeleton";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRoundIcon } from "lucide-react";
import { toast } from "sonner";

import {
  SettingsContent,
  SettingsDescription,
  SettingsHeader,
  SettingsSection,
  SettingsTitle,
} from "@/components/settings-section";
import { api, errorMessage, unwrap } from "@/lib/api";

function when(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleDateString() : "never";
}

/** Signed-in devices and tokens (the CLI, MCP servers, CI), which you can revoke. */
export function Devices() {
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
        <SettingsTitle>Devices and tokens</SettingsTitle>
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
