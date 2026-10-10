import { Button } from "@dotrix/ui/components/button";
import { useMutation } from "@tanstack/react-query";
import { CircleCheckIcon, CircleXIcon, Loader2Icon } from "lucide-react";
import { Link } from "@/lib/navigation";
import { useEffect, useRef } from "react";

import { AuthCard } from "@/components/auth-card";
import { api, errorMessage, unwrap } from "@/lib/api";

export function VerifyEmail({ token }: { token: string }) {
  const verify = useMutation({
    mutationFn: () => unwrap(api.POST("/v1/auth/verify-email", { body: { token } })),
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

  const home = (
    <Button asChild className="w-full">
      <Link href="/">Go to dotrix</Link>
    </Button>
  );
  if (!token || verify.isError) {
    return (
      <AuthCard title="We couldn't verify your email">
        <div className="grid gap-4">
          <p className="text-muted-foreground flex gap-2 text-sm">
            <CircleXIcon className="text-destructive size-4 shrink-0" />
            {token ? errorMessage(verify.error) : "This link is incomplete."} You can send a new link from Settings.
          </p>
          {home}
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
          {home}
        </div>
      </AuthCard>
    );
  }
  return (
    <AuthCard title="Verifying your email…">
      <Loader2Icon className="text-muted-foreground mx-auto size-6 animate-spin" />
    </AuthCard>
  );
}
