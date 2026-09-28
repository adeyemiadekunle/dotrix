"use client";

import { Badge } from "@pmagent/ui/components/badge";
import { Button } from "@pmagent/ui/components/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@pmagent/ui/components/card";
import { Label } from "@pmagent/ui/components/label";
import { RadioGroup, RadioGroupItem } from "@pmagent/ui/components/radio-group";
import { Skeleton } from "@pmagent/ui/components/skeleton";
import { cn } from "@pmagent/ui/lib/utils";
import { useMutation } from "@tanstack/react-query";
import { MonitorIcon, MoonIcon, SunIcon, type LucideIcon } from "lucide-react";
import { useTheme } from "next-themes";
import { useSyncExternalStore } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/app-shell";
import { api, errorMessage, unwrap } from "@/lib/api";
import { useMe } from "@/lib/queries";

import { CalendarFeed } from "./calendar";
import { Devices } from "./devices";

const THEMES: { value: string; label: string; icon: LucideIcon; preview: string }[] = [
  { value: "system", label: "System", icon: MonitorIcon, preview: "bg-linear-to-r from-white from-50% to-neutral-900 to-50%" },
  { value: "light", label: "Light", icon: SunIcon, preview: "bg-white" },
  { value: "dark", label: "Dark", icon: MoonIcon, preview: "bg-neutral-900" },
];

// The chosen theme is only known in the browser; render the picker after hydration.
const subscribe = () => () => {};
function useMounted() {
  return useSyncExternalStore(subscribe, () => true, () => false);
}

function Appearance() {
  const { theme, setTheme } = useTheme();
  const mounted = useMounted();
  return (
    <Card>
      <CardHeader>
        <CardTitle>Appearance</CardTitle>
        <CardDescription>System follows your device&apos;s light or dark setting. Saved in this browser.</CardDescription>
      </CardHeader>
      <CardContent>
        {mounted ? (
          <RadioGroup value={theme ?? "system"} onValueChange={setTheme} className="grid grid-cols-3 gap-3 sm:max-w-md">
            {THEMES.map(({ value, label, icon: Icon, preview }) => (
              <Label
                key={value}
                className="has-[[data-state=checked]]:border-primary has-[[data-state=checked]]:ring-primary/20 flex cursor-pointer flex-col gap-2 rounded-lg border p-2 font-normal has-[[data-state=checked]]:ring-2"
              >
                <RadioGroupItem value={value} className="sr-only" />
                <span className={cn("h-14 w-full rounded-md border", preview)} aria-hidden />
                <span className="flex items-center gap-1.5 text-sm">
                  <Icon className="size-4" />
                  {label}
                </span>
              </Label>
            ))}
          </RadioGroup>
        ) : (
          <Skeleton className="h-24 sm:max-w-md" />
        )}
      </CardContent>
    </Card>
  );
}

function Profile() {
  const me = useMe();
  const resend = useMutation({
    mutationFn: () => unwrap(api.POST("/v1/auth/verify-email/resend")),
    onSuccess: () => toast.success("Verification email sent"),
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle>Profile</CardTitle>
        <CardDescription>How you appear to your team.</CardDescription>
      </CardHeader>
      <CardContent>
        {me.data ? (
          <dl className="grid gap-3 text-sm">
            <div className="grid grid-cols-[6rem_1fr] items-center gap-4">
              <dt className="text-muted-foreground">Name</dt>
              <dd>{me.data.display_name}</dd>
            </div>
            <div className="grid grid-cols-[6rem_1fr] items-center gap-4">
              <dt className="text-muted-foreground">Email</dt>
              <dd className="flex flex-wrap items-center gap-2">
                {me.data.email}
                {me.data.email_verified ? (
                  <Badge variant="secondary">Verified</Badge>
                ) : (
                  <>
                    <Badge variant="outline" className="border-warning text-warning-foreground">
                      Not verified
                    </Badge>
                    <Button size="sm" variant="link" className="h-auto p-0" disabled={resend.isPending} onClick={() => resend.mutate()}>
                      Resend link
                    </Button>
                  </>
                )}
              </dd>
            </div>
          </dl>
        ) : (
          <Skeleton className="h-12" />
        )}
      </CardContent>
    </Card>
  );
}

export default function SettingsPage() {
  return (
    <>
      <PageHeader title="Settings" />
      <div className="flex max-w-3xl flex-col gap-4 p-4 md:p-6">
        <Profile />
        <Appearance />
        <CalendarFeed />
        <Devices />
      </div>
    </>
  );
}
