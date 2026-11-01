import { usd } from "../lib/format";
import { Card, Spinner } from "./ui";
import { isTech } from "../lib/edition";

const ICON: Record<string, [string, string]> = {
  ok: ["✓", "text-good"], attention: ["!", "text-warn"], bloquant: ["✕", "text-bad"], "en attente": ["…", "text-muted"],
};

/** Checklist d'entrée scalp : décision claire + plan de sortie pour ta taille de position. */
export default function ScalpCard({ sc }: { sc: any }) {
  if (!sc) return null;
  const d = sc.decision;
  const tone = d === "ENTRÉE POSSIBLE" ? "border-good/60 bg-good/10 text-good" : d === "NE PAS ENTRER" ? "border-bad/60 bg-bad/10 text-bad"
    : d === "ATTENDRE" ? "border-warn/60 bg-warn/10 text-warn" : "border-line bg-panel2 text-muted";
  const icon = d === "ENTRÉE POSSIBLE" ? "✅" : d === "NE PAS ENTRER" ? "⛔" : d === "ATTENDRE" ? "⏳" : "";
  const p = sc.plan;
  return (
    <Card title={isTech() ? "Checklist d'entrée tech" : "Checklist d'entrée scalp"}>
      <div className={`mb-2 rounded-md border px-3 py-2 ${tone}`}>
        <div className="text-[16px] font-extrabold tracking-wide">{icon} {d === "EN COURS" ? <><Spinner /> ANALYSE EN COURS</> : d}</div>
        <div className="text-[12px] text-ink2">{sc.reason}</div>
      </div>
      <div className="grid gap-x-4 sm:grid-cols-2">
        {sc.checks.map((c: any) => {
          const [i, cls] = ICON[c.status] || ["·", "text-muted"];
          return (
            <div key={c.name} className="flex items-start gap-2 border-b border-line/60 py-1 text-[12px]">
              <span className={`w-3 shrink-0 text-center font-bold ${cls}`} aria-label={c.status}>{i}</span>
              <span><b>{c.name}</b> <span className="text-muted">— {c.detail}</span></span>
            </div>
          );
        })}
      </div>
      {p && (
        <div className="mt-2 grid grid-cols-3 gap-2 rounded-md bg-panel2 p-2 text-[12px]">
          <div><div className="text-[10px] uppercase text-muted">Entrée</div><b className="num">{usd(p.entry_mcap)}</b><div className="text-[10px] text-muted">{p.position_sol} SOL</div></div>
          <div><div className="text-[10px] uppercase text-muted">Objectif +{p.take_profit_pct}%</div><b className="num text-good">{usd(p.target_mcap)}</b>
            <div className="text-[10px] text-muted">≈ +{p.gain_sol.toFixed(3)} SOL net</div></div>
          <div><div className="text-[10px] uppercase text-muted">Stop −{p.stop_pct}%</div><b className="num text-bad">{usd(p.stop_mcap)}</b>
            <div className="text-[10px] text-muted">≈ {p.loss_sol.toFixed(3)} SOL net</div></div>
          {p.breakeven_winrate != null && <div className="col-span-3 text-[11px] text-muted">
            Coût aller-retour ≈ {p.cost_pct != null ? `${p.cost_pct.toFixed(1)}%` : "?"}. Pour être rentable avec ce plan, il faut gagner plus de <b className="text-ink">{Math.round(p.breakeven_winrate * 100)}%</b> de tes trades.</div>}
        </div>
      )}
      <div className="mt-1 text-[10px] text-muted">{sc.note}</div>
    </Card>
  );
}
