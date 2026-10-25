import { useEffect, useState } from "react";

import { useRouter, useSearchParams } from "@/lib/navigation";

import { DeviceApproval, pendingDeviceCode, rememberDeviceCode } from "./device-approval";

export default function DevicePage() {
  const fromUrl = useSearchParams().get("code");
  const router = useRouter();
  // The code a terminal's link carried: kept in this tab, and out of the address bar (and so out
  // of history and the sign-in redirect) as soon as the page has read it.
  const [code] = useState(() => (fromUrl ? rememberDeviceCode(fromUrl) : pendingDeviceCode()));
  useEffect(() => {
    if (fromUrl) router.replace("/device", { scroll: false });
  }, [fromUrl, router]);
  return <DeviceApproval initialCode={code} />;
}
