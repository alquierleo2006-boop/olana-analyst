import { ReactNode, useState } from "react";
import { DP, dateTime } from "../lib/format";
import { openUrl } from "../lib/native";

export type Tone = "good" | "warn" | "bad" | "info" | "muted";
const toneCls: Record<Tone, string> = {
  good: "text-good border-good/40 bg-good/10",
  warn: "text-warn border-warn/40 bg-warn/10",
  bad: "text-bad border-bad/40 bg-bad/10",
  info: "text-info border-info/40 bg-info/10",
  muted: "text-ink2 border-line bg-panel2",
};
const toneIcon: Record<Tone, string> = { good: "✓", warn: "!", bad: "✕", info: "i", muted: "·" };

export function Badge({ tone = "muted", children, icon = true, title }: { tone?: Tone; children: ReactNode; icon?: boolean; title?: string }) {
  return (
    <span title={title} className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium whitespace-nowrap ${toneCls[tone]}`}>
      {icon && <span aria-hidden className="text-[10px] font-bold">{toneIcon[tone]}</span>}
      {children}
    </span>
  );
}

export function Card({ title, right, children, className = "" }: { title?: ReactNode; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-lg border border-line bg-panel p-3 ${className}`}>
      {(title || right) && (
        <div className="mb-2 flex items-center justify-between gap-2">
          <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted">{title}</h3>
          {right}
        </div>
      )}
      {children}
    </section>
  );
}

/** Indique la source, l'horodatage et le statut d'une donnée (traçabilité). */
export function Src({ p }: { p: DP | any }) {
  if (!p || typeof p !== "object" || !("src" in p)) return null;
  const st = p.st as string;
  const color = st === "vérifié" ? "text-good" : st === "estimé" ? "text-warn" : st === "indisponible" || st === "non vérifié" ? "text-bad" : "text-muted";
  return (
    <span title={`Source : ${p.src}\nHorodatage : ${dateTime(p.ts)}\nStatut : ${st}`} className={`ml-1 cursor-help text-[10px] ${color}`}>
      ⓘ
    </span>
  );
}

export function Stat({ label, value, sub, p, tone }: { label: string; value: ReactNode; sub?: ReactNode; p?: any; tone?: Tone }) {
  const c = tone === "good" ? "text-good" : tone === "bad" ? "text-bad" : tone === "warn" ? "text-warn" : "text-ink";
  return (
    <div className="min-w-0">
      <div className="text-[10px] uppercase tracking-wide text-muted">{label}</div>
      <div className={`num truncate text-[14px] font-semibold ${c}`}>
        {value}
        <Src p={p} />
      </div>
      {sub && <div className="truncate text-[11px] text-muted">{sub}</div>}
    </div>
  );
}

export function Row({ k, children }: { k: ReactNode; children: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-line/60 py-1.5 last:border-0">
      <span className="text-ink2">{k}</span>
      <span className="num text-right font-medium">{children}</span>
    </div>
  );
}

export function Tabs({ tabs, active, onChange }: { tabs: { id: string; label: string; dot?: Tone }[]; active: string; onChange: (id: string) => void }) {
  return (
    <div className="flex gap-1 overflow-x-auto border-b border-line pb-px" role="tablist">
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={active === t.id} onClick={() => onChange(t.id)}
          className={`relative whitespace-nowrap rounded-t-md px-2.5 py-1.5 text-[11px] font-semibold tracking-wide transition-colors ${
            active === t.id ? "bg-panel text-ink" : "text-muted hover:text-ink2"}`}>
          {t.label}
          {t.dot && <span className={`ml-1 inline-block h-1.5 w-1.5 rounded-full align-middle ${t.dot === "bad" ? "bg-bad" : t.dot === "warn" ? "bg-warn" : t.dot === "good" ? "bg-good" : "bg-muted"}`} />}
          {active === t.id && <span className="absolute inset-x-1 -bottom-px h-0.5 rounded bg-info" />}
        </button>
      ))}
    </div>
  );
}

export function Button({ children, onClick, kind = "ghost", disabled, title, className = "", type = "button" }:
  { children: ReactNode; onClick?: () => void; kind?: "primary" | "ghost" | "danger"; disabled?: boolean; title?: string; className?: string; type?: "button" | "submit" }) {
  const k = kind === "primary" ? "bg-info text-white hover:bg-info/90 border-info"
    : kind === "danger" ? "border-bad/50 text-bad hover:bg-bad/10" : "border-line text-ink2 hover:bg-panel2 hover:text-ink";
  return (
    <button type={type} title={title} disabled={disabled} onClick={onClick}
      className={`rounded-md border px-2.5 py-1.5 text-[12px] font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${k} ${className}`}>
      {children}
    </button>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-md border border-dashed border-line p-3 text-center text-[12px] text-muted">{children}</div>;
}

export function Spinner({ size = 12 }: { size?: number }) {
  return <span style={{ width: size, height: size }} className="inline-block animate-spin rounded-full border-2 border-muted/40 border-t-info align-middle" />;
}

export function Collapse({ title, children, defaultOpen = false }: { title: ReactNode; children: ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-md border border-line">
      <button className="flex w-full items-center justify-between px-2.5 py-1.5 text-left text-[12px] font-semibold text-ink2 hover:text-ink" onClick={() => setOpen(!open)}>
        {title}<span className="text-muted">{open ? "▾" : "▸"}</span>
      </button>
      {open && <div className="border-t border-line p-2.5">{children}</div>}
    </div>
  );
}

export function Link({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a href={href} onClick={(e) => { e.preventDefault(); openUrl(href); }}
      className="text-info underline-offset-2 hover:underline break-all">{children}</a>
  );
}

export const socialTone = (s?: string): Tone =>
  s === "AUTHENTIQUE VÉRIFIÉ" ? "good" : s === "PROBABLEMENT AUTHENTIQUE" ? "info"
  : s === "SUSPECT" ? "warn" : s === "USURPATION PROBABLE" ? "bad" : "muted";

export const claimTone = (s?: string): Tone =>
  s?.startsWith("CONFIRMÉ") ? "good" : s === "PARTIELLEMENT CONFIRMÉ" ? "info"
  : s === "CONTREDIT" || s === "FAUX OU TROMPEUR" ? "bad" : "muted";

export const riskTone = (l?: string): Tone => (l === "critique" ? "bad" : l === "élevé" ? "warn" : l === "moyen" ? "info" : "muted");
