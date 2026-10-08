// Gr8r's utilities (gr8r-studio/src/core/utils.js), typed.
export const uid = (p = "x") => p + Math.random().toString(36).slice(2, 8);
export const clamp = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v));
export const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
export const MOD = isMac ? "⌘" : "Ctrl";

/* ---------- dates ---------- */
export const DAY = 864e5;
export const sod = (d: Date | number | string) => {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x;
};
export const TODAY = sod(new Date());
export const iso = (d: Date | number) => {
  const x = new Date(d);
  return `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, "0")}-${String(x.getDate()).padStart(2, "0")}`;
};
export const parse = (s: string | null | undefined): Date | null => {
  if (!s) return null;
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y!, m! - 1, d);
};
export const addD = (d: Date | number, n: number) => {
  const x = new Date(d);
  x.setDate(x.getDate() + n);
  return x;
};
export const dOff = (n: number) => iso(addD(TODAY, n));
export const diffD = (a: Date | number, b: Date | number) => Math.round((sod(a).getTime() - sod(b).getTime()) / DAY);
export const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export const MONL = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
export const WD = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
export const WDL = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

/** Set from preferences (core/theme), so utils never depends on the store. */
let dateFormat = "MMM d";
export function setDateFormat(f: string | undefined) {
  dateFormat = f || "MMM d";
}
export function fmtDate(s: string | Date | null | undefined, long?: boolean): string {
  const d = typeof s === "string" ? parse(s) : s;
  if (!d) return "";
  const fmt = dateFormat;
  if (fmt === "d/M") return `${d.getDate()}/${d.getMonth() + 1}${long ? "/" + d.getFullYear() : ""}`;
  if (fmt === "M/d") return `${d.getMonth() + 1}/${d.getDate()}${long ? "/" + d.getFullYear() : ""}`;
  if (fmt === "yyyy-MM-dd") return iso(d);
  return `${MON[d.getMonth()]} ${d.getDate()}${long || d.getFullYear() !== TODAY.getFullYear() ? ", " + d.getFullYear() : ""}`;
}
export function relDate(s: string | null | undefined): string {
  if (!s) return "";
  const n = diffD(parse(s)!, TODAY);
  if (n === 0) return "Today";
  if (n === 1) return "Tomorrow";
  if (n === -1) return "Yesterday";
  if (n > 1 && n < 7) return WD[parse(s)!.getDay()]!;
  return fmtDate(s);
}
export function ago(ts: number): string {
  const m = Math.round((Date.now() - ts) / 6e4);
  if (m < 1) return "just now";
  if (m < 60) return m + "m ago";
  const h = Math.round(m / 60);
  if (h < 24) return h + "h ago";
  const d = Math.round(h / 24);
  if (d < 7) return d + "d ago";
  return fmtDate(iso(new Date(ts)));
}
export const minsAgo = (m: number) => Date.now() - m * 6e4;
export function dayBucket(ts: number): string {
  const n = diffD(new Date(ts), TODAY);
  if (n === 0) return "Today";
  if (n === -1) return "Yesterday";
  if (n > -7) return "This week";
  return "Earlier";
}
export function greeting(): string {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}
export const initials = (name: string) =>
  name
    .split(" ")
    .map((x) => x[0])
    .join("")
    .slice(0, 2);
