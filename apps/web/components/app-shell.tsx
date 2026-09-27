"use client";

import { Button } from "@pmagent/ui/components/button";
import { Separator } from "@pmagent/ui/components/separator";
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@pmagent/ui/components/sidebar";
import { useMutation } from "@tanstack/react-query";
import { MailWarningIcon } from "lucide-react";
import type { ReactNode } from "react";
import { toast } from "sonner";

import { AppSidebar } from "@/components/app-sidebar";
import { api, errorMessage, unwrap } from "@/lib/api";
import { useMe } from "@/lib/queries";

function VerifyEmailBanner() {
  const me = useMe();
  const resend = useMutation({
    mutationFn: () => unwrap(api.POST("/v1/auth/verify-email/resend")),
    onSuccess: () => toast.success("Verification email sent"),
    onError: (e) => toast.error(errorMessage(e)),
  });
  if (!me.data || me.data.email_verified) return null;
  return (
    <div className="bg-warning-muted text-warning-foreground flex items-center gap-2 border-b px-4 py-2 text-sm">
      <MailWarningIcon className="size-4 shrink-0" />
      <span className="flex-1">Confirm your email address using the link we sent to {me.data.email}.</span>
      <Button size="sm" variant="ghost" disabled={resend.isPending} onClick={() => resend.mutate()}>
        Resend
      </Button>
    </div>
  );
}

/** The signed-in frame: sidebar, a top bar with the page title, and the page. */
export function AppShell({ children }: { children: ReactNode }) {
  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset>
        <VerifyEmailBanner />
        {children}
      </SidebarInset>
    </SidebarProvider>
  );
}

/** Each page's top bar: sidebar toggle, title (with optional breadcrumb before it), and actions. */
export function PageHeader({ title, parent, actions }: { title: ReactNode; parent?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="bg-background sticky top-0 z-10 flex h-14 shrink-0 items-center gap-2 border-b px-4">
      <SidebarTrigger className="-ml-1" />
      <Separator orientation="vertical" className="mr-2 data-[orientation=vertical]:h-4" />
      <div className="flex min-w-0 flex-1 items-center gap-1.5 text-sm">
        {parent && (
          <>
            <span className="text-muted-foreground truncate">{parent}</span>
            <span className="text-muted-foreground">/</span>
          </>
        )}
        <h1 className="truncate font-medium">{title}</h1>
      </div>
      {actions}
    </header>
  );
}
