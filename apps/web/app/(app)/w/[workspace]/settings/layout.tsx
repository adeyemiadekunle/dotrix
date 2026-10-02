"use client";

import { cn } from "@pmagent/ui/lib/utils";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, type ReactNode } from "react";

import { PageHeader } from "@/components/app-shell";
import { NotFound } from "@/components/states";
import { canManageProjects } from "@/lib/labels";
import { useCurrentWorkspace } from "@/lib/queries";

interface Item {
  label: string;
  /** Under /w/[ws]/settings; "" is General. Null: planned, shown as Later. */
  path: string | null;
}

/** Settings in one place: your account, then this workspace. */
export default function SettingsLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { workspace, notFound } = useCurrentWorkspace();
  const nav = useRef<HTMLDivElement>(null);
  // On phones the nav is a scrolling row: keep the current page's item in view.
  useEffect(() => {
    nav.current?.querySelector("[aria-current=page]")?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [pathname, workspace]);
  if (notFound) return <NotFound what="workspace" />;

  const base = workspace ? `/w/${workspace.slug}/settings` : "";
  const admin = canManageProjects(workspace?.role);
  const organisation = workspace?.kind === "organization";
  const groups: { title: string; items: Item[] }[] = [
    {
      title: "Account",
      items: [
        { label: "Profile", path: "profile" },
        { label: "Appearance", path: "appearance" },
        { label: "Notifications", path: "notifications" },
        { label: "Devices and tokens", path: "devices" },
        { label: "Calendar", path: "calendar" },
      ],
    },
    {
      title: workspace?.name ?? "Workspace",
      items: [
        { label: "General", path: "" },
        { label: "Members", path: "members" },
        // In a personal workspace this is where it turns into an organisation (which invites).
        ...(admin ? [{ label: "Invites", path: "invites" }] : []),
        ...(organisation ? [{ label: "What members can do", path: "permissions" }] : []),
        ...(admin
          ? [
              { label: "Agents", path: "agents" },
              { label: "Audit log", path: "audit" },
            ]
          : []),
      ],
    },
  ];

  function isActive(path: string) {
    const href = path ? `${base}/${path}` : base;
    return path ? pathname === href || pathname.startsWith(`${href}/`) : pathname === href;
  }

  return (
    <>
      <PageHeader title="Settings" parent={workspace?.name} />
      <div className="flex w-full max-w-6xl flex-col gap-6 p-4 md:flex-row md:gap-10 md:p-8">
        <nav aria-label="Settings" className="shrink-0 md:sticky md:top-20 md:w-52 md:self-start">
          {/* A scrolling row on phones, a column beside the page from md up. */}
          <div ref={nav} className="-mx-4 flex gap-6 overflow-x-auto px-4 md:mx-0 md:flex-col md:px-0">
            {groups.map((group) => (
              <div key={group.title} className="flex shrink-0 items-center gap-1 md:flex-col md:items-stretch">
                <p className="text-muted-foreground hidden truncate px-2 pb-1 text-xs font-semibold md:block">{group.title}</p>
                {group.items.map((item) =>
                  item.path === null ? (
                    <span
                      key={item.label}
                      aria-disabled
                      className="text-muted-foreground flex shrink-0 items-center gap-2 rounded-md px-2 py-1.5 text-sm"
                    >
                      {item.label}
                      <span className="bg-warning-muted text-warning-foreground ml-auto rounded-full px-1.5 text-[10px] font-semibold">
                        Later
                      </span>
                    </span>
                  ) : (
                    <Link
                      key={item.label}
                      href={item.path ? `${base}/${item.path}` : base}
                      aria-current={isActive(item.path) ? "page" : undefined}
                      className={cn(
                        "shrink-0 rounded-md px-2 py-1.5 text-sm whitespace-nowrap transition-colors",
                        isActive(item.path)
                          ? "bg-muted text-foreground font-medium"
                          : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                      )}
                    >
                      {item.label}
                    </Link>
                  ),
                )}
              </div>
            ))}
          </div>
        </nav>
        <div className="grid min-w-0 flex-1 content-start gap-8">{children}</div>
      </div>
    </>
  );
}
