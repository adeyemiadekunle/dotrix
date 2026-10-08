import { Link } from "@/lib/navigation";
import { useState, type FormEvent } from "react";

import { AuthCard } from "@/components/auth-card";
import { Field, FormError, SubmitButton } from "@/components/form";
import { api, errorMessage, unwrap } from "@/lib/api";

export default function ForgotPasswordPage() {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sentTo, setSentTo] = useState<string | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const email = String(new FormData(event.currentTarget).get("email"));
    setPending(true);
    setError(null);
    try {
      await unwrap(api.POST("/v1/auth/password-reset/request", { body: { email } }));
      setSentTo(email);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setPending(false);
    }
  }

  const back = (
    <Link href="/login" className="text-foreground underline underline-offset-4">
      Back to sign in
    </Link>
  );
  if (sentTo) {
    return (
      <AuthCard title="Check your email" footer={back}>
        <p className="text-muted-foreground text-sm">
          If there&apos;s an account for <span className="text-foreground font-medium">{sentTo}</span>, we&apos;ve sent
          it a link to reset the password. The link works once and expires in an hour.
        </p>
      </AuthCard>
    );
  }
  return (
    <AuthCard title="Reset your password" description="We'll email you a link to choose a new one." footer={back}>
      <form onSubmit={onSubmit} className="grid gap-4">
        <FormError message={error} />
        <Field label="Email" name="email" type="email" autoComplete="email" placeholder="you@company.com" required />
        <SubmitButton pending={pending} className="w-full">
          Send reset link
        </SubmitButton>
      </form>
    </AuthCard>
  );
}
