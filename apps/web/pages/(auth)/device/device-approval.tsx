import { Badge } from "@dotrix/ui/components/badge";
import { Button } from "@dotrix/ui/components/button";
import { useMutation } from "@tanstack/react-query";
import { CircleCheckIcon, CircleXIcon, TerminalIcon } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";

import { AuthCard } from "@/components/auth-card";
import { Field, FormError, SubmitButton } from "@/components/form";
import { api, errorMessage, unwrap } from "@/lib/api";

type Outcome = "approved" | "denied";

export function DeviceApproval({ initialCode }: { initialCode: string }) {
  const [code, setCode] = useState(initialCode);
  const [outcome, setOutcome] = useState<Outcome | null>(null);

  const lookup = useMutation({
    mutationFn: (user_code: string) => unwrap(api.POST("/v1/auth/device/lookup", { body: { user_code } })),
  });
  const decide = useMutation({
    mutationFn: async (decision: Outcome) => {
      const body = { user_code: code };
      await unwrap(decision === "approved" ? api.POST("/v1/auth/device/approve", { body }) : api.POST("/v1/auth/device/deny", { body }));
      return decision;
    },
    onSuccess: setOutcome,
  });

  const { mutate: find } = lookup;
  useEffect(() => {
    if (initialCode) find(initialCode);
  }, [initialCode, find]);

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    find(code.trim());
  }

  if (outcome) {
    return (
      <AuthCard title={outcome === "approved" ? "Device signed in" : "Sign-in denied"}>
        <p className="text-muted-foreground flex gap-2 text-sm">
          {outcome === "approved" ? (
            <>
              <CircleCheckIcon className="size-4 shrink-0 text-emerald-600" />
              Go back to your terminal; it&apos;s signed in. You can revoke it any time in Settings.
            </>
          ) : (
            <>
              <CircleXIcon className="text-destructive size-4 shrink-0" />
              The device wasn&apos;t signed in. You can close this page.
            </>
          )}
        </p>
      </AuthCard>
    );
  }

  if (lookup.data) {
    return (
      <AuthCard title="Sign in this device?" description="Only approve if you started this sign-in yourself.">
        <div className="grid gap-4">
          <div className="bg-muted/50 grid gap-2 rounded-md border p-3 text-sm">
            <div className="flex items-center gap-2 font-medium">
              <TerminalIcon className="size-4" />
              {lookup.data.client_name}
            </div>
            <div className="text-muted-foreground flex items-center gap-2">
              Code <span className="text-foreground font-mono">{code}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground">Access</span>
              {lookup.data.scopes.map((s) => (
                <Badge key={s} variant="secondary">
                  {s}
                </Badge>
              ))}
            </div>
          </div>
          <FormError message={decide.isError ? errorMessage(decide.error) : null} />
          <div className="grid grid-cols-2 gap-2">
            <Button variant="outline" disabled={decide.isPending} onClick={() => decide.mutate("denied")}>
              Deny
            </Button>
            <Button disabled={decide.isPending} onClick={() => decide.mutate("approved")}>
              Approve
            </Button>
          </div>
        </div>
      </AuthCard>
    );
  }

  return (
    <AuthCard title="Sign in a device" description="Enter the code shown in your terminal.">
      <form onSubmit={onSubmit} className="grid gap-4">
        <FormError message={lookup.isError ? errorMessage(lookup.error) : null} />
        <Field
          label="Code"
          value={code}
          onChange={(e) => setCode(e.target.value.toUpperCase())}
          placeholder="BCDF-GHJK"
          autoComplete="off"
          className="font-mono tracking-widest uppercase"
          required
          maxLength={16}
        />
        <SubmitButton pending={lookup.isPending} className="w-full">
          Continue
        </SubmitButton>
      </form>
    </AuthCard>
  );
}
