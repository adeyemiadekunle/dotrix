import { useSearchParams } from "@/lib/navigation";

import { MagicLinkSignIn } from "./magic-link-sign-in";

export default function MagicLinkPage() {
  const params = useSearchParams();
  return <MagicLinkSignIn token={params.get("token") ?? ""} next={params.get("next")} />;
}
