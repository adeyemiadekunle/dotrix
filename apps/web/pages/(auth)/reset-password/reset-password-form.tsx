import { Button } from "@pmagent/ui/components/button";
import { Link } from "@/lib/navigation";
import { useState, type FormEvent } from "react";

import { AuthCard } from "@/components/auth-card";
import { Field, FormError, SubmitButton } from "@/components/form";
import { api, authPost, errorMessage, unwrap } from "@/lib/api";

export function ResetPasswordForm({ token }: { token: string }) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    if (form.get("new_password") !== form.get("confirm")) {
      setError("The passwords don't match.");
      return;
    }
    setPending(true);
    setError(null);
    try {
      await unwrap(
        api.POST("/v1/auth/password-reset/confirm", {
          body: { token, new_password: String(form.get("new_password")) },
        }),
      );
      // The backend signed every session out; drop this browser's (now dead) cookies too.
      await authPost("logout").catch(() => undefined);
      setDone(true);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setPending(false);
    }
  }

  if (!token) {
    return (
      <AuthCard title="This link is incomplete" footer={<Link href="/forgot-password">Request a new link</Link>}>
        <p className="text-muted-foreground text-sm">Open the link from your email again, or request a new one.</p>
      </AuthCard>
    );
  }
  if (done) {
    return (
      <AuthCard title="Password changed" description="You've been signed out on every device. Sign in with your new password.">
        <Button asChild className="w-full">
          <Link href="/login">Sign in</Link>
        </Button>
      </AuthCard>
    );
  }
  return (
    <AuthCard title="Choose a new password">
      <form onSubmit={onSubmit} className="grid gap-4">
        <FormError message={error} />
        <Field
          label="New password"
          name="new_password"
          type="password"
          autoComplete="new-password"
          required
          minLength={10}
          maxLength={128}
          hint="At least 10 characters."
        />
        <Field label="Confirm password" name="confirm" type="password" autoComplete="new-password" required />
        <SubmitButton pending={pending} className="w-full">
          Change password
        </SubmitButton>
      </form>
    </AuthCard>
  );
}
