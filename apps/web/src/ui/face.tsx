// An agent's face: a glossy sphere in its colour with eyes and a mouth that show what it's
// doing. Idle is calm, working is focused, needs-you looks up expectantly, blocked frowns.
// Pure SVG, so it scales from the 18px sidebar dot to the large one on Home.
import { useId } from "react";

export type Mood = "idle" | "working" | "thinking" | "needs" | "blocked" | "offline";

const EYES: Record<Mood, string> = {
  idle: "M10.6 15.4q1.4-1.6 2.8 0M18.6 15.4q1.4-1.6 2.8 0", // relaxed arcs
  working: "M10.4 15.2h3.2M18.4 15.2h3.2", // focused
  thinking: "M10.8 13.8a1.2 1.2 0 1 0 2.4 0a1.2 1.2 0 1 0-2.4 0M18.8 13.8a1.2 1.2 0 1 0 2.4 0a1.2 1.2 0 1 0-2.4 0", // looking up
  needs: "M10.6 15a1.4 1.4 0 1 0 2.8 0a1.4 1.4 0 1 0-2.8 0M18.6 15a1.4 1.4 0 1 0 2.8 0a1.4 1.4 0 1 0-2.8 0",
  blocked: "M10.4 14.4l3 1.2M21.6 14.4l-3 1.2",
  offline: "M10.6 15.6h2.8M18.6 15.6h2.8",
};
const MOUTH: Record<Mood, string> = {
  idle: "M13.6 19.6q2.4 1.8 4.8 0",
  working: "M14.4 19.8h3.2",
  thinking: "M14.6 20.2q1.4-.8 2.8 0",
  needs: "M13.6 19.2h4.8q-.5 2.8-2.4 2.8t-2.4-2.8z", // an open, expectant smile
  blocked: "M13.6 21q2.4-1.8 4.8 0",
  offline: "M14.4 20h3.2",
};

/** `c` is the agent's colour; `size` in px. */
export function Face({ c, size = 20, mood = "idle", label }: { c: string; size?: number; mood?: Mood; label?: string }) {
  const id = useId().replace(/:/g, "");
  const ink = "#2B2A27"; // the features stay dark on every colour, in both themes
  return (
    <svg className={`face face-${mood}`} width={size} height={size} viewBox="0 0 32 32" role={label ? "img" : undefined} aria-label={label} aria-hidden={label ? undefined : true}>
      <defs>
        <radialGradient id={`g${id}`} cx="38%" cy="30%" r="75%">
          <stop offset="0" stopColor="#fff" stopOpacity={mood === "offline" ? 0.25 : 0.7} />
          <stop offset=".35" stopColor={mood === "offline" ? "#8A867E" : c} />
          <stop offset="1" stopColor={mood === "offline" ? "#5F5C56" : c} stopOpacity=".92" />
        </radialGradient>
      </defs>
      <circle cx="16" cy="16" r="15" fill={`url(#g${id})`} />
      <circle cx="16" cy="16" r="14.5" fill="none" stroke="#000" strokeOpacity=".08" />
      <path className="face-eyes" d={EYES[mood]} fill={mood === "needs" || mood === "thinking" ? ink : "none"} stroke={ink} strokeWidth="1.5" strokeLinecap="round" opacity=".85" />
      <path className="face-mouth" d={MOUTH[mood]} fill={mood === "needs" ? ink : "none"} stroke={ink} strokeWidth="1.4" strokeLinecap="round" opacity=".8" />
    </svg>
  );
}
