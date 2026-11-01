// Graphiques SVG minimalistes : trait 2 px, axes discrets, infobulle au survol, légende si ≥ 2 séries.
import { useLayoutEffect, useRef, useState, ReactNode } from "react";

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [w, setW] = useState(300);
  useLayoutEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver((e) => setW(Math.max(120, e[0].contentRect.width)));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

const PAD = { l: 58, r: 10, t: 8, b: 20 };

function Tip({ x, y, w, children }: { x: number; y: number; w: number; children: ReactNode }) {
  const left = Math.min(Math.max(4, x + 10), w - 150);
  return (
    <div style={{ left, top: Math.max(0, y - 10) }}
      className="pointer-events-none absolute z-10 w-[140px] rounded-md border border-line bg-panel2 px-2 py-1 text-[11px] shadow-lg">
      {children}
    </div>
  );
}

export function LineChart({ points, height = 140, fmtY, fmtX, label }:
  { points: { x: number; y: number }[]; height?: number; fmtY: (n: number) => string; fmtX: (n: number) => string; label: string }) {
  const [ref, W] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  if (points.length < 2) return <div className="text-[12px] text-muted">Pas assez de données pour un graphique.</div>;
  const xs = points.map((p) => p.x), ys = points.map((p) => p.y);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  let y0 = Math.min(...ys), y1 = Math.max(...ys);
  if (y0 === y1) { y0 *= 0.95; y1 *= 1.05; }
  const iw = W - PAD.l - PAD.r, ih = height - PAD.t - PAD.b;
  const sx = (x: number) => PAD.l + ((x - x0) / (x1 - x0 || 1)) * iw;
  const sy = (y: number) => PAD.t + ih - ((y - y0) / (y1 - y0 || 1)) * ih;
  const d = points.map((p, i) => `${i ? "L" : "M"}${sx(p.x).toFixed(1)},${sy(p.y).toFixed(1)}`).join("");
  const ticks = [y0, (y0 + y1) / 2, y1];
  const onMove = (e: React.MouseEvent) => {
    const r = (e.currentTarget as SVGElement).getBoundingClientRect();
    const xv = x0 + ((e.clientX - r.left - PAD.l) / iw) * (x1 - x0);
    let best = 0;
    points.forEach((p, i) => { if (Math.abs(p.x - xv) < Math.abs(points[best].x - xv)) best = i; });
    setHover(best);
  };
  const hp = hover !== null ? points[hover] : null;
  return (
    <div ref={ref} className="relative" aria-label={label} role="img">
      <svg width={W} height={height} onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
        {ticks.map((t, i) => (
          <g key={i}>
            <line x1={PAD.l} x2={W - PAD.r} y1={sy(t)} y2={sy(t)} stroke="#262b33" strokeWidth={1} />
            <text x={PAD.l - 6} y={sy(t) + 3} textAnchor="end" fontSize={10} fill="#7f8792">{fmtY(t)}</text>
          </g>
        ))}
        <text x={PAD.l} y={height - 4} fontSize={10} fill="#7f8792">{fmtX(x0)}</text>
        <text x={W - PAD.r} y={height - 4} fontSize={10} fill="#7f8792" textAnchor="end">{fmtX(x1)}</text>
        <path d={d} fill="none" stroke="var(--color-series1)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        {hp && (
          <g>
            <line x1={sx(hp.x)} x2={sx(hp.x)} y1={PAD.t} y2={PAD.t + ih} stroke="#7f8792" strokeDasharray="3 3" />
            <circle cx={sx(hp.x)} cy={sy(hp.y)} r={4} fill="var(--color-series1)" stroke="#14171c" strokeWidth={2} />
          </g>
        )}
      </svg>
      {hp && (
        <Tip x={sx(hp.x)} y={sy(hp.y)} w={W}>
          <div className="text-muted">{fmtX(hp.x)}</div>
          <div className="font-semibold text-ink">{fmtY(hp.y)}</div>
        </Tip>
      )}
    </div>
  );
}

export type BarSeries = { name: string; color: string; values: number[] };

export function BarChart({ labels, series, height = 140, fmtY, label }:
  { labels: string[]; series: BarSeries[]; height?: number; fmtY: (n: number) => string; label: string }) {
  const [ref, W] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  if (!labels.length) return <div className="text-[12px] text-muted">Aucune donnée.</div>;
  const max = Math.max(1e-9, ...series.flatMap((s) => s.values));
  const iw = W - PAD.l - PAD.r, ih = height - PAD.t - PAD.b;
  const group = iw / labels.length;
  const gap = 2;
  const bw = Math.max(1, (group - 4) / series.length - gap);
  const sy = (y: number) => PAD.t + ih - (y / max) * ih;
  const every = Math.ceil(labels.length / 6);
  return (
    <div ref={ref} className="relative" role="img" aria-label={label}>
      {series.length > 1 && (
        <div className="mb-1 flex gap-3 text-[11px] text-ink2">
          {series.map((s) => (
            <span key={s.name} className="flex items-center gap-1"><span className="inline-block h-2 w-2 rounded-sm" style={{ background: s.color }} />{s.name}</span>
          ))}
        </div>
      )}
      <svg width={W} height={height} onMouseLeave={() => setHover(null)}>
        {[0, max / 2, max].map((t, i) => (
          <g key={i}>
            <line x1={PAD.l} x2={W - PAD.r} y1={sy(t)} y2={sy(t)} stroke="#262b33" />
            <text x={PAD.l - 6} y={sy(t) + 3} textAnchor="end" fontSize={10} fill="#7f8792">{fmtY(t)}</text>
          </g>
        ))}
        {labels.map((lb, i) => (
          <g key={i} onMouseEnter={() => setHover(i)}>
            <rect x={PAD.l + i * group} y={PAD.t} width={group} height={ih} fill={hover === i ? "#ffffff08" : "transparent"} />
            {series.map((s, k) => {
              const h = Math.max(0, PAD.t + ih - sy(s.values[i] || 0));
              const x = PAD.l + i * group + 2 + k * (bw + gap);
              const r = Math.min(4, bw / 2, h);
              return h > 0 ? (
                <path key={k} fill={s.color}
                  d={`M${x},${PAD.t + ih}V${PAD.t + ih - h + r}Q${x},${PAD.t + ih - h} ${x + r},${PAD.t + ih - h}H${x + bw - r}Q${x + bw},${PAD.t + ih - h} ${x + bw},${PAD.t + ih - h + r}V${PAD.t + ih}Z`} />
              ) : null;
            })}
            {i % every === 0 && <text x={PAD.l + i * group + group / 2} y={height - 4} fontSize={10} fill="#7f8792" textAnchor="middle">{lb}</text>}
          </g>
        ))}
      </svg>
      {hover !== null && (
        <Tip x={PAD.l + hover * group + group / 2} y={PAD.t + 10} w={W}>
          <div className="text-muted">{labels[hover]}</div>
          {series.map((s) => (
            <div key={s.name} className="flex justify-between gap-2"><span className="flex items-center gap-1"><span className="inline-block h-2 w-2 rounded-sm" style={{ background: s.color }} />{s.name}</span><span className="font-semibold text-ink">{fmtY(s.values[hover] || 0)}</span></div>
          ))}
        </Tip>
      )}
    </div>
  );
}

/** Barres horizontales (répartition des holders). Une seule teinte ; les comptes techniques sont texturés. */
export function HBars({ rows, fmt }: { rows: { label: string; value: number; technical?: boolean; title?: string }[]; fmt: (n: number) => string }) {
  const max = Math.max(1e-9, ...rows.map((r) => r.value));
  return (
    <div className="space-y-1" role="list">
      <svg width="0" height="0" className="absolute">
        <defs>
          <pattern id="hatch" width="6" height="6" patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
            <rect width="6" height="6" fill="#3987e533" /><line x1="0" y1="0" x2="0" y2="6" stroke="#3987e5" strokeWidth="2" />
          </pattern>
        </defs>
      </svg>
      {rows.map((r, i) => (
        <div key={i} className="group flex items-center gap-2" role="listitem" title={r.title || r.label}>
          <div className="w-28 shrink-0 truncate text-[11px] text-ink2">{r.label}</div>
          <svg className="h-3 flex-1" preserveAspectRatio="none" viewBox="0 0 100 10">
            <rect x="0" y="1" height="8" rx="2" width={Math.max(0.5, (r.value / max) * 100)} fill={r.technical ? "url(#hatch)" : "var(--color-series1)"} className="group-hover:opacity-80" />
          </svg>
          <div className="num w-14 shrink-0 text-right text-[11px] font-semibold">{fmt(r.value)}</div>
        </div>
      ))}
    </div>
  );
}
