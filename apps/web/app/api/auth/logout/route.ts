// Sign out: revoke the refresh token's session on the backend, then drop the cookies.
import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { API_URL, REFRESH_COOKIE, clearSession } from "@/lib/session";

export async function POST() {
  const refreshToken = (await cookies()).get(REFRESH_COOKIE)?.value;
  if (refreshToken) {
    await fetch(`${API_URL}/v1/auth/logout`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
      cache: "no-store",
    }).catch(() => undefined); // signing out locally still works if the backend is down
  }
  const response = new NextResponse(null, { status: 204 });
  clearSession(response);
  return response;
}
