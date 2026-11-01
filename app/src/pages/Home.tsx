import { FormEvent, useEffect, useState } from "react";
import { api } from "../lib/api";
import { age, scoreTone, short, verdictTone } from "../lib/format";
import { MINT_RE, extractMint } from "../lib/mint";
import { readClipboard } from "../lib/native";
import { Badge, Button, Tone } from "../components/ui";

export default function Home({ onAnalyze, go, health, input, setInput, error, setError, busy }:
  { onAnalyze: (mint: string) => void; go: (p: string, arg?: any) => void; health: any; input: string; setInput: (s: string) => void;
    error: string | null; setError: (s: string | null) => void; busy: boolean }) {
  const [recent, setRecent] = useState<any[]>([]);
  useEffect(() => { api("/api/history?limit=6").then(setRecent).catch(() => {}); }, []);

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    const m = extractMint(input);
    if (!m || !MINT_RE.test(m)) { setError("Adresse invalide : colle une adresse de token Solana (32 à 44 caractères base58)."); return; }
    setError(null);
    onAnalyze(m);
  };
  const paste = async () => { const t = await readClipboard(); setInput(t.trim()); setError(null); };

  const prov = health?.providers || [];
  const ok = prov.filter((p: any) => p.status === "ok").length;
  const bad = prov.filter((p: any) => p.status === "erreur");
  const nar = health?.narrative_engine;
  return (
    <div className="flex h-full flex-col gap-3 p-4">
      <div className="flex items-center gap-2.5">
        <Logo />
        <div>
          <div className="text-[15px] font-bold leading-tight">Solana AI Desktop Analyst</div>
          <div className="text-[11px] text-muted">Analyse à la demande · lecture seule · aucun achat automatique</div>
        </div>
      </div>

      <form onSubmit={submit} className="space-y-2">
        <div className={`flex items-center gap-2 rounded-lg border bg-panel px-2.5 py-2 ${error ? "border-bad/60" : "border-line focus-within:border-info/60"}`}>
          <input autoFocus value={input} onChange={(e) => { setInput(e.target.value); setError(null); }} spellCheck={false}
            placeholder="Colle l'adresse Mint du token (ou un lien DexScreener / pump.fun)…"
            className="min-w-0 flex-1 bg-transparent font-mono text-[12px] outline-none placeholder:font-sans placeholder:text-muted" aria-label="Adresse Mint" />
          <button type="button" onClick={paste} className="text-[11px] font-semibold text-muted hover:text-ink" title="Coller depuis le presse-papiers">Coller</button>
        </div>
        {error && <div className="text-[12px] text-bad" role="alert">{error}</div>}
        <Button type="submit" kind="primary" className="w-full py-2.5 text-[14px] tracking-wider" disabled={busy || !input.trim()}>{busy ? "Analyse en cours…" : "ANALYSER"}</Button>
      </form>

      <div className="grid grid-cols-2 gap-1.5">
        <Button onClick={() => go("history")}>Historique</Button>
        <Button onClick={() => go("narratives")}>Narratives mondiales</Button>
        <Button onClick={() => go("wallets")}>Smart money</Button>
        <Button onClick={() => go("performance")}>Performance</Button>
      </div>

      <div className="space-y-1 rounded-lg border border-line bg-panel p-2.5 text-[11px]">
        <StatusLine label="Moteur d'analyse" tone={health ? "good" : "bad"} text={health ? `prêt · v${health.version}` : "indisponible"} />
        <StatusLine label="Fournisseurs de données" tone={!health ? "muted" : bad.length ? "warn" : "good"}
          text={!health ? "—" : prov.length === 0 ? "pas encore sollicités" : `${ok} OK${bad.length ? ` · ${bad.length} en erreur (${bad.map((b: any) => b.name).slice(0, 3).join(", ")})` : ""}`} />
        <StatusLine label="Narratives mondiales" tone={nar?.last_compute ? "good" : "muted"}
          text={nar ? (nar.last_compute ? `${nar.state} · ${nar.articles_48h} articles · màj ${age(nar.last_compute)}` : nar.state) : "—"} />
        <StatusLine label="IA de synthèse" tone={health?.llm?.available ? "good" : "muted"} text={health?.llm?.available ? health.llm.provider : "désactivée (règles)"} />
        <StatusLine label="Helius (gratuit)" tone={health?.helius ? "good" : "muted"} text={health?.helius ? "configuré" : "non configuré — holders/smart money limités"} />
      </div>

      {recent.length > 0 && (
        <div className="min-h-0 flex-1 overflow-auto">
          <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted">Analyses récentes</div>
          {recent.map((r) => (
            <button key={r.id} onClick={() => go("analysis", r.id)} className="flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left hover:bg-panel">
              <span className="truncate text-[12px]"><b>{r.symbol ? `$${r.symbol}` : short(r.mint)}</b> <span className="text-muted">{age(r.created_at)}</span></span>
              <span className="flex gap-1">
                {r.score != null && <Badge tone={scoreTone(r.score) as Tone} icon={false}>{r.score}</Badge>}
                {r.verdict ? <Badge tone={verdictTone(r.verdict) as Tone}>{r.verdict}</Badge> : <Badge>{r.status}</Badge>}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function StatusLine({ label, tone, text }: { label: string; tone: Tone; text: string }) {
  const c = tone === "good" ? "bg-good" : tone === "warn" ? "bg-warn" : tone === "bad" ? "bg-bad" : "bg-muted";
  return <div className="flex items-center gap-2"><span className={`h-1.5 w-1.5 shrink-0 rounded-full ${c}`} /><span className="text-ink2">{label}</span><span className="ml-auto truncate text-right text-muted">{text}</span></div>;
}

export function Logo({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-label="logo">
      <rect width="32" height="32" rx="8" fill="#14171c" stroke="#262b33" />
      <path d="M8 21h11l5-4H13z" fill="#3987e5" /><path d="M8 11h11l5 4H13z" fill="#3987e5" opacity=".55" />
      <circle cx="23" cy="9" r="2.2" fill="#22b357" />
    </svg>
  );
}
