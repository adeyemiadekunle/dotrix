import { useAuthProviders } from "@/lib/api";
import { useSearchParams } from "@/lib/navigation";

import { SignupForm } from "./signup-form";

export default function SignupPage() {
  const params = useSearchParams();
  const providers = useAuthProviders();
  return <SignupForm next={params.get("next") ?? undefined} signupError={params.get("error") ?? undefined} github={providers.github} />;
}
