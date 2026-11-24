// An agent's face, as in the app (apps/web/src/ui/face.tsx): a disc in its hue with calm eyes and a smile.
const EYES = "M10.6 15.4q1.4-1.6 2.8 0M18.6 15.4q1.4-1.6 2.8 0";
const MOUTH = "M13.6 19.6q2.4 1.8 4.8 0";

export function Face({ c, size = 40 }: { c: string; size?: number }) {
  return (
    <svg className="face" width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <circle cx="16" cy="16" r="15" fill={`color-mix(in srgb, ${c} 14%, var(--face-bg, #ffffff))`} />
      <circle cx="16" cy="16" r="14.5" fill="none" stroke={`color-mix(in srgb, ${c} 42%, var(--face-bg, #ffffff))`} strokeWidth="1" />
      <path d={EYES} fill="none" stroke={c} strokeWidth="1.6" strokeLinecap="round" />
      <path d={MOUTH} fill="none" stroke={c} strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

/** dotrix's mark: a 3×3 dot matrix, the middle dot bigger and darker. */
export function Mark({ size = 22 }: { size?: number }) {
  const grid = [3.5, 12, 20.5];
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      {grid.flatMap((y) =>
        grid.map((x) => {
          const mid = x === 12 && y === 12;
          return <circle key={`${x}-${y}`} cx={x} cy={y} r={mid ? 3.6 : 1.9} fill="#3D8B5C" fillOpacity={mid ? 1 : 0.62} />;
        }),
      )}
    </svg>
  );
}
