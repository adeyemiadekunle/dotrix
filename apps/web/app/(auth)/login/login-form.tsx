"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { AuthCard } from "@/components/auth-card";
import { Field, FormError, SubmitButton } from "@/components/form";
import { authPost, errorMessage, safeNext } from "@/lib/api";

export function LoginForm({ next }: { next?: string }) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setPending(true);
    setError(null);
    try {
      await authPost("login", { email: form.get("email"), password: form.get("password") });
      // A full load, so the server sees the new session cookie.
      window.location.assign(safeNext(next));
    } catch (e) {
      setError(errorMessage(e));
      setPending(false);
    }
  }

  const signupHref = next ? `/signup?next=${encodeURIComponent(next)}` : "/signup";
  return (
    <AuthCard
      title="Welcome back"
      description="Sign in to your pmagent account."
      footer={
        <span>
          New to pmagent?{" "}
          <Link href={signupHref} className="text-foreground underline underline-offset-4">
            Create an account
          </Link>
        </span>
      }
    >
      <form onSubmit={onSubmit} className="grid gap-4">
        <FormError message={error} />
        <Field label="Email" name="email" type="email" autoComplete="email" placeholder="you@company.com" required />
        <Field
          label="Password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          action={
            <Link href="/forgot-password" className="text-muted-foreground text-sm underline-offset-4 hover:underline">
              Forgot password?
            </Link>
          }
        />
        <SubmitButton pending={pending} className="w-full">
          Sign in
        </SubmitButton>
      </form>
    </AuthCard>
  );
}
