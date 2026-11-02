import { Button } from "@dotrix/ui/components/button";
import { useMutation, useQuery } from "@tanstack/react-query";
import { SpinnerGapIcon } from "@phosphor-icons/react";
import { Link } from "@/lib/navigation";

import { AuthCard } from "@/components/auth-card";
import { FormError } from "@/components/form";
import { api, errorMessage, hasSession, safeNext, unwrap } from "@/lib/api";
import { ROLE_LABELS } from "@/lib/labels";

export function AcceptInvite({ token, next }: { token: string; next?: string | null }) {
  const preview = useQuery({
    queryKey: ["invite-preview", token],
    queryFn: () => unwrap(api.POST("/v1/invites/preview", { body: { token } })),
    enabled: Boolean(token),
    retry: false,
  });
  const accept = useMutation({
    mutationFn: () => unwrap(api.POST("/v1/invites/accept", { body: { token } })),
    onSuccess: (workspace) => {
      const home = `/w/${workspace.slug}`;
      const destination = new URL(safeNext(next), location.origin);
      window.location.assign(
        destination.pathname === home || destination.pathname.startsWith(`${home}/`) ? destination.pathname + destination.search + destination.hash : home,
      );
    },
  });

  if (!token || preview.isError) {
    return (
      <AuthCard title="This invite doesn't work">
        <div className="grid gap-4">
          <p className="text-muted-foreground text-sm">
            {token ? errorMessage(preview.error) : "The link is incomplete."} Ask whoever invited you for a new link.
          </p>
          <Button asChild variant="outline" className="w-full">
            <Link href="/">Go to dotrix</Link>
          </Button>
        </div>
      </AuthCard>
    );
  }
  if (!preview.data) {
    return (
      <AuthCard title="Opening your invite…">
        <SpinnerGapIcon className="text-muted-foreground mx-auto size-6 animate-spin" />
      </AuthCard>
    );
  }
  const invite = preview.data;
  return (
    <AuthCard
      title={`Join ${invite.workspace_name}`}
      description={
        <>
          {invite.invited_by ? `${invite.invited_by} invited you` : "You've been invited"} as {ROLE_LABELS[invite.role].toLowerCase()}.
        </>
      }
    >
      <div className="grid gap-4">
        <FormError message={accept.isError ? errorMessage(accept.error) : null} />
        {hasSession() ? (
          <Button className="w-full" disabled={accept.isPending} onClick={() => accept.mutate()}>
            {accept.isPending && <SpinnerGapIcon className="animate-spin" />}
            Accept and join
          </Button>
        ) : (
          <>
            <Button className="w-full" asChild>
              <Link href={`/signup?next=${encodeURIComponent(location.pathname + location.search)}`}>Create an account to join</Link>
            </Button>
            <Button className="w-full" variant="outline" asChild>
              <Link href={`/login?next=${encodeURIComponent(location.pathname + location.search)}`}>Sign in to join</Link>
            </Button>
          </>
        )}
      </div>
    </AuthCard>
  );
}
