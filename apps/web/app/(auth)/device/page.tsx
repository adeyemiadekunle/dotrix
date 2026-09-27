import type { Metadata } from "next";

import { DeviceApproval } from "./device-approval";

export const metadata: Metadata = { title: "Sign in a device" };

export default async function DevicePage({ searchParams }: { searchParams: Promise<{ code?: string }> }) {
  const { code } = await searchParams;
  return <DeviceApproval initialCode={code ?? ""} />;
}
