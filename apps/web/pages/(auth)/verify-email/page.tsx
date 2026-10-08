import { useSearchParams } from "@/lib/navigation";

import { VerifyEmail } from "./verify-email";

export default function VerifyEmailPage() {
  const token = useSearchParams().get("token");
  return <VerifyEmail token={token ?? ""} />;
}
