import { useAuthProviders } from "@/lib/api";
import { useSearchParams } from "@/lib/navigation";

import { LoginForm } from "./login-form";

export default function LoginPage() {
  const params = useSearchParams();
  const providers = useAuthProviders();
  return (
    <LoginForm
      next={params.get("next") ?? undefined}
      emailLink={params.get("link") === "1"}
      github={providers.github}
      initialError={params.get("error") ?? undefined}
    />
  );
}
