// A drag handle between two areas: drag it, or focus it and use the arrow keys. Sizes a person sets
// are kept in this browser (a convenience: they come back to the defaults when storage is gone).
import { useEffect, useState } from "react";
import { ResizeHandle, useResizable } from "@dotrix/ui/astryx";

export function Splitter({
  dir,
  size,
  min,
  max,
  onResize,
  reversed = false,
  label,
  className = "",
}: {
  dir: "col" | "row";
  size: number;
  min: number;
  max: number;
  onResize: (size: number) => void;
  reversed?: boolean;
  label: string;
  className?: string;
}) {
  const direction = dir === "col" ? "horizontal" : "vertical";
  const region = useResizable({ defaultSize: size, minSize: min, maxSize: max, direction, onSizeChange: onResize });
  return (
    <ResizeHandle
      direction={direction}
      label={label}
      resizable={region}
      isReversed={reversed}
      className={`splitter ${dir} ${className}`}
      hasDivider
      isAlwaysVisible={false}
    />
  );
}

/** A size kept in this browser, within limits. The setter takes a size or a change to the latest
 * one (a drag's handler keeps the render it started in, so it changes, never replaces). */
export function useStoredSize(key: string, fallback: number, min: number, max: number): [number, (n: number | ((prev: number) => number)) => void] {
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
  return [size, (n) => setSize((prev) => clamp(typeof n === "function" ? n(prev) : n))];
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

/** A short text kept in this browser (the fallback when storage is gone). */
export function useStoredText(key: string, fallback: string): [string, (value: string) => void] {
  const [value, setValue] = useState(() => {
    try {
      return localStorage.getItem(key) ?? fallback;
    } catch {
      return fallback;
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem(key, value);
    } catch {
      /* storage off: it lasts until the page reloads */
    }
  }, [key, value]);
  return [value, setValue];
}
