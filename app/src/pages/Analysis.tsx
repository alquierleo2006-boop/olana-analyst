import { useState } from "react";
import { useAnalysis } from "../lib/useAnalysis";
import { age, dateTime, scoreTone, short, usd, v, verdictTone } from "../lib/format";
import { copyText } from "../lib/native";
import { Badge, Button, Card, Spinner, Stat, Tabs, Tone } from "../components/ui";
import * as T from "./AnalysisTabs";
import ScalpCard from "../components/ScalpCard";

const TABS = [
  { id: "overview", label: "OVERVIEW" }, { id: "onchain", label: "ON-CHAIN" }, { id: "holders", label: "HOLDERS" },
  { id: "developer", label: "DEVELOPER" }, { id: "social", label: "SOCIAL" }, { id: "narrative", label: "NARRATIVE" },
{ id: "smart", label: "SMART MONEY" }, { id: "risk", label: "RISK ANALYSIS" },
  { id: "ai", label: "AI VERDICT" },
];

export default function Analysis({ id, compact, onBack, onReanalyze }: { id: number; compact: boolean; onBack: () => void; onReanalyze: (mint: string) => void }) {
  const { data: d, error, firstMs } = useAnalysis(id);
  const [tab, setTab] = useState("overview");
  const [showDetails, setShowDetails] = useState(!compact);

  if (error && (!d || !d.scores)) {
    return (
      <div className="space-y-3 p-3">
        <Button onClick={onBack}>← Retour</Button>
        <Card title="Analyse impossible">
          <div className="text-bad">{error}</div>
          <div className="mt-2 text-[12px] text-muted">Aucune analyse n'a été produite : le logiciel n'affiche jamais de résultats sans données réelles.</div>
        </Card>
      </div>
    );
  }
  if (!d) return <div className="p-6 text-center text-muted"><Spinner /> Connexion à l'analyse…</div>;

  const tok = d.token || {}, m = d.market || {}, sc = d.scores;
  const lp = tok.launchpad;
  const running = d.provisional !== false;
  const mods = Object.entries(d.modules || {}) as [string, any][];
  const doneCount = mods.filter(([, x]) => x.status !== "en cours").length;
  const critical = (d.risks || []).filter((r: any) => r.level === "critique");

  return (
    <div className="space-y-2.5 p-3">
      <div className="flex items-center justify-between">
        <Button onClick={onBack}>← Accueil</Button>
        <div className="flex gap-1.5">
          {!running && <Button onClick={() => onReanalyze(d.mint)} title="Relancer une analyse complète">↻ Réanalyser</Button>}
          <Button onClick={() => setShowDetails(!showDetails)}>{showDetails ? "Mode compact" : "Analyse détaillée"}</Button>
        </div>
      </div>

      {/* 10.1 En-tête */}
      <Card>
        <div className="flex items-start gap-3">
          {tok.image ? <img src={tok.image} alt="" className="h-11 w-11 shrink-0 rounded-lg border border-line object-cover" onError={(e) => ((e.target as HTMLImageElement).style.display = "none")} />
            : <div className="grid h-11 w-11 shrink-0 place-items-center rounded-lg border border-line bg-panel2 text-muted">?</div>}
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="truncate text-[15px] font-bold">{tok.name || "Token"}</span>
              <span className="text-ink2">${tok.symbol || "?"}</span>
              {lp && <Badge tone={lp.status === "vérifié on-chain" ? "info" : "muted"} title={(lp.evidence || []).join("\n")}>{lp.label}{lp.status !== "vérifié on-chain" ? " (non vérifié)" : ""}</Badge>}
            </div>
            <button className="selectable mt-0.5 font-mono text-[11px] text-muted hover:text-ink2" onClick={() => copyText(d.mint)} title="Copier l'adresse">
              {short(d.mint, 8)} ⧉
            </button>
          </div>
        </div>
        <div className="mt-2.5 grid grid-cols-3 gap-2 sm:grid-cols-6">
          <Stat label="Market cap" value={usd(v(m.mcap))} p={m.mcap} />
          <Stat label="FDV" value={usd(v(m.fdv))} p={m.fdv} />
          <Stat label="Liquidité" value={usd(v(m.liquidity_usd))} p={m.liquidity_usd} />
          <Stat label="Volume 24 h" value={usd(v(m.volume?.h24))} p={m.volume?.h24} />
          <Stat label="Âge" value={age(v(tok.created_at) || v(m.first_pair_at))} p={tok.created_at} />
          <Stat label="Analyse" value={dateTime(d.started_at)} />
        </div>
      </Card>

      {/* 10.2 Résultat principal */}
      <MainResult d={d} sc={sc} running={running} firstMs={firstMs} doneCount={doneCount} total={mods.length} />

      {d.scores?.scalp && <ScalpCard sc={d.scores.scalp} />}

      {d.live_watch?.active && <div className="text-[11px] text-muted">🛡 Surveillance anti-rug active : notification si le dev, un gros holder ou le bundle vend.</div>}

      {critical.length > 0 && (
        <div className="rounded-lg border border-bad/50 bg-bad/10 p-2.5" role="alert">
          <div className="mb-1 text-[11px] font-bold uppercase tracking-wider text-bad">✕ Risques critiques</div>
          {critical.map((r: any) => <div key={r.code} className="text-[12px] text-ink">• {r.message} <span className="text-muted">({r.source})</span></div>)}
        </div>
      )}

      {showDetails && (
        <div>
          <Tabs tabs={TABS.map((t) => ({ ...t, dot: tabDot(t.id, d) }))} active={tab} onChange={setTab} />
          <div className="pt-2.5">
            {tab === "overview" && <T.Overview d={d} />}
            {tab === "onchain" && <T.OnChain d={d} />}
            {tab === "holders" && <T.Holders d={d} />}
            {tab === "developer" && <T.Developer d={d} />}
            {tab === "social" && <T.Social d={d} />}
            {tab === "narrative" && <T.Narrative d={d} />}
            {tab === "smart" && <T.Smart d={d} />}
            {tab === "risk" && <T.Risk d={d} />}
            {tab === "ai" && <T.AIVerdict d={d} />}
          </div>
        </div>
      )}
    </div>
  );
}

function tabDot(id: string, d: any): Tone | undefined {
  const mod: Record<string, string[]> = { onchain: ["security", "liquidity", "market"], holders: ["holders", "clusters"], developer: ["developer"],
    social: ["social"], narrative: ["narrative"], smart: ["smart_money"] };
  const ms = (mod[id] || []).map((k) => d.modules?.[k]?.status);
  if (ms.some((s) => s === "en cours")) return "muted";
  if (ms.some((s) => s === "erreur" || s === "délai dépassé")) return "warn";
  if (id === "risk" && (d.risks || []).some((r: any) => r.level === "critique")) return "bad";
  return undefined;
}

function MainResult({ d, sc, running, firstMs, doneCount, total }: any) {
  if (!sc) {
    return <Card><div className="py-3 text-center text-muted"><Spinner /> Identification du token et collecte des premières données…</div></Card>;
  }
  const g = sc.global;
  const tone = scoreTone(g);
  const vt = verdictTone(sc.verdict) as Tone;
  const ringColor = tone === "good" ? "var(--color-good)" : tone === "warn" ? "var(--color-warn)" : tone === "bad" ? "var(--color-bad)" : "#7f8792";
  const C = 2 * Math.PI * 34;
  const timing = d.timing || {};
  return (
    <Card className={running ? "border-info/40" : ""}>
      <div className="flex items-center gap-4">
        <div className="relative h-[84px] w-[84px] shrink-0" aria-label={`Score ${g ?? "indisponible"} sur 10`}>
          <svg viewBox="0 0 84 84" className="h-full w-full -rotate-90">
            <circle cx="42" cy="42" r="34" stroke="#262b33" strokeWidth="7" fill="none" />
            {g !== null && <circle cx="42" cy="42" r="34" stroke={ringColor} strokeWidth="7" fill="none" strokeLinecap="round" strokeDasharray={`${(g / 10) * C} ${C}`} />}
          </svg>
          <div className="absolute inset-0 grid place-items-center text-center">
            <div><div className="num text-[24px] font-bold leading-none">{g ?? "—"}</div><div className="text-[10px] text-muted">/ 10</div></div>
          </div>
        </div>
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`rounded-md px-2.5 py-1 text-[15px] font-extrabold tracking-wide ${vt === "good" ? "bg-good/15 text-good" : vt === "warn" ? "bg-warn/15 text-warn" : "bg-bad/15 text-bad"}`}>
              {vt === "good" ? "▲ " : vt === "warn" ? "◆ " : "✕ "}{sc.verdict}
            </span>
            {running ? <Badge tone="info">provisoire · {doneCount}/{total} modules</Badge> : <Badge tone={d.status === "complète" ? "good" : "warn"}>analyse {d.status}</Badge>}
          </div>
          <div className="text-[12px] text-ink2">{sc.verdict_reason}</div>
          <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[11px] sm:grid-cols-4">
            <span className="text-muted">Potentiel : <b className="text-ink">{sc.interpretation}</b></span>
            <span className="text-muted">Confiance : <b className="text-ink">{Math.round(sc.confidence * 100)}%</b></span>
            <span className="text-muted">Risque : <b className={sc.risk.label === "critique" ? "text-bad" : sc.risk.label === "élevé" ? "text-warn" : "text-ink"}>{sc.risk.label} ({sc.risk.score}/10)</b></span>
            <span className="text-muted" title={`Objectif 1re fiche : ${timing.target_s ?? 5} s`}>
              Durée : <b className="text-ink">{firstMs || timing.first_result_ms ? `${(((timing.first_result_ms ?? firstMs) as number) / 1000).toFixed(1)} s` : "…"}</b>
              {timing.total_ms ? <> · complète {(timing.total_ms / 1000).toFixed(1)} s</> : running ? " · en cours" : ""}
            </span>
          </div>
        </div>
      </div>
      {running && <div className="mt-2 h-1 overflow-hidden rounded bg-line"><div className="h-full bg-info transition-all" style={{ width: `${(doneCount / Math.max(1, total)) * 100}%` }} /></div>}
    </Card>
  );
}

