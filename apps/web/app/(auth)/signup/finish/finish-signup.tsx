"use client";

import { Skeleton } from "@pmagent/ui/components/skeleton";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState, type FormEvent } from "react";

import { AuthCard } from "@/components/auth-card";
import { Field, FormError, SubmitButton } from "@/components/form";
import { api, authPost, errorMessage, unwrap } from "@/lib/api";

/**
 * Finish creating an account from an emailed link: the address is already proved, so all that's
 * left is a name. Nothing happens until the form is sent (mail scanners open links).
 */
export function FinishSignup({ token }: { token: string }) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const address = useQuery({
    queryKey: ["email-signup", token],
    queryFn: () => unwrap(api.POST("/v1/auth/magic-link/signup/lookup", { body: { token } })),
    enabled: Boolean(token),
    retry: false,
  });

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setPending(true);
    setError(null);
    try {
      await authPost("signup-link", { token, display_name: form.get("display_name") });
      // A full load, so the server sees the new session cookie.
      window.location.assign("/");
    } catch (e) {
      setError(errorMessage(e));
      setPending(false);
    }
  }

  if (!token || address.isError) {
    return (
      <AuthCard
        title={token ? "This link is invalid or has expired" : "This link is incomplete"}
        description="Sign-up links work once, for 15 minutes. Ask for a new one from the sign-in page."
        footer={<Link href="/login">Back to sign in</Link>}
      >
        <span />
      </AuthCard>
    );
  }
  return (
    <AuthCard
      title="Create your account"
      description={
        address.data ? `For ${address.data.email}. No password needed: you sign in with a link.` : "Checking your link…"
      }
      footer={
        <span>
          Already have an account? <Link href="/login" className="text-foreground underline underline-offset-4">Sign in</Link>
        </span>
      }
    >
      {address.isLoading ? (
        <Skeleton className="h-24" />
      ) : (
        <form onSubmit={onSubmit} className="grid gap-4">
          <FormError message={error} />
          <Field label="Name" name="display_name" autoComplete="name" placeholder="Ada Lovelace" required maxLength={100} autoFocus />
          <SubmitButton pending={pending} className="w-full">
            Create account
          </SubmitButton>
        </form>
      )}
    </AuthCard>
  );
}
