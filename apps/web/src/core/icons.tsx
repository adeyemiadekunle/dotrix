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

/* dotrix's mark: a 3×3 dot matrix in green, no background; the middle dot (the fifth) is bigger
   and darker, the eight around it lighter. In a 24-unit box. The wordmark follows the text colour. */
export const MARK_GREEN = "#3D8B5C";
const GRID = [3.5, 12, 20.5];
export function Dots() {
  return (
    <>
      {GRID.flatMap((y) =>
        GRID.map((x) => {
          const mid = x === 12 && y === 12;
          return <circle key={`${x}-${y}`} cx={x} cy={y} r={mid ? 3.6 : 1.9} fill={MARK_GREEN} fillOpacity={mid ? 1 : 0.62} />;
        }),
      )}
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
    <svg width={px} height={px} viewBox="0 0 24 24" aria-hidden="true">
      <Dots />
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
