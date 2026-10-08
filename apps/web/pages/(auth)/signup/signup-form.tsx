import { Button } from "@pmagent/ui/components/button";
import { MailIcon } from "lucide-react";
import { Link } from "@/lib/navigation";
import { useState, type FormEvent } from "react";

import { AuthCard } from "@/components/auth-card";
import { Field, FormError, SubmitButton } from "@/components/form";
import { GitHubSignIn } from "@/components/github-sign-in";
import { authPost, errorMessage, safeNext } from "@/lib/api";

export function SignupForm({ next, github = false }: { next?: string; github?: boolean }) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setPending(true);
    setError(null);
    try {
      await authPost("signup", {
        display_name: form.get("display_name"),
        email: form.get("email"),
        password: form.get("password"),
      });
      window.location.assign(safeNext(next));
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
        {github && <GitHubSignIn next={next} />}
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
          <Link href="/login?link=1">
            <MailIcon /> Sign up with an email link instead
          </Link>
        </Button>
      </form>
    </AuthCard>
  );
}
