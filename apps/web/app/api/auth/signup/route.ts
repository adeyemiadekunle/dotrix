// Create an account and sign in straight away (the backend returns a session with the new user).
import { NextResponse, type NextRequest } from "next/server";

import { API_URL, type TokenPair, passError, setSession } from "@/lib/session";

export async function POST(request: NextRequest) {
  const upstream = await fetch(`${API_URL}/v1/auth/signup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
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
