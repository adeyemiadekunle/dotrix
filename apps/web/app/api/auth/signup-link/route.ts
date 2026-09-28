// Create an account from an emailed sign-up link and sign in: the backend checks the one-time
// token; the session goes into httpOnly cookies, never the page.
import { NextResponse, type NextRequest } from "next/server";

import { API_URL, type TokenPair, clientHeaders, passError, setSession } from "@/lib/session";

export async function POST(request: NextRequest) {
  const upstream = await fetch(`${API_URL}/v1/auth/magic-link/signup`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...clientHeaders(request) },
    body: await request.text(),
    cache: "no-store",
  });
  if (!upstream.ok) {
    return passError(upstream);
  }
  const { user, tokens } = (await upstream.json()) as { user: unknown; tokens: TokenPair };
  const response = NextResponse.json(user, { status: 201 });
  setSession(response, tokens);
  return response;
}
