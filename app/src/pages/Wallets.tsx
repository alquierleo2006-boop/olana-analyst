import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { age, short } from "../lib/format";
import { Badge, Button, Card, Empty, Spinner } from "../components/ui";

export default function Wallets({ back }: { back: () => void }) {
  const [rows, setRows] = useState<any[]>([]);
  const [addr, setAddr] = useState(""); const [label, setLabel] = useState("");
  const [err, setErr] = useState<string | null>(null); const [busy, setBusy] = useState<string | null>(null);
  const load = () => api("/api/wallets").then(setRows).catch(() => {});
  useEffect(() => { load(); }, []);
  const add = async () => {
    setErr(null);
    try { await api("/api/wallets", { method: "POST", body: JSON.stringify({ address: addr.trim(), label: label.trim() || null }) }); setAddr(""); setLabel(""); load(); }
    catch (e: any) { setErr(e.message); }
  };
  const evaluate = async (a: string) => {
    setBusy(a); setErr(null);
    try { await api(`/api/wallets/${a}/evaluate`, { method: "POST" }); load(); } catch (e: any) { setErr(e.message); } finally { setBusy(null); }
  };
  const inp = "rounded-md border border-line bg-panel px-2 py-1.5 text-[12px] outline-none focus:border-info/60";
  return (
    <div className="space-y-2.5 p-3">
      <div className="flex items-center justify-between"><Button onClick={back}>← Accueil</Button><h2 className="text-[13px] font-bold">SMART MONEY</h2><span /></div>
      <Card title="Suivre un wallet public">
        <div className="flex gap-1.5"><input className={inp + " flex-1 font-mono"} placeholder="Adresse du wallet" value={addr} onChange={(e) => setAddr(e.target.value)} />
          <input className={inp + " w-28"} placeholder="Étiquette" value={label} onChange={(e) => setLabel(e.target.value)} />
          <Button kind="primary" onClick={add} disabled={!addr.trim()}>Ajouter</Button></div>
        {err && <div className="mt-1 text-[12px] text-bad">{err}</div>}
        <div className="mt-1 text-[11px] text-muted">L'évaluation (PnL, win rate) utilise les transactions enrichies Helius (clé gratuite). Moins de 20 positions clôturées = résultats non fiables.</div>
      </Card>
      {rows.length === 0 ? <Empty>Aucun wallet suivi.</Empty> : rows.map((w) => {
        const s = w.stats;
        return (
          <Card key={w.address} title={<span className="normal-case tracking-normal text-ink">{w.label || "Wallet"} <span className="font-mono text-muted">{short(w.address, 6)}</span></span>}
            right={<div className="flex gap-1"><Button onClick={() => evaluate(w.address)} disabled={busy === w.address}>{busy === w.address ? <Spinner /> : "Évaluer"}</Button>
              <Button kind="danger" onClick={() => api(`/api/wallets/${w.address}`, { method: "DELETE" }).then(load)}>Retirer</Button></div>}>
            {!s ? <div className="text-[12px] text-muted">Pas encore évalué.</div> : (
              <div className="grid grid-cols-2 gap-x-3 text-[12px] sm:grid-cols-4">
                <span>Positions clôturées <b>{s.closed_positions}</b></span>
                <span>Win rate <b>{s.win_rate != null ? `${Math.round(s.win_rate * 100)}%` : "—"}</b></span>
                <span>PnL réalisé <b className={s.realized_pnl_sol >= 0 ? "text-good" : "text-bad"}>{s.realized_pnl_sol} SOL</b></span>
                <span>ROI médian <b>{s.median_roi != null ? `${Math.round(s.median_roi * 100)}%` : "—"}</b></span>
                <span>7 j : <b>{s.periods["7j"].trades}</b> trades, {s.periods["7j"].pnl_sol} SOL</span>
                <span>30 j : <b>{s.periods["30j"].trades}</b> trades, {s.periods["30j"].pnl_sol} SOL</span>
                <span>Frais <b>{s.fees_sol} SOL</b></span>
                <span>{s.performant ? <Badge tone="good">performant</Badge> : s.reliable ? <Badge tone="muted">fiable, non performant</Badge> : <Badge tone="warn">échantillon insuffisant</Badge>}</span>
                <span className="col-span-full text-[10px] text-muted">{s.transactions_analysed} transactions analysées · évalué {age(s.computed_at)} · {s.method}</span>
              </div>
            )}
          </Card>
        );
      })}
    </div>
  );
}
