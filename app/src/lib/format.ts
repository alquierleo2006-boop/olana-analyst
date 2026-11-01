// Formatage. Une valeur absente s'affiche « — », jamais 0.
export type DP<T = any> = { v: T | null; src: string; ts: number; st: string } | null | undefined;

export const v = <T,>(p: DP<T> | any): T | null =>
  p && typeof p === "object" && "v" in p ? (p.v ?? null) : p ?? null;

export function usd(x: number | null | undefined, digits = 2): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "—";
  const a = Math.abs(x);
  if (a >= 1e9) return `$${(x / 1e9).toFixed(digits)}B`;
  if (a >= 1e6) return `$${(x / 1e6).toFixed(digits)}M`;
  if (a >= 1e3) return `$${(x / 1e3).toFixed(1)}K`;
  return `$${x.toFixed(a < 10 ? 2 : 0)}`;
}

export function price(x: number | null | undefined): string {
  if (x === null || x === undefined) return "—";
  if (x >= 1) return `$${x.toLocaleString("fr-FR", { maximumFractionDigits: 4 })}`;
  if (x === 0) return "$0";
  const s = x.toFixed(14).split(".")[1];
  const zeros = s.length - s.replace(/^0+/, "").length;
  if (zeros >= 4) {
    const sub = String(zeros).replace(/\d/g, (d) => "₀₁₂₃₄₅₆₇₈₉"[+d]);
    return `$0.0${sub}${s.slice(zeros, zeros + 4)}`;
  }
  return `$${x.toFixed(zeros + 4)}`;
}

export const pct = (x: number | null | undefined, d = 1) =>
  x === null || x === undefined ? "—" : `${x > 0 ? "+" : ""}${x.toFixed(d)}%`;

export const num = (x: number | null | undefined) =>
  x === null || x === undefined ? "—" : x.toLocaleString("fr-FR");

export function age(ts: number | null | undefined): string {
  if (!ts) return "—";
  const s = Date.now() / 1000 - ts;
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min`;
  if (s < 86400) return `${(s / 3600).toFixed(1)} h`;
  return `${(s / 86400).toFixed(1)} j`;
}

export const dateTime = (ts: number | null | undefined) =>
  ts ? new Date(ts * 1000).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—";

export const short = (a?: string | null, n = 4) => (a ? `${a.slice(0, n)}…${a.slice(-n)}` : "—");

export const verdictTone = (vd?: string) =>
  vd === "BUY SETUP" ? "good" : vd === "WATCH" ? "warn" : vd === "AVOID" ? "bad" : "info";

export function scoreTone(s: number | null | undefined) {
  if (s === null || s === undefined) return "muted";
  return s >= 7 ? "good" : s >= 4.5 ? "warn" : "bad";
}
