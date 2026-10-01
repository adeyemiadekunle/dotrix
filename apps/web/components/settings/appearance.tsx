"use client";

import { Label } from "@pmagent/ui/components/label";
import { RadioGroup, RadioGroupItem } from "@pmagent/ui/components/radio-group";
import { Skeleton } from "@pmagent/ui/components/skeleton";
import { cn } from "@pmagent/ui/lib/utils";
import { MonitorIcon, MoonIcon, SunIcon, type LucideIcon } from "lucide-react";
import { useTheme } from "next-themes";
import { useSyncExternalStore } from "react";

import {
  SettingsContent,
  SettingsDescription,
  SettingsHeader,
  SettingsSection,
  SettingsTitle,
} from "@/components/settings-section";

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

export function Appearance() {
  const { theme, setTheme } = useTheme();
  const mounted = useMounted();
  return (
    <SettingsSection>
      <SettingsHeader>
        <SettingsTitle>Appearance</SettingsTitle>
        <SettingsDescription>System follows your device&apos;s light or dark setting. Saved in this browser.</SettingsDescription>
      </SettingsHeader>
      <SettingsContent>
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
      </SettingsContent>
    </SettingsSection>
  );
}
