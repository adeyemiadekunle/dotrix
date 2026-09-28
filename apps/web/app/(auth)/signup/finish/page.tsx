import type { Metadata } from "next";

import { FinishSignup } from "./finish-signup";

export const metadata: Metadata = { title: "Create your account" };

export default async function FinishSignupPage({ searchParams }: { searchParams: Promise<{ token?: string }> }) {
  const { token } = await searchParams;
  return <FinishSignup token={token ?? ""} />;
}
