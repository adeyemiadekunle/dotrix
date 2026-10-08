import { useSearchParams } from "@/lib/navigation";

import { FinishSignup } from "./finish-signup";

export default function FinishSignupPage() {
  const token = useSearchParams().get("token");
  return <FinishSignup token={token ?? ""} />;
}
