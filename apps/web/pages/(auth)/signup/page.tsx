import { useAuthProviders } from "@/lib/api";
import { useSearchParams } from "@/lib/navigation";

import { SignupForm } from "./signup-form";

export default function SignupPage() {
  const next = useSearchParams().get("next");
  const providers = useAuthProviders();
  return <SignupForm next={next ?? undefined} github={providers.github} />;
}
