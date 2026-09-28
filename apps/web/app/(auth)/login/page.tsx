import type { Metadata } from "next";

import { LoginForm } from "./login-form";

export const metadata: Metadata = { title: "Sign in" };

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ next?: string; link?: string }> }) {
  const { next, link } = await searchParams;
  return <LoginForm next={next} emailLink={link === "1"} />;
}
