import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { age, dateTime, short, usd } from "../lib/format";
import { Badge, Button, Card, Empty, Link, Spinner, Tone } from "../components/ui";

const stateTone = (s: string): Tone => (s === "ÉMERGENTE" || s === "EN ACCÉLÉRATION" ? "good" : s === "VIRALE" ? "info" : s === "SATURÉE" || s === "EN DÉCLIN" ? "warn" : "muted");

export default function Narratives({ back, analyze }: { back: () => void; analyze: (m: string) => void }) {
  const [data, setData] = useState<any>(null);
  const load = () => api("/api/narratives").then(setData).catch(() => {});
  useEffect(() => { load(); const t = setInterval(load, 15000); return () => clearInterval(t); }, []);
  const st = data?.status;
  return (
    <div className="space-y-2.5 p-3">
      <div className="flex items-center justify-between">
        <Button onClick={back}>← Accueil</Button>
        <h2 className="text-[13px] font-bold">GLOBAL NARRATIVE INTELLIGENCE</h2>
        <Button onClick={() => api("/api/narratives/refresh", { method: "POST" }).then(() => setTimeout(load, 3000))}>↻</Button>
      </div>
      {st && <div className="text-[11px] text-muted">État : {st.state} · {st.articles_48h} articles (48 h) · sources OK {st.sources_ok}, en échec {st.sources_failed} · dernier calcul {st.last_compute ? age(st.last_compute) : "—"}
        {st.errors?.length > 0 && <span className="text-warn" title={st.errors.join("\n")}> · erreurs de collecte</span>}</div>}
      {!data ? <Empty><Spinner /> Chargement…</Empty> : data.items.length === 0 ? <Empty>Première collecte en cours (actualités, GDELT, Reddit). Le classement apparaît après le premier calcul.</Empty> :
        data.items.map((n: any) => (
          <Card key={n.name} title={<span className="normal-case tracking-normal text-ink"><span className="text-muted">#{n.rank}</span> {n.name}</span>} right={<Badge tone={stateTone(n.state)}>{n.state}</Badge>}>
            <div className="text-[12px] text-ink2">{n.category} · {n.description}</div>
            <div className="mt-1 grid grid-cols-2 gap-x-3 text-[11px] text-muted sm:grid-cols-4">
              <span>Accélération <b className="text-ink">×{n.acceleration}</b></span>
              <span>Sources uniques <b className="text-ink">{n.unique_sources}</b></span>
              <span>Apparition <b className="text-ink">{dateTime(n.first_seen)}</b></span>
              <span>Sentiment <b className="text-ink">{n.sentiment.label}</b></span>
              <span>Saturation <b className="text-ink">{n.saturation != null ? `${Math.round(n.saturation * 100)}%` : "—"}</b></span>
              <span>Continuation <b className="text-ink">{n.continuation_score}</b></span>
              <span>Pays <b className="text-ink">{n.countries || "—"}</b></span>
              <span>Mots-clés <b className="text-ink">{n.keywords.slice(0, 3).join(", ")}</b></span>
            </div>
            {n.trigger && <div className="mt-1 text-[12px]">Déclencheur : <Link href={n.trigger.url}>{n.trigger.title}</Link> <span className="text-muted">({n.trigger.domain})</span></div>}
            {n.solana_tokens?.length > 0 && (
              <div className="mt-1.5 flex flex-wrap gap-1">
                <span className="text-[11px] text-muted">Tokens Solana associés ({n.solana_tokens_24h} créés en 24 h) :</span>
                {n.solana_tokens.map((t: any) => (
                  <button key={t.mint} onClick={() => analyze(t.mint)} title={`Analyser ${t.mint}`} className="rounded border border-line px-1.5 text-[11px] hover:border-info/60">
                    ${t.symbol || short(t.mint)} <span className="text-muted">{usd(t.mcap)}</span>
                  </button>
                ))}
              </div>
            )}
          </Card>
        ))}
      <div className="text-[11px] text-muted">Le classement favorise l'accélération inhabituelle, pas seulement le volume. Les reprises d'une même dépêche sont comptées une seule fois. Les narratives nées uniquement sur X apparaissent quand elles sont reprises par les médias ou Reddit.</div>
    </div>
  );
}
