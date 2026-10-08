import { useSearchParams } from "@/lib/navigation";

import { MagicLinkSignIn } from "./magic-link-sign-in";

export default function MagicLinkPage() {
  const token = useSearchParams().get("token");
  return <MagicLinkSignIn token={token ?? ""} />;
}
