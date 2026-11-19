import { useSearchParams } from "@/lib/navigation";

import { AcceptInvite } from "./accept-invite";

export default function AcceptInvitePage() {
  const params = useSearchParams();
  return <AcceptInvite token={params.get("token") ?? ""} next={params.get("next")} />;
}
