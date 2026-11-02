import { useSearchParams } from "@/lib/navigation";

import { FinishSignup } from "./finish-signup";

export default function FinishSignupPage() {
  const params = useSearchParams();
  return <FinishSignup token={params.get("token") ?? ""} next={params.get("next")} />;
}
