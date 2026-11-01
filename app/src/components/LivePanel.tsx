import { useEffect, useState } from "react";
import { api, wsUrl } from "../lib/api";
import { pct, usd } from "../lib/format";
import { LineChart } from "./charts";
import { Badge, Button, Card } from "./ui";

/** Suivi en direct (mode Scalp) : market cap rafraîchie toutes les quelques secondes. Aucune transaction. */
export default function LivePanel({ mint, autoStarted }: { mint: string; autoStarted: boolean }) {
  const [s, setS] = useState<any>(null);
  const [on, setOn] = useState(autoStarted);
  const [above, setAbove] = useState(""); const [below, setBelow] = useState("");
  useEffect(() => { if (autoStarted) setOn(true); }, [autoStarted]);

  useEffect(() => {
    if (!on) return;
    let ws: WebSocket | null = null, stop = false;
    const connect = () => {
      ws = new WebSocket(wsUrl(`/ws/live/${mint}`));
      ws.onmessage = (e) => {
        const ev = JSON.parse(e.data);
        if (ev.type === "tick") { setS(ev.data); if (ev.data.targets) { setAbove((a) => a || (ev.data.targets.above ? String(Math.round(ev.data.targets.above)) : "")); setBelow((b) => b || (ev.data.targets.below ? String(Math.round(ev.data.targets.below)) : "")); } }
        if (ev.type === "stopped") { setOn(false); stop = true; }
      };
      ws.onclose = () => { if (!stop) setTimeout(connect, 1500); };
    };
    connect();
    return () => { stop = true; ws?.close(); };
  }, [on, mint]);

  const start = async () => {
    const r = await api(`/api/live/${mint}`, { method: "POST", body: JSON.stringify({
      above: above ? Number(above) : null, below: below ? Number(below) : null }) });  // vide = calculé au 1er relevé live
    setS(r); setOn(true);
  };
  const saveTargets = () => api(`/api/live/${mint}`, { method: "POST", body: JSON.stringify({ above: above ? Number(above) : null, below: below ? Number(below) : null }) }).then(setS);
  const stopIt = () => api(`/api/live/${mint}`, { method: "DELETE" }).then(() => setOn(false));

  if (!on && !s) {
    return (
      <Card title="Suivi live (scalp)">
        <div className="flex items-center justify-between gap-2">
          <span className="text-[12px] text-muted">Market cap en direct toutes les ~3 s, alertes de retournement, d'objectif et de vente du développeur.</span>
          <Button kind="primary" onClick={start}>▶ Suivre en live</Button>
        </div>
      </Card>
    );
  }
  const ch = s?.change || {};
  const dd = s?.drawdown_pct;
  const pts = (s?.points || []).map((p: number[]) => ({ x: p[0], y: p[1] }));
  const tone = (x: number | null | undefined) => (x == null ? "text-muted" : x >= 0 ? "text-good" : "text-bad");
  const inp = "w-24 rounded-md border border-line bg-panel2 px-2 py-1 text-right text-[12px] outline-none focus:border-info/60";
  return (
    <Card className="border-info/50" title={<span className="flex items-center gap-1.5">{on && <span className="pulse-soft inline-block h-2 w-2 rounded-full bg-bad" />}LIVE {s?.state?.source ? `· ${s.state.source}` : ""}</span>}
      right={on ? <Button kind="danger" onClick={stopIt}>■ Arrêter</Button> : <Button onClick={start}>▶ Reprendre</Button>}>
      <div className="flex flex-wrap items-end gap-x-5 gap-y-1">
        <div>
          <div className="text-[10px] uppercase tracking-wide text-muted">Market cap live</div>
          <div className="num text-[24px] font-bold leading-tight">{usd(s?.mcap)}</div>
        </div>
        {[["30 s", ch["30s"]], ["1 min", ch["1m"]], ["5 min", ch["5m"]], ["depuis le début", s?.change_since_start]].map(([k, x]: any) => (
          <div key={k}><div className="text-[10px] uppercase tracking-wide text-muted">{k}</div><div className={`num text-[15px] font-semibold ${tone(x)}`}>{pct(x)}</div></div>
        ))}
        <div><div className="text-[10px] uppercase tracking-wide text-muted">Sous le plus haut</div><div className={`num text-[15px] font-semibold ${dd != null && dd < -10 ? "text-bad" : "text-ink"}`}>{pct(dd)} <span className="text-[11px] text-muted">(haut {usd(s?.high)})</span></div></div>
      </div>
      <div className="mt-1.5 flex flex-wrap gap-x-4 text-[11px] text-muted">
        {s?.sol_flow?.["1m"] != null && <span>Flux net SOL 1 min : <b className={tone(s.sol_flow["1m"])}>{s.sol_flow["1m"] >= 0 ? "+" : ""}{s.sol_flow["1m"].toFixed(2)} SOL</b></span>}
        {s?.sol_flow?.["5m"] != null && <span>5 min : <b className={tone(s.sol_flow["5m"])}>{s.sol_flow["5m"] >= 0 ? "+" : ""}{s.sol_flow["5m"].toFixed(2)} SOL</b></span>}
        {s?.state?.curve_progress != null && <span>Bonding curve : <b className="text-ink">{s.state.curve_progress.toFixed(1)}%</b></span>}
        {s?.state?.txns_5m && <span>Achats/ventes 5 min : <b className="text-ink">{s.state.txns_5m.buys}/{s.state.txns_5m.sells}</b></span>}
        {s?.liquidity != null && <span>Liquidité : <b className="text-ink">{usd(s.liquidity)}</b></span>}
        {s?.state?.dev_sold && <Badge tone="bad">le dev a vendu</Badge>}
        {s?.state?.error && <span className="text-warn">erreur de lecture : {s.state.error}</span>}
      </div>
      {pts.length > 1 && <div className="mt-2"><LineChart points={pts} height={110} fmtY={(n) => usd(n, 1)} fmtX={(t) => new Date(t * 1000).toLocaleTimeString("fr-FR")} label="Market cap en direct" /></div>}
      <div className="mt-2 flex flex-wrap items-center gap-2 text-[12px]">
        <span className="text-ink2">Alerte si MC ≥</span><input className={inp} value={above} onChange={(e) => setAbove(e.target.value.replace(/[^\d]/g, ""))} placeholder="objectif $" />
        <span className="text-ink2">ou ≤</span><input className={inp} value={below} onChange={(e) => setBelow(e.target.value.replace(/[^\d]/g, ""))} placeholder="stop $" />
        {on && <Button onClick={saveTargets}>Appliquer</Button>}
      </div>
      {s?.alerts?.length > 0 && (
        <div className="mt-2 max-h-28 space-y-0.5 overflow-auto">
          {[...s.alerts].reverse().map((a: any, i: number) => (
            <div key={i} className="text-[12px]"><span className="text-muted">{new Date(a.ts * 1000).toLocaleTimeString("fr-FR")}</span>{" "}
              <Badge tone={a.level === "critique" ? "bad" : a.level === "élevé" ? "warn" : "info"}>{a.code}</Badge> {a.message}</div>
          ))}
        </div>
      )}
      <div className="mt-1 text-[10px] text-muted">Informations seulement : aucun ordre n'est passé. Les alertes apparaissent aussi en notification Windows.</div>
    </Card>
  );
}
