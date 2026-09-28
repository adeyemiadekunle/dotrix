import type { Metadata } from "next";

import { MagicLinkSignIn } from "./magic-link-sign-in";

export const metadata: Metadata = { title: "Sign in" };

export default async function MagicLinkPage({ searchParams }: { searchParams: Promise<{ token?: string }> }) {
  const { token } = await searchParams;
  return <MagicLinkSignIn token={token ?? ""} />;
}
