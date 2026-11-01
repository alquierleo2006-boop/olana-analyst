import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { dateTime, pct } from "../lib/format";
import { Button, Card, Empty, Spinner } from "../components/ui";

export default function Performance({ back }: { back: () => void }) {
  const [r, setR] = useState<any>(null);
  const [h, setH] = useState("1h");
  useEffect(() => { api("/api/performance").then(setR).catch(() => {}); }, []);
  if (!r) return <div className="p-6 text-center text-muted"><Spinner /></div>;
  const H = r.horizons[h] || {};
  const Tbl = ({ title, data }: { title: string; data: any }) => !data || !Object.keys(data).length ? null : (
    <Card title={title}>
      <table className="w-full text-[12px]">
        <thead className="text-left text-[10px] uppercase text-muted"><tr><th>Groupe</th><th>N</th><th>Taux de réussite</th><th>Médiane (après frais)</th><th>Gain max moyen</th><th>Drawdown moyen</th></tr></thead>
        <tbody>{Object.entries(data).map(([k, x]: any) => (
          <tr key={k} className="border-t border-line/60"><td className="py-1">{k}</td><td>{x.n}</td>
            <td>{Math.round(x.hit_rate * 100)}% <span className="text-muted">[{Math.round(x.ci95[0] * 100)}–{Math.round(x.ci95[1] * 100)}]</span></td>
            <td>{pct(x.median_change_after_fees)}</td><td>{pct(x.avg_max_gain)}</td><td>{pct(x.avg_drawdown)}</td></tr>))}</tbody>
      </table>
    </Card>
  );
  return (
    <div className="space-y-2.5 p-3">
      <div className="flex items-center justify-between"><Button onClick={back}>← Accueil</Button><h2 className="text-[13px] font-bold">PERFORMANCE & BACKTESTING</h2><span /></div>
      <ScalpPerf sp={r.scalp} />
      <div className="mt-3 text-[11px] font-semibold uppercase tracking-wider text-muted">Évolution du prix par horizon</div>
      <div className="flex gap-1">{Object.keys(r.horizons).map((k) => <Button key={k} kind={k === h ? "primary" : "ghost"} onClick={() => setH(k)}>{k} ({r.horizons[k].observations})</Button>)}</div>
      <div className="text-[11px] text-muted">Réussite = hausse ≥ {r.rise_definition_pct}% du prix après {r.fees_assumption_pct}% de frais estimés. {r.note}</div>
      {!H.observations ? <Empty>Aucune observation à cet horizon pour l'instant. Le suivi se fait automatiquement après chaque analyse, tant que l'application est ouverte.</Empty> : (
        <>
          <Tbl title="Global" data={{ "Toutes analyses": H.overall }} />
          <Tbl title="Par tranche de score" data={H.by_score} />
          <Tbl title="Par verdict" data={H.by_verdict} />
          <Tbl title="Par launchpad" data={H.by_launchpad} />
          <Tbl title="Par market cap initiale" data={H.by_mcap} />
          <Card title="Qualité du verdict BUY SETUP">
            <div className="text-[12px]">Précision {H.buy_setup.precision != null ? `${Math.round(H.buy_setup.precision * 100)}%` : "—"} · Rappel {H.buy_setup.recall != null ? `${Math.round(H.buy_setup.recall * 100)}%` : "—"} · Faux positifs {H.buy_setup.false_positives}</div>
          </Card>
          {H.probability_model && (
            <Card title="Modèle de probabilité (validation chronologique 60/20/20)">
              {H.probability_model.usable ? <div className="text-[12px] text-good">Validé · Brier {H.probability_model.brier} (taux de base {H.probability_model.brier_base_rate}) · ECE {H.probability_model.ece}</div>
                : <div className="text-[12px] text-warn">{H.probability_model.reason} — {H.probability_model.observations} observations{H.probability_model.test_needed ? `, test ${H.probability_model.test_available}/${H.probability_model.test_needed}` : ""}</div>}
            </Card>
          )}
        </>
      )}
      <Card title="Versions du modèle de scoring">
        {r.model_versions.map((m: any) => <div key={m.id} className="border-b border-line/60 py-1 text-[11px] last:border-0">v{m.id} · {dateTime(m.created_at)} · {m.note} · {Object.entries(m.weights).map(([k, w]) => `${k} ${w}%`).join(", ")}</div>)}
      </Card>
    </div>
  );
}

function ScalpPerf({ sp }: { sp: any }) {
  if (!sp) return null;
  const T = ({ data }: { data: any }) => (
    <table className="w-full text-[12px]">
      <thead className="text-left text-[10px] uppercase text-muted"><tr><th>Groupe</th><th>Trades</th><th>Réussite</th><th>Gagnés / perdus / ni l'un ni l'autre</th><th>PnL moyen</th><th>Temps médian vers l'objectif</th></tr></thead>
      <tbody>{Object.entries(data).map(([k, x]: any) => (
        <tr key={k} className="border-t border-line/60"><td className="py-1">{k}</td><td>{x.n}</td>
          <td><b>{x.win_rate != null ? `${Math.round(x.win_rate * 100)}%` : "—"}</b> <span className="text-muted">[{Math.round(x.ci95[0] * 100)}–{Math.round(x.ci95[1] * 100)}]</span></td>
          <td>{x.wins} / {x.losses} / {x.open}</td>
          <td className={(x.avg_pnl_pct ?? 0) >= 0 ? "text-good" : "text-bad"}>{x.avg_pnl_pct != null ? `${x.avg_pnl_pct > 0 ? "+" : ""}${x.avg_pnl_pct}%` : "—"}</td>
          <td>{x.median_minutes_to_target != null ? `${x.median_minutes_to_target} min` : "—"}</td></tr>))}</tbody>
    </table>
  );
  return (
    <Card title="Mes résultats scalp (objectif avant stop, 1 h)">
      {!sp.observations ? <Empty>Aucun trade rejoué pour l'instant ({sp.pending} en attente). Chaque analyse est rejouée 1 h après, tant que l'application est ouverte.</Empty> : (
        <div className="space-y-2">
          <T data={{ "Toutes les analyses": sp.overall }} />
          {Object.keys(sp.by_decision).length > 0 && <><div className="text-[11px] text-muted">Par décision de la checklist</div><T data={sp.by_decision} /></>}
          {Object.keys(sp.by_score).length > 0 && <><div className="text-[11px] text-muted">Par note</div><T data={sp.by_score} /></>}
          <div className="text-[11px] text-muted">{sp.definition} {sp.pending} analyse(s) en attente de rejeu.</div>
        </div>
      )}
    </Card>
  );
}
