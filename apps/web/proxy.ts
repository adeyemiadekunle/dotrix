// Optimistic sign-in check: pages other than the public auth pages need a session cookie.
// The real check is the backend's; this only saves a round trip to a page that would 401.
import { NextResponse, type NextRequest } from "next/server";

const PUBLIC = ["/login", "/signup", "/forgot-password", "/reset-password", "/verify-email", "/magic-link"];

export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const signedIn = request.cookies.has("pm_refresh");
  const isPublic = PUBLIC.some((p) => pathname === p || pathname.startsWith(`${p}/`));

  if (!signedIn && !isPublic) {
    const login = new URL("/login", request.url);
    if (pathname !== "/") login.searchParams.set("next", `${pathname}${search}`);
    return NextResponse.redirect(login);
  }
  if (signedIn && (pathname === "/login" || pathname === "/signup")) {
    return NextResponse.redirect(new URL(request.nextUrl.searchParams.get("next") ?? "/", request.url));
  }
  return NextResponse.next();
}

export const config = {
  // Everything except the API routes (they answer 401 themselves) and Next's own files.
  matcher: ["/((?!api/|_next/static|_next/image|favicon.ico).*)"],
};
