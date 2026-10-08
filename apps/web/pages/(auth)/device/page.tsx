import { useSearchParams } from "@/lib/navigation";

import { DeviceApproval } from "./device-approval";

export default function DevicePage() {
  const code = useSearchParams().get("code");
  return <DeviceApproval initialCode={code ?? ""} />;
}
