import { Button } from "@dotrix/ui/components/button";
import { Loader2Icon } from "lucide-react";
import { Link } from "@/lib/navigation";
import { useState } from "react";

import { AuthCard } from "@/components/auth-card";
import { FormError } from "@/components/form";
import { authPost, errorMessage } from "@/lib/api";

/**
 * Sign in from an emailed link. It takes a click rather than happening when the page opens:
 * mail scanners open links in emails, and would otherwise use the one-time link up.
 */
export function MagicLinkSignIn({ token }: { token: string }) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function signIn() {
    setPending(true);
    setError(null);
    try {
      await authPost("magic-link", { token });
      // A full load, so the server sees the new session cookie.
      window.location.assign("/");
    } catch (e) {
      setError(errorMessage(e));
      setPending(false);
    }
  }

  if (!token) {
    return (
      <AuthCard title="This link is incomplete" footer={<Link href="/login">Back to sign in</Link>}>
        <p className="text-muted-foreground text-sm">Open the link from your email again, or ask for a new one.</p>
      </AuthCard>
    );
  }
  return (
    <AuthCard title="Sign in to dotrix" description="You opened a sign-in link from your email." footer={<Link href="/login">Sign in another way</Link>}>
      <div className="grid gap-4">
        <FormError message={error ? `${error.replace(/\.$/, "")}. Ask for a new link from the sign-in page.` : null} />
        <Button className="w-full" disabled={pending} onClick={() => void signIn()}>
          {pending && <Loader2Icon className="animate-spin" />}
          Sign in
        </Button>
      </div>
    </AuthCard>
  );
}
