import Link from "next/link";
import type { ReactNode } from "react";

import { Logo } from "@/components/logo";

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="bg-muted/40 flex min-h-svh flex-col items-center justify-center gap-6 p-4 md:p-10">
      <Link href="/" aria-label="pmagent home">
        <Logo className="text-lg" />
      </Link>
      <div className="w-full max-w-sm">{children}</div>
    </div>
  );
}
