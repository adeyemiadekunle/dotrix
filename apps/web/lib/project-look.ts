// How a project looks: its colour, icon, and status. Set in project settings;
// a project without them looks like its key (a letter, a colour picked from the key).
import type { Schemas } from "@dotrix/api-client";
import {
  BriefcaseIcon,
  BuildingsIcon,
  CodeIcon,
  DiamondsFourIcon,
  FolderIcon,
  GlobeIcon,
  HeartIcon,
  StackIcon,
  GridFourIcon,
  MegaphoneIcon,
  PaletteIcon,
  RocketIcon,
  DeviceMobileIcon,
  SparkleIcon,
  TargetIcon,
  LightningIcon,
  type Icon,
} from "@phosphor-icons/react";

export type ProjectColor = Schemas["ProjectColor"];
export type ProjectStatus = Schemas["ProjectStatus"];

/** The project colours, readable as text on their own 16% tint in both themes. */
export const PROJECT_COLORS: Record<ProjectColor, string> = {
  indigo: "#5a67d8",
  blue: "#3b82c4",
  violet: "#8662c9",
  teal: "#23918a",
  rose: "#c54b78",
  amber: "#c48a1e",
  green: "#3d8e5f",
  slate: "#6b7280",
};

const BY_KEY: ProjectColor[] = ["teal", "violet", "blue", "amber", "rose", "green", "indigo", "slate"];

/** The project's colour, or one that follows its key. */
export function projectColor(key: string, color?: ProjectColor | null): string {
  if (color) return PROJECT_COLORS[color];
  let hash = 0;
  for (const ch of key) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return PROJECT_COLORS[BY_KEY[hash % BY_KEY.length]!];
}

/** The icons a project can have (the API accepts these names). */
export const PROJECT_ICONS: Record<string, Icon> = {
  globe: GlobeIcon,
  smartphone: DeviceMobileIcon,
  megaphone: MegaphoneIcon,
  rocket: RocketIcon,
  component: DiamondsFourIcon,
  "building-2": BuildingsIcon,
  "layout-grid": GridFourIcon,
  palette: PaletteIcon,
  code: CodeIcon,
  briefcase: BriefcaseIcon,
  target: TargetIcon,
  layers: StackIcon,
  zap: LightningIcon,
  heart: HeartIcon,
  folder: FolderIcon,
  sparkles: SparkleIcon,
};

export const PROJECT_STATUSES: { value: ProjectStatus; label: string; dot: string }[] = [
  { value: "planning", label: "Planning", dot: "bg-label-gray" },
  { value: "active", label: "In progress", dot: "bg-info" },
  { value: "on_hold", label: "On hold", dot: "bg-warning" },
  { value: "completed", label: "Completed", dot: "bg-success" },
];

/** The sidebar's dot: red when it's at risk or off track, else its status. */
export function projectDot(project: Pick<Schemas["ProjectRead"], "status" | "health">): { dot: string; label: string } {
  if (project.health === "at_risk" || project.health === "off_track") {
    return { dot: "bg-destructive", label: project.health === "at_risk" ? "At risk" : "Off track" };
  }
  const status = PROJECT_STATUSES.find((s) => s.value === project.status) ?? PROJECT_STATUSES[1]!;
  return { dot: status.dot, label: status.label };
}
