import { FormEvent, useState } from "react";
import { api } from "../lib/api";
import { short } from "../lib/format";
import { MINT_RE, extractMint } from "../lib/mint";
import { readClipboard } from "../lib/native";
import { Button, Card, Link, Spinner } from "./ui";

const ICON: Record<string, [string, string]> = { ok: ["✓", "text-good"], attention: ["!", "text-warn"], bloquant: ["✕", "text-bad"], info: ["i", "text-info"] };

/** Édition Tech : vérifie un projet à partir de son lien X (compte, site, CA publié, cohérence). */
export default function XCheck({ mintInput, openAnalysis }: { mintInput: string; openAnalysis: (id: number) => void }) {
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [r, setR] = useState<any>(null);

  const submit = async (e?: FormEvent) => {
    e?.preventDefault();
    if (!/^(https?:\/\/)?(www\.|mobile\.)?(x|twitter)\.com\/.+/i.test(url.trim())) { setErr("Colle un lien X : x.com/compte ou x.com/compte/status/…"); return; }
    const m = extractMint(mintInput);
    setBusy(true); setErr(null); setR(null);
    try {
      setR(await api("/api/xcheck", { method: "POST", body: JSON.stringify({ url: url.trim(), mint: m && MINT_RE.test(m) ? m : null, analyze: true }) }));
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  const tone = r?.verdict === "CLEAN" ? "border-good/60 bg-good/10 text-good" : r?.verdict === "SUSPECT" ? "border-bad/60 bg-bad/10 text-bad" : "border-warn/60 bg-warn/10 text-warn";
  return (
    <div className="space-y-2">
      <form onSubmit={submit} className="flex gap-1.5">
        <div className="flex min-w-0 flex-1 items-center gap-2 rounded-lg border border-line bg-panel px-2.5 py-2 focus-within:border-[#9085e9]/60">
          <span className="text-[13px] text-muted">𝕏</span>
          <input value={url} onChange={(e) => { setUrl(e.target.value); setErr(null); }} spellCheck={false} aria-label="Lien X du projet"
            placeholder="Lien X / Twitter du projet (tweet du CA ou profil)…" className="min-w-0 flex-1 bg-transparent text-[12px] outline-none placeholder:text-muted" />
          <button type="button" onClick={async () => setUrl((await readClipboard()).trim())} className="text-[11px] font-semibold text-muted hover:text-ink">Coller</button>
        </div>
        <Button type="submit" disabled={busy || !url.trim()} className="border-[#9085e9]/60 text-[#b3abf2]">{busy ? <Spinner /> : "VÉRIFIER"}</Button>
      </form>
      {err && <div className="text-[12px] text-bad">{err}</div>}
      {r && (
        <Card title={<span>Vérification du compte X {r.handle ? `@${r.handle}` : ""}</span>} right={<span className="text-[10px] text-muted">{(r.ms / 1000).toFixed(1)} s</span>}>
          <div className={`mb-2 rounded-md border px-3 py-2 ${tone}`}>
            <div className="text-[15px] font-extrabold">{r.verdict === "CLEAN" ? "✅" : r.verdict === "SUSPECT" ? "⛔" : "⚠️"} {r.verdict}</div>
            <div className="text-[12px] text-ink2">{r.reason}</div>
          </div>
          {r.checks.map((c: any) => {
            const [i, cls] = ICON[c.status] || ["·", "text-muted"];
            return <div key={c.name} className="flex gap-2 border-b border-line/60 py-1 text-[12px] last:border-0"><span className={`w-3 shrink-0 text-center font-bold ${cls}`}>{i}</span><span><b>{c.name}</b> <span className="text-muted">— {c.detail}</span></span></div>;
          })}
          {r.site && <div className="mt-1.5 text-[12px]">Site : <Link href={r.site.url}>{r.site.url}</Link></div>}
          {r.summary && <p className="mt-1.5 text-[12px] text-ink2">{r.summary}</p>}
          {r.limits?.length > 0 && <div className="mt-1.5 text-[11px] text-warn">{r.limits.map((l: string, k: number) => <div key={k}>• {l}</div>)}</div>}
          {r.ca && (
            <div className="mt-2 flex items-center justify-between gap-2 rounded-md bg-panel2 p-2">
              <span className="text-[12px]">CA : <span className="font-mono">{short(r.ca, 8)}</span></span>
              {r.analysis_id && <Button kind="primary" onClick={() => openAnalysis(r.analysis_id)}>Voir l'analyse complète →</Button>}
            </div>
          )}
          <div className="mt-1 text-[10px] text-muted">{r.note}</div>
        </Card>
      )}
    </div>
  );
}
