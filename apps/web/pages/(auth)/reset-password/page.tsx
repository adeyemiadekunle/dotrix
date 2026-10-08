import { useSearchParams } from "@/lib/navigation";

import { ResetPasswordForm } from "./reset-password-form";

export default function ResetPasswordPage() {
  const token = useSearchParams().get("token");
  return <ResetPasswordForm token={token ?? ""} />;
}
