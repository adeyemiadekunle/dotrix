import type { Metadata } from "next";

import { authProviders } from "@/lib/session";

import { SignupForm } from "./signup-form";

export const metadata: Metadata = { title: "Create your account" };

export default async function SignupPage({ searchParams }: { searchParams: Promise<{ next?: string }> }) {
  const [{ next }, providers] = await Promise.all([searchParams, authProviders()]);
  return <SignupForm next={next} github={providers.github} />;
}
