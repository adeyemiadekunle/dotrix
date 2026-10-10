import { Button } from "@dotrix/ui/components/button";
import { Input } from "@dotrix/ui/components/input";
import { Label } from "@dotrix/ui/components/label";
import { RadioGroup, RadioGroupItem } from "@dotrix/ui/components/radio-group";
import { Skeleton } from "@dotrix/ui/components/skeleton";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarPlusIcon, CopyIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { SettingsContent, SettingsDescription, SettingsHeader, SettingsSection, SettingsTitle } from "@/components/settings-section";
import { ApiError, api, errorMessage, unwrap } from "@/lib/api";

type Scope = "mine" | "all";

const SCOPES: { value: Scope; label: string; description: string }[] = [
  { value: "mine", label: "My issues", description: "Assigned to you, or that you watch" },
  { value: "all", label: "Everything", description: "Every issue with a date in the projects you can see" },
];

const KEY = ["calendar-feed"];

function when(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString() : "not yet";
}

/** The personal calendar feed (FR-32): issue due and scheduled dates in any calendar app. */
export function CalendarFeed() {
  const queryClient = useQueryClient();
  const [url, setUrl] = useState<string | null>(null); // shown once, right after turning it on
  const [scope, setScope] = useState<Scope>("mine");
  const feed = useQuery({
    queryKey: KEY,
    queryFn: () =>
      unwrap(api.GET("/v1/me/calendar")).catch((e) => {
        if (e instanceof ApiError && e.status === 404) return null; // off
        throw e;
      }),
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: KEY });

  const create = useMutation({
    mutationFn: (s: Scope) => unwrap(api.POST("/v1/me/calendar", { body: { scope: s } })),
    onSuccess: (created) => {
      setUrl(created.url);
      return refresh();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const update = useMutation({
    mutationFn: (s: Scope) => unwrap(api.PATCH("/v1/me/calendar", { body: { scope: s } })),
    onSuccess: refresh,
    onError: (e) => toast.error(errorMessage(e)),
  });
  const remove = useMutation({
    mutationFn: () => unwrap(api.DELETE("/v1/me/calendar")),
    onSuccess: () => {
      setUrl(null);
      toast.success("Calendar feed turned off");
      return refresh();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  async function copy(text: string) {
    await navigator.clipboard.writeText(text);
    toast.success("Calendar link copied");
  }

  const current = feed.data;
  const shownScope = current ? (current.scope as Scope) : scope;

  return (
    <SettingsSection>
      <SettingsHeader>
        <SettingsTitle>Calendar</SettingsTitle>
        <SettingsDescription>Subscribe to your issues&apos; due and scheduled dates in Google Calendar, Apple Calendar, or Outlook.</SettingsDescription>
      </SettingsHeader>
      <SettingsContent className="grid gap-4">
        {feed.isLoading ? (
          <Skeleton className="h-24" />
        ) : (
          <>
            <RadioGroup
              value={shownScope}
              onValueChange={(v) => (current ? update.mutate(v as Scope) : setScope(v as Scope))}
              className="grid gap-2 sm:grid-cols-2"
              aria-label="What the calendar shows"
            >
              {SCOPES.map((s) => (
                <Label
                  key={s.value}
                  className="has-[[data-state=checked]]:border-primary flex cursor-pointer items-start gap-3 rounded-md border p-3 font-normal"
                >
                  <RadioGroupItem value={s.value} className="mt-0.5" disabled={update.isPending} />
                  <span className="grid gap-1">
                    <span className="font-medium">{s.label}</span>
                    <span className="text-muted-foreground text-xs">{s.description}</span>
                  </span>
                </Label>
              ))}
            </RadioGroup>

            {url && (
              <div className="grid gap-2">
                <Label htmlFor="calendar-url">Your calendar link</Label>
                <div className="flex gap-2">
                  <Input id="calendar-url" readOnly value={url} className="font-mono text-xs" onFocus={(e) => e.target.select()} />
                  <Button variant="outline" size="icon" aria-label="Copy calendar link" onClick={() => void copy(url)}>
                    <CopyIcon />
                  </Button>
                </div>
                <p className="text-muted-foreground text-xs">
                  Copy it now: it&apos;s shown only once. In your calendar app, add a calendar &quot;from URL&quot; and paste it. Anyone with the link can see
                  these issues&apos; keys, titles, and dates, so keep it private.
                </p>
                <Button variant="outline" size="sm" className="w-fit" asChild>
                  <a href={url.replace(/^https?:/, "webcal:")}>
                    <CalendarPlusIcon /> Open in calendar app
                  </a>
                </Button>
              </div>
            )}

            {current ? (
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-muted-foreground mr-auto text-sm">
                  On since {when(current.created_at)} · last fetched {when(current.last_used_at)}
                </p>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={create.isPending}
                  onClick={() => {
                    if (window.confirm("Get a new link? The current one stops working in every calendar using it.")) {
                      create.mutate(current.scope as Scope);
                    }
                  }}
                >
                  New link
                </Button>
                <Button variant="outline" size="sm" disabled={remove.isPending} onClick={() => remove.mutate()}>
                  Turn off
                </Button>
              </div>
            ) : (
              <Button className="w-fit" disabled={create.isPending} onClick={() => create.mutate(scope)}>
                <CalendarPlusIcon /> Turn on calendar feed
              </Button>
            )}
          </>
        )}
      </SettingsContent>
    </SettingsSection>
  );
}
