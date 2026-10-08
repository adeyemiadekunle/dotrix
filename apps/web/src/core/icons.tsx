// Gr8r's icons (gr8r-studio/src/core/icons.js): ic(name, size, class) as <Ic>, any Lucide name,
// bundled only if src/ names it (icons-plugin.ts). The logo is Gr8r's, for now.
import type { CSSProperties } from "react";
import { ICONS } from "virtual:icons";

import type { Workspace } from "../data/types";

const FALLBACK = '<rect x="5" y="5" width="14" height="14" rx="3"/>';

export function Ic({ n, s = 16, cls = "", style }: { n: string; s?: number; cls?: string; style?: CSSProperties }) {
  return (
    <svg
      className={`i ${cls}`}
      width={s}
      height={s}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={style}
      dangerouslySetInnerHTML={{ __html: ICONS[n] ?? FALLBACK }}
    />
  );
}

/* dotrix's mark: a 3×3 dot matrix whose middle dot (the fifth) is bigger, in a 24-unit box.
   The wordmark follows the theme's text colour; the app icon is the white matrix on black. */
const GRID = [4, 12, 20];
export function Dots({ fill = "currentColor" }: { fill?: string }) {
  return (
    <>
      {GRID.flatMap((y) => GRID.map((x) => <circle key={`${x}-${y}`} cx={x} cy={y} r={x === 12 && y === 12 ? 3.9 : 2.3} fill={fill} />))}
    </>
  );
}

export function Logo({ h = 22 }: { h?: number }) {
  return (
    <svg className="logo" height={h} width={Math.round((h * 92) / 24)} viewBox="0 0 92 24" role="img" aria-label="dotrix">
      <Dots />
      <text x="31" y="18.2" fill="currentColor" fontSize="19" fontWeight="650" letterSpacing="-0.6" style={{ fontFamily: "var(--font-sans, 'Geist Variable', sans-serif)" }}>
        dotrix
      </text>
    </svg>
  );
}
export function Mark({ px = 22 }: { px?: number }) {
  return (
    <svg width={px} height={px} viewBox="-6 -6 36 36" aria-hidden="true">
      <rect x="-6" y="-6" width="36" height="36" fill="#000" />
      <Dots fill="#fff" />
    </svg>
  );
}
export function WsLogo({ w, px = 22 }: { w: Pick<Workspace, "name" | "c" | "brand">; px?: number }) {
  return w.brand ? (
    <span className="ws-logo brand" style={{ width: px, height: px }}>
      <Mark px={px} />
    </span>
  ) : (
    <span
      className="ws-logo"
      style={{ "--c": w.c, width: px, height: px, fontSize: Math.max(9, Math.round(px * 0.46)) } as CSSProperties}
    >
      {w.name[0]}
    </span>
  );
}
