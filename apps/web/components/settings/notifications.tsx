"use client";

import type { Schemas } from "@pmagent/api-client";
import { Checkbox } from "@pmagent/ui/components/checkbox";
import { Label } from "@pmagent/ui/components/label";
import { Skeleton } from "@pmagent/ui/components/skeleton";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import {
  SettingsContent,
  SettingsDescription,
  SettingsHeader,
  SettingsSection,
  SettingsTitle,
} from "@/components/settings-section";
import { api, errorMessage, unwrap } from "@/lib/api";

type Settings = Schemas["NotificationSettings"];

const KINDS: { id: Exclude<keyof Settings, "email">; label: string; description: string }[] = [
  { id: "mention", label: "Mentions", description: "Someone @mentions you in an issue comment or a chat message" },
  { id: "assigned", label: "Assigned to you", description: "Someone, or an agent, assigns you an issue" },
  { id: "finding", label: "Agent findings", description: "A run you asked for finds things to look at" },
  { id: "decided", label: "Your requests decided", description: "Someone approves or rejects changes you asked an agent for, and why" },
  { id: "watching", label: "Issues you watch", description: "An issue you watch changes or gets a comment" },
];

const ALWAYS = [
  { label: "Changes waiting for your decision", description: "An agent wants to change a document or the board" },
  { label: "Plans waiting for you", description: "An agent you asked wants you to check its plan" },
];

/** Settings → Notifications: turn mentions, assignments, and findings on or off. */
export function NotificationSettings() {
  const queryClient = useQueryClient();
  const settings = useQuery({
    queryKey: ["notification-settings"],
    queryFn: () => unwrap(api.GET("/v1/me/notification-settings")),
  });
  const update = useMutation({
    mutationFn: (body: Settings) => unwrap(api.PUT("/v1/me/notification-settings", { body })),
    onMutate: (body) => queryClient.setQueryData(["notification-settings"], body),
    onSuccess: (saved) => {
      queryClient.setQueryData(["notification-settings"], saved);
      // What shows (and counts) in Notifications follows at once.
      void queryClient.invalidateQueries({ queryKey: ["notifications"] });
    },
    onError: (e) => {
      toast.error(errorMessage(e));
      void queryClient.invalidateQueries({ queryKey: ["notification-settings"] });
    },
  });

  return (
    <SettingsSection>
      <SettingsHeader>
        <SettingsTitle>Notifications</SettingsTitle>
        <SettingsDescription>
          What shows in Notifications and on the bell, in every workspace, and how it reaches your inbox. Turning one off
          hides earlier ones too.
        </SettingsDescription>
      </SettingsHeader>
      <SettingsContent className="p-0">
        {!settings.data ? (
          <Skeleton className="m-5 h-32" />
        ) : (
          <ul className="divide-y" aria-label="Notifications you get">
            {KINDS.map((kind) => (
              <li key={kind.id} className="flex items-start gap-3 p-4">
                <Checkbox
                  id={`notify-${kind.id}`}
                  checked={settings.data[kind.id]}
                  onCheckedChange={(checked) => update.mutate({ ...settings.data!, [kind.id]: checked === true })}
                  className="mt-0.5"
                />
                <Label htmlFor={`notify-${kind.id}`} className="grid gap-0.5 font-normal">
                  <span className="font-medium">{kind.label}</span>
                  <span className="text-muted-foreground text-xs">{kind.description}</span>
                </Label>
              </li>
            ))}
            {ALWAYS.map((kind) => (
              <li key={kind.label} className="flex items-start gap-3 p-4">
                <Checkbox checked disabled aria-label={`${kind.label} (always on)`} className="mt-0.5" />
                <span className="grid gap-0.5 text-sm">
                  <span className="font-medium">{kind.label}</span>
                  <span className="text-muted-foreground text-xs">
                    {kind.description}. Always on: the agent waits until someone decides.
                  </span>
                </span>
              </li>
            ))}
          </ul>
        )}
        {settings.data && (
          <div className="grid gap-2 border-t p-4">
            <Label htmlFor="notify-email" className="font-medium">
              Email me
            </Label>
            <select
              id="notify-email"
              value={settings.data.email}
              onChange={(e) => update.mutate({ ...settings.data!, email: e.target.value as Settings["email"] })}
              className="bg-background h-9 w-full max-w-72 rounded-md border px-2 text-sm"
            >
              <option value="immediately">As things happen (one email per batch)</option>
              <option value="daily">A daily digest (08:00 UTC)</option>
              <option value="off">Never</option>
            </select>
            <p className="text-muted-foreground text-xs">
              Only what you haven&apos;t read or decided yet, and only to a verified address.
            </p>
          </div>
        )}
      </SettingsContent>
    </SettingsSection>
  );
}
