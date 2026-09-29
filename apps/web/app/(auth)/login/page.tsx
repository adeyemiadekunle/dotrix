import type { Metadata } from "next";

import { authProviders } from "@/lib/session";

import { LoginForm } from "./login-form";

export const metadata: Metadata = { title: "Sign in" };

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string; link?: string; error?: string }>;
}) {
  const [{ next, link, error }, providers] = await Promise.all([searchParams, authProviders()]);
  return <LoginForm next={next} emailLink={link === "1"} github={providers.github} initialError={error} />;
}
