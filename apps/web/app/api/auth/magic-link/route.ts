// Sign in with an emailed link: the backend checks the one-time token; the session goes into
// httpOnly cookies, never the page.
import { NextResponse, type NextRequest } from "next/server";

import { API_URL, type TokenPair, clientHeaders, passError, setSession } from "@/lib/session";

export async function POST(request: NextRequest) {
  const upstream = await fetch(`${API_URL}/v1/auth/magic-link/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...clientHeaders(request) },
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
