import { useSearchParams } from "@/lib/navigation";

import { AcceptInvite } from "./accept-invite";

export default function AcceptInvitePage() {
  const token = useSearchParams().get("token");
  return <AcceptInvite token={token ?? ""} />;
}
