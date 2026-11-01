import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { dateTime, pct, scoreTone, short, usd, verdictTone } from "../lib/format";
import { Badge, Button, Card, Empty, Tone } from "../components/ui";

export default function History({ open, back }: { open: (id: number) => void; back: () => void }) {
  const [rows, setRows] = useState<any[]>([]);
  const [f, setF] = useState({ q: "", verdict: "", launchpad: "", min_score: "", max_score: "", date_from: "", date_to: "", outcome: "" });
  const [sel, setSel] = useState<number[]>([]);
  const [cmp, setCmp] = useState<any[] | null>(null);
  useEffect(() => {
    const p = new URLSearchParams();
    Object.entries(f).forEach(([k, val]) => {
      if (!val) return;
      if (k.startsWith("date_")) p.set(k, String(new Date(val).getTime() / 1000 + (k === "date_to" ? 86399 : 0)));
      else p.set(k, val);
    });
    api(`/api/history?${p}`).then(setRows).catch(() => setRows([]));
  }, [f]);
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value });
  const inp = "rounded-md border border-line bg-panel px-2 py-1 text-[12px] outline-none focus:border-info/60";
  const doCompare = () => api(`/api/compare?ids=${sel.join(",")}`).then(setCmp);

  return (
    <div className="space-y-2.5 p-3">
      <div className="flex items-center justify-between"><Button onClick={back}>← Accueil</Button><h2 className="text-[13px] font-bold">HISTORY</h2>
        <Button kind="primary" disabled={sel.length < 2} onClick={doCompare}>Comparer ({sel.length})</Button></div>
      <div className="flex flex-wrap gap-1.5">
        <input className={inp + " w-40"} placeholder="Nom, ticker, adresse" value={f.q} onChange={set("q")} />
        <select className={inp} value={f.verdict} onChange={set("verdict")}><option value="">Verdict</option><option>BUY SETUP</option><option>WATCH</option><option>AVOID</option></select>
        <select className={inp} value={f.launchpad} onChange={set("launchpad")}><option value="">Launchpad</option><option value="pumpfun">Pump.fun</option><option value="letsbonk">LetsBonk</option><option value="launchlab">LaunchLab</option><option value="meteora_dbc">Meteora DBC</option><option value="unknown">Non identifié</option></select>
        <input className={inp + " w-16"} placeholder="Score ≥" value={f.min_score} onChange={set("min_score")} />
        <input className={inp + " w-16"} placeholder="Score ≤" value={f.max_score} onChange={set("max_score")} />
        <input type="date" className={inp} value={f.date_from} onChange={set("date_from")} title="Depuis" />
        <input type="date" className={inp} value={f.date_to} onChange={set("date_to")} title="Jusqu'au" />
        <select className={inp} value={f.outcome} onChange={set("outcome")}><option value="">Résultat</option><option value="up">En hausse</option><option value="down">En baisse</option></select>
      </div>
      {cmp && <Compare items={cmp} close={() => setCmp(null)} />}
      {rows.length === 0 ? <Empty>Aucune analyse ne correspond.</Empty> : (
        <div className="overflow-auto rounded-lg border border-line">
          <table className="w-full text-[12px]">
            <thead className="bg-panel text-left text-[10px] uppercase text-muted"><tr><th className="p-1.5"></th><th>Token</th><th>Date</th><th>Score</th><th>Verdict</th><th>MC initiale</th><th>1 h</th><th>24 h</th><th>7 j</th></tr></thead>
            <tbody>{rows.map((r) => (
              <tr key={r.id} className="cursor-pointer border-t border-line/60 hover:bg-panel" onClick={() => open(r.id)}>
                <td className="p-1.5" onClick={(e) => e.stopPropagation()}><input type="checkbox" checked={sel.includes(r.id)} onChange={() => setSel(sel.includes(r.id) ? sel.filter((x) => x !== r.id) : [...sel, r.id].slice(-6))} /></td>
                <td><b>{r.symbol ? `$${r.symbol}` : short(r.mint)}</b> <span className="text-muted">{r.launchpad || ""}</span></td>
                <td className="text-muted">{dateTime(r.created_at)}</td>
                <td>{r.score != null ? <Badge tone={scoreTone(r.score) as Tone} icon={false}>{r.score}</Badge> : "—"}</td>
                <td>{r.verdict ? <Badge tone={verdictTone(r.verdict) as Tone}>{r.verdict}</Badge> : <span className="text-muted">{r.status}</span>}</td>
                <td>{usd(r.mcap)}</td>
                {["1h", "24h", "7j"].map((h) => <td key={h} className={(r.performance?.[h] ?? 0) >= 0 ? "text-good" : "text-bad"}>{r.performance?.[h] != null ? pct(r.performance[h], 0) : <span className="text-muted">—</span>}</td>)}
              </tr>))}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Compare({ items, close }: { items: any[]; close: () => void }) {
  const cats = ["onchain", "momentum", "social", "narrative", "credibility", "smart_money"];
  const best = items.reduce((b, x) => ((x.scores?.global ?? -1) > (b?.scores?.global ?? -1) ? x : b), null as any);
  return (
    <Card title="Comparaison" right={<Button onClick={close}>Fermer</Button>}>
      <div className="overflow-auto">
        <table className="w-full text-[12px]">
          <thead><tr className="text-left text-[10px] uppercase text-muted"><th></th>{items.map((x) => <th key={x.id} className="p-1">{x.token.symbol ? `$${x.token.symbol}` : short(x.token.mint)}{x === best && <span className="text-good"> ★</span>}</th>)}</tr></thead>
          <tbody>
            {[["Score global", (x: any) => x.scores?.global ?? "—"], ["Verdict", (x: any) => x.scores?.verdict ?? "—"],
              ["Confiance", (x: any) => (x.scores ? `${Math.round(x.scores.confidence * 100)}%` : "—")],
              ["Risque", (x: any) => (x.scores ? `${x.scores.risk.score} (${x.scores.risk.label})` : "—")],
              ["Market cap", (x: any) => usd(x.market?.mcap?.v)], ["Liquidité", (x: any) => usd(x.market?.liquidity_usd?.v)],
              ...cats.map((c) => [c, (x: any) => x.scores?.categories?.[c]?.score ?? "—"] as const)].map(([k, fn]: any) => (
              <tr key={k} className="border-t border-line/60"><td className="py-1 text-ink2">{k}</td>{items.map((x) => <td key={x.id} className="num p-1 font-medium">{fn(x)}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-1 text-[11px] text-muted">★ = meilleur score global. Compare aussi le risque et la confiance avant de décider.</div>
    </Card>
  );
}
