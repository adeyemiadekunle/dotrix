// Icons: <Ic n={name} s={size} />, Phosphor's regular weight (https://phosphoricons.com): any Phosphor
// name, or one of dotrix's own names (icons-plugin.ts ALIASES), bundled only if src/ names it.
import type { CSSProperties } from "react";
import { ICONS } from "virtual:icons";

import type { Workspace } from "../data/types";

// An unknown name: Phosphor's square, so a missing icon still takes its place (in the 256-unit box).
const FALLBACK = '<path d="M208,32H48A16,16,0,0,0,32,48V208a16,16,0,0,0,16,16H208a16,16,0,0,0,16-16V48A16,16,0,0,0,208,32Zm0,176H48V48H208V208Z"/>';

export function Ic({ n, s = 16, cls = "", style }: { n: string; s?: number; cls?: string; style?: CSSProperties }) {
  return (
    <svg
      className={`i ${cls}`}
      width={s}
      height={s}
      viewBox="0 0 256 256"
      fill="currentColor"
      aria-hidden="true"
      style={style}
      dangerouslySetInnerHTML={{ __html: ICONS[n] ?? FALLBACK }}
    />
  );
}

/* dotrix's mark: a 3×3 dot matrix in green, no background; the middle dot (the fifth) is bigger
   and darker, the eight around it lighter. In a 24-unit box. The wordmark follows the text colour. */
const MARK_GREEN = "#3D8B5C";
const GRID = [3.5, 12, 20.5];
function Dots() {
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

export function DotsLoader({ px = 44 }: { px?: number }) {
  return (
    <svg className="dots-loader" width={px} height={px} viewBox="0 0 24 24" role="img" aria-label="Loading">
      {GRID.flatMap((y) =>
        GRID.map((x) => {
          const mid = x === 12 && y === 12;
          return (
            <circle
              key={`${x}-${y}`}
              className="dots-loader-dot"
              style={{ animationDelay: `${Math.hypot(x - 12, y - 12) * 110}ms` }}
              cx={x}
              cy={y}
              r={mid ? 3.6 : 1.9}
              fill={MARK_GREEN}
              fillOpacity={mid ? 1 : 0.62}
            />
          );
        }),
      )}
    </svg>
  );
}

export function Logo({ h = 22 }: { h?: number }) {
  return (
    <svg className="logo" height={h} width={Math.round((h * 92) / 24)} viewBox="0 0 92 24" role="img" aria-label="dotrix">
      <Dots />
      <text
        x="31"
        y="18.2"
        fill="currentColor"
        fontSize="19"
        fontWeight="650"
        letterSpacing="-0.6"
        style={{ fontFamily: "var(--font-sans, 'Geist Variable', sans-serif)" }}
      >
        dotrix
      </text>
    </svg>
  );
}
function Mark({ px = 22 }: { px?: number }) {
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
    <span className="ws-logo" style={{ "--c": w.c, width: px, height: px, fontSize: Math.max(9, Math.round(px * 0.46)) } as CSSProperties}>
      {w.name[0]}
    </span>
  );
}
