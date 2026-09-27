// Sign in: the backend checks the password; the tokens go into httpOnly cookies, never the page.
import { NextResponse, type NextRequest } from "next/server";

import { API_URL, type TokenPair, passError, setSession } from "@/lib/session";

export async function POST(request: NextRequest) {
  const upstream = await fetch(`${API_URL}/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: await request.text(),
    cache: "no-store",
  });
  if (!upstream.ok) {
    return passError(upstream);
  }
  const response = new NextResponse(null, { status: 204 });
  setSession(response, (await upstream.json()) as TokenPair);
  return response;
}
