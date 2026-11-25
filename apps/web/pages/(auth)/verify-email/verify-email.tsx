import { Button } from "@dotrix/ui/components/button";
import { useMutation, useQuery } from "@tanstack/react-query";
import { CircleCheckIcon, CircleXIcon, LoaderCircleIcon } from "lucide-react";
import { Link } from "@/lib/navigation";
import { useEffect, useRef, useState } from "react";

import { AuthCard } from "@/components/auth-card";
import { api, errorMessage, hasSession, unwrap } from "@/lib/api";

export function VerifyEmail({ token }: { token: string }) {
  const signedIn = hasSession();
  const [resent, setResent] = useState(false);
  const verify = useMutation({
    mutationFn: () => unwrap(api.POST("/v1/auth/verify-email", { body: { token } })),
  });
  const resend = useMutation({
    mutationFn: () => unwrap(api.POST("/v1/auth/verify-email/resend")),
    onSuccess: () => setResent(true),
  });
  const profile = useQuery({
    queryKey: ["verify-email-me"],
    enabled: signedIn && verify.isSuccess,
    queryFn: () => unwrap(api.GET("/v1/me")),
  });
  const { mutate } = verify;
  // The token works once: don't send it twice (React runs effects twice in development).
  const sent = useRef(false);
  useEffect(() => {
    if (token && !sent.current) {
      sent.current = true;
      mutate();
    }
  }, [token, mutate]);

  const needsOnboarding = signedIn && profile.data && profile.data.onboarding_workspace_id == null;
  const continueHref = !signedIn ? "/login?next=%2Fonboarding" : needsOnboarding ? "/onboarding" : "/";
  const continueLabel = !signedIn ? "Sign in to continue setup" : needsOnboarding ? "Continue setup" : "Go to dotrix";

  if (!token || verify.isError) {
    return (
      <AuthCard title="We couldn't verify your email">
        <div className="grid gap-4">
          <p className="text-muted-foreground flex gap-2 text-sm">
            <CircleXIcon className="text-destructive size-4 shrink-0" />
            {token ? errorMessage(verify.error) : "This link is incomplete."}
          </p>
          {resent && (
            <p role="status" className="text-muted-foreground text-sm">
              Sent a new verification email. Check your inbox for the latest link.
            </p>
          )}
          {resend.isError && <p className="text-destructive text-sm">{errorMessage(resend.error)}</p>}
          {signedIn && (
            <Button variant="outline" className="w-full" disabled={resend.isPending} onClick={() => resend.mutate()}>
              {resend.isPending ? "Sending…" : "Resend verification email"}
            </Button>
          )}
          <Button asChild className="w-full">
            <Link href={signedIn ? "/onboarding" : "/login"}>{signedIn ? "Back to setup" : "Sign in"}</Link>
          </Button>
        </div>
      </AuthCard>
    );
  }
  if (verify.isSuccess) {
    return (
      <AuthCard title="Email verified">
        <div className="grid gap-4">
          <p className="text-muted-foreground flex gap-2 text-sm">
            <CircleCheckIcon className="size-4 shrink-0 text-emerald-600" />
            Thanks, your email address is confirmed.
          </p>
          <Button asChild className="w-full" disabled={signedIn && profile.isLoading}>
            <Link href={continueHref}>{continueLabel}</Link>
          </Button>
        </div>
      </AuthCard>
    );
  }
  return (
    <AuthCard title="Verifying your email…">
      <LoaderCircleIcon className="text-muted-foreground mx-auto size-6 animate-spin" />
    </AuthCard>
  );
}
