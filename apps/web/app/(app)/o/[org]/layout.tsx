"use client";

import { Badge } from "@pmagent/ui/components/badge";
import { cn } from "@pmagent/ui/lib/utils";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { PageHeader } from "@/components/app-shell";
import { NotFound } from "@/components/states";
import { ORG_ROLE_LABELS, useCurrentOrg } from "@/lib/orgs";

const TABS = [
  { href: "", label: "Workspaces" },
  { href: "/members", label: "Members" },
  { href: "/settings", label: "Settings" },
];

export default function OrgLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { org, notFound } = useCurrentOrg();
  if (notFound) return <NotFound what="organisation" />;
  const base = org ? `/o/${org.slug}` : "";
  return (
    <>
      <PageHeader
        parent="Organisation"
        title={org?.name ?? "…"}
        actions={org && <Badge variant="outline">{ORG_ROLE_LABELS[org.role]}</Badge>}
      />
      <nav className="flex gap-4 overflow-x-auto border-b px-4 text-sm md:px-6" aria-label="Organisation">
        {TABS.map((tab) => {
          const href = `${base}${tab.href}`;
          const active = pathname === href;
          return (
            <Link
              key={tab.label}
              href={href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "-mb-px shrink-0 border-b-2 border-transparent py-2.5 transition-colors",
                active ? "border-foreground font-medium" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {tab.label}
            </Link>
          );
        })}
      </nav>
      {children}
    </>
  );
}
