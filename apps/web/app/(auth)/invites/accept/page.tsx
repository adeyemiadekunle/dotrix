import type { Metadata } from "next";

import { AcceptInvite } from "./accept-invite";

export const metadata: Metadata = { title: "Join a workspace" };

export default async function AcceptInvitePage({ searchParams }: { searchParams: Promise<{ token?: string }> }) {
  const { token } = await searchParams;
  return <AcceptInvite token={token ?? ""} />;
}
