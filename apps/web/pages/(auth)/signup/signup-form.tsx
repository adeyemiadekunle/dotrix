import { Button } from "@dotrix/ui/components/button";
import { MailIcon } from "lucide-react";
import { Link } from "@/lib/navigation";
import { useState, type FormEvent } from "react";

import { AuthCard } from "@/components/auth-card";
import { Field, FormError, SubmitButton } from "@/components/form";
import { GitHubSignIn } from "@/components/github-sign-in";
import { TERMS_VERSION, TermsAcceptance } from "@/components/terms-acceptance";
import { authPost, errorMessage, safeNext } from "@/lib/api";

export function SignupForm({ next, github = false, signupError }: { next?: string; github?: boolean; signupError?: string }) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(signupError ?? null);
  const [accepted, setAccepted] = useState(false);
  const destination = next ? safeNext(next) : "/onboarding";

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    if (!form.has("accept_terms")) return;
    setPending(true);
    setError(null);
    try {
      await authPost("signup", {
        display_name: form.get("display_name"),
        email: form.get("email"),
        password: form.get("password"),
        terms_version: TERMS_VERSION,
      });
      window.location.assign(destination);
    } catch (e) {
      setError(errorMessage(e));
      setPending(false);
    }
  }

  async function withGitHub() {
    if (!accepted || pending) return;
    setPending(true);
    setError(null);
    try {
      const response = await authPost("github/signup", { terms_version: TERMS_VERSION, next: destination });
      const { authorize_url } = (await response.json()) as { authorize_url: string };
      window.location.assign(authorize_url);
    } catch (e) {
      setError(errorMessage(e));
      setPending(false);
    }
  }

  const loginHref = next ? `/login?next=${encodeURIComponent(next)}` : "/login";
  return (
    <AuthCard
      title="Create your account"
      description="You get a personal workspace to start in."
      footer={
        <span>
          Already have an account?{" "}
          <Link href={loginHref} className="text-foreground underline underline-offset-4">
            Sign in
          </Link>
        </span>
      }
    >
      <form onSubmit={onSubmit} className="grid gap-4">
        <FormError message={error} />
        <TermsAcceptance onChange={setAccepted} />
        {github && <GitHubSignIn onClick={() => void withGitHub()} disabled={!accepted || pending} />}
        <Field label="Name" name="display_name" autoComplete="name" placeholder="Ada Lovelace" required maxLength={100} />
        <Field label="Email" name="email" type="email" autoComplete="email" placeholder="you@company.com" required />
        <Field
          label="Password"
          name="password"
          type="password"
          autoComplete="new-password"
          required
          minLength={10}
          maxLength={128}
          hint="At least 10 characters."
        />
        <SubmitButton pending={pending} className="w-full">
          Create account
        </SubmitButton>
        <Button type="button" variant="ghost" className="w-full" asChild>
          <Link href={`/login?link=1&next=${encodeURIComponent(next ? safeNext(next) : "/onboarding")}`}>
            <MailIcon /> Sign up with an email link instead
          </Link>
        </Button>
      </form>
    </AuthCard>
  );
}
