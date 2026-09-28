"use client";

import { Button } from "@pmagent/ui/components/button";
import { MailIcon } from "lucide-react";
import Link from "next/link";
import { useState, type FormEvent } from "react";

import { AuthCard } from "@/components/auth-card";
import { Field, FormError, SubmitButton } from "@/components/form";
import { api, authPost, errorMessage, safeNext, unwrap } from "@/lib/api";

/** Sign in with a password, or with a one-time link sent by email. */
export function LoginForm({ next }: { next?: string }) {
  const [mode, setMode] = useState<"password" | "link">("password");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sentTo, setSentTo] = useState<string | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const email = String(form.get("email") ?? "");
    setPending(true);
    setError(null);
    try {
      if (mode === "link") {
        await unwrap(api.POST("/v1/auth/magic-link/request", { body: { email } }));
        setSentTo(email);
        setPending(false);
        return;
      }
      await authPost("login", { email, password: form.get("password") });
      // A full load, so the server sees the new session cookie.
      window.location.assign(safeNext(next));
    } catch (e) {
      setError(errorMessage(e));
      setPending(false);
    }
  }

  const signupHref = next ? `/signup?next=${encodeURIComponent(next)}` : "/signup";
  const footer = (
    <span>
      New to pmagent?{" "}
      <Link href={signupHref} className="text-foreground underline underline-offset-4">
        Create an account
      </Link>
    </span>
  );

  if (sentTo) {
    return (
      <AuthCard
        title="Check your email"
        description={`If ${sentTo} has a pmagent account, a sign-in link is on its way. It works once, for 15 minutes.`}
        footer={footer}
      >
        <Button
          variant="outline"
          className="w-full"
          onClick={() => {
            setSentTo(null);
            setMode("password");
          }}
        >
          Sign in with a password instead
        </Button>
      </AuthCard>
    );
  }

  return (
    <AuthCard title="Welcome back" description="Sign in to your pmagent account." footer={footer}>
      <form onSubmit={onSubmit} className="grid gap-4">
        <FormError message={error} />
        <Field label="Email" name="email" type="email" autoComplete="email" placeholder="you@company.com" required />
        {mode === "password" && (
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
        )}
        <SubmitButton pending={pending} className="w-full">
          {mode === "password" ? "Sign in" : "Email me a sign-in link"}
        </SubmitButton>
        <Button
          type="button"
          variant="ghost"
          className="w-full"
          onClick={() => {
            setMode(mode === "password" ? "link" : "password");
            setError(null);
          }}
        >
          {mode === "password" ? (
            <>
              <MailIcon /> Email me a sign-in link instead
            </>
          ) : (
            "Sign in with a password instead"
          )}
        </Button>
      </form>
    </AuthCard>
  );
}
