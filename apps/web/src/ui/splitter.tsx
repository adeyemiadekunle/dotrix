// A drag handle between two areas: drag it, or focus it and use the arrow keys. Sizes a person sets
// are kept in this browser (a convenience: they come back to the defaults when storage is gone).
import {
  useEffect,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";

export function Splitter({
  dir,
  onDrag,
  label,
  className = "",
}: {
  dir: "col" | "row";
  onDrag: (delta: number) => void;
  label: string;
  className?: string;
}) {
  const start = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    e.preventDefault();
    let last = dir === "col" ? e.clientX : e.clientY;
    const move = (ev: PointerEvent) => {
      const now = dir === "col" ? ev.clientX : ev.clientY;
      if (now !== last) onDrag(now - last);
      last = now;
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      document.body.classList.remove("resizing-col", "resizing-row");
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    document.body.classList.add(
      dir === "col" ? "resizing-col" : "resizing-row",
    );
  };
  return (
    <div
      role="separator"
      aria-orientation={dir === "col" ? "vertical" : "horizontal"}
      aria-label={label}
      tabIndex={0}
      className={`splitter ${dir} ${className}`}
      onPointerDown={start}
      onKeyDown={(e) => {
        const step = e.shiftKey ? 64 : 16;
        const back = dir === "col" ? "ArrowLeft" : "ArrowUp";
        const fwd = dir === "col" ? "ArrowRight" : "ArrowDown";
        if (e.key === back || e.key === fwd) {
          e.preventDefault();
          onDrag(e.key === back ? -step : step);
        }
      }}
    />
  );
}

/** A size kept in this browser, within limits. The setter takes a size or a change to the latest
 * one (a drag's handler keeps the render it started in, so it changes, never replaces). */
export function useStoredSize(
  key: string,
  fallback: number,
  min: number,
  max: number,
): [number, (n: number | ((prev: number) => number)) => void] {
  const clamp = (n: number) => Math.min(max, Math.max(min, Math.round(n)));
  const [size, setSize] = useState(() => {
    try {
      const v = Number(localStorage.getItem(key));
      return v ? clamp(v) : fallback;
    } catch {
      return fallback;
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem(key, String(size));
    } catch {
      /* storage off: the size lasts until the page reloads */
    }
  }, [key, size]);
  return [
    size,
    (n) => setSize((prev) => clamp(typeof n === "function" ? n(prev) : n)),
  ];
}

/** An on/off kept in this browser (off when storage is gone). */
export function useStoredFlag(key: string): [boolean, (on: boolean) => void] {
  const [on, setOn] = useState(() => {
    try {
      return localStorage.getItem(key) === "1";
    } catch {
      return false;
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem(key, on ? "1" : "0");
    } catch {
      /* storage off: it lasts until the page reloads */
    }
  }, [key, on]);
  return [on, setOn];
}
