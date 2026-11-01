import { ReactNode } from "react";
import { BarChart, HBars } from "../components/charts";
import { Badge, Card, Collapse, Empty, Link, Row, Spinner, Src, Stat, claimTone, riskTone, socialTone } from "../components/ui";
import { isTech } from "../lib/edition";
import { age, dateTime, num, pct, price, scoreTone, short, usd, v } from "../lib/format";

const S1 = "var(--color-series1)", S2 = "var(--color-series2)";
const hm = (t: number) => new Date(t * 1000).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });

function Pending({ d, mod, children }: { d: any; mod: string | string[]; children: ReactNode }) {
  const mods = Array.isArray(mod) ? mod : [mod];
  const st = mods.map((m) => d.modules?.[m]);
  if (st.some((x) => x?.status === "en cours")) return <Empty><Spinner /> Module en cours d'exécution…</Empty>;
  const err = st.find((x) => x && x.status !== "terminé");
  return (
    <>
      {err && <div className="mb-2 rounded-md border border-warn/40 bg-warn/10 p-2 text-[12px] text-warn">Module incomplet ({err.status}){err.error ? ` : ${err.error}` : ""}. Les données absentes ne sont pas remplacées par des estimations.</div>}
      {children}
    </>
  );
}

function SubScores({ sc }: { sc: any }) {
  const order = isTech() ? ["onchain", "credibility", "narrative", "momentum", "social"] : ["onchain", "momentum", "social", "narrative", "smart_money"];
  return (
    <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
      {order.map((k) => {
        const c = sc.categories[k];
        const t = scoreTone(c.score);
        return (
          <div key={k} className="rounded-md border border-line bg-panel2 p-2" title={(c.reasons || []).join("\n")}>
            <div className="text-[10px] uppercase tracking-wide text-muted">{c.label}{c.weight ? ` · ${c.weight}%` : " · info"}</div>
            <div className={`num text-[16px] font-bold ${t === "good" ? "text-good" : t === "warn" ? "text-warn" : t === "bad" ? "text-bad" : "text-muted"}`}>
              {c.score ?? "—"}<span className="text-[11px] font-normal text-muted">{c.score !== null ? "/10" : " indisponible"}</span>
            </div>
            <div className="h-1 rounded bg-line"><div className="h-1 rounded bg-ink2/60" style={{ width: `${c.confidence * 100}%` }} title="confiance" /></div>
          </div>
        );
      })}
      <div className="rounded-md border border-line bg-panel2 p-2">
        <div className="text-[10px] uppercase tracking-wide text-muted">Risk score (séparé)</div>
        <div className={`num text-[16px] font-bold ${sc.risk.score >= 5 ? "text-bad" : sc.risk.score >= 2 ? "text-warn" : "text-good"}`}>{sc.risk.score}<span className="text-[11px] font-normal text-muted">/10</span></div>
        <div className="text-[10px] text-muted">10 = risque maximal</div>
      </div>
    </div>
  );
}

export function Factors({ sc }: { sc: any }) {
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      <Card title="Points positifs">
        {sc.positives.length ? sc.positives.map((p: string, i: number) => <div key={i} className="py-0.5 text-[12px]"><span className="text-good">▲</span> {p}</div>) : <div className="text-[12px] text-muted">Aucun point positif marquant.</div>}
      </Card>
      <Card title="Points négatifs">
        {sc.negatives.length ? sc.negatives.map((p: string, i: number) => <div key={i} className="py-0.5 text-[12px]"><span className="text-bad">▼</span> {p}</div>) : <div className="text-[12px] text-muted">Aucun point négatif marquant.</div>}
      </Card>
    </div>
  );
}

export function Overview({ d }: { d: any }) {
  const sc = d.scores;
  if (!sc) return <Empty><Spinner /> Calcul du score…</Empty>;
  return (
    <div className="space-y-2.5">
      <SubScores sc={sc} />
      <Factors sc={sc} />
      {d.summary && <Card title={`Conclusion (${d.summary_source || "règles"})`}><p className="selectable text-[12px] leading-relaxed text-ink2">{d.summary}</p></Card>}
      <Card title="Modules d'analyse">
        <div className="grid grid-cols-2 gap-x-4 sm:grid-cols-3">
          {Object.entries(d.modules || {}).map(([k, m]: any) => (
            <div key={k} className="flex justify-between py-0.5 text-[11px]">
              <span className="text-ink2">{k}</span>
              <span className={m.status === "terminé" ? "text-good" : m.status === "en cours" ? "text-muted" : "text-warn"}>
                {m.status === "en cours" ? <Spinner size={9} /> : m.status}{m.ms !== undefined ? ` · ${(m.ms / 1000).toFixed(1)}s` : ""}
              </span>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

export function OnChain({ d }: { d: any }) {
  const m = d.market || {}, L = d.liquidity || {}, sec = d.security || {}, mom = m.momentum || {};
  const candles: number[][] = m.candles_1m || [];
  const last30 = candles.slice(-30);
  return (
    <Pending d={d} mod={["market", "security", "liquidity"]}>
      <div className="space-y-2.5">
        {m.unavailable && <Empty>{m.unavailable}</Empty>}
        <Card title="Marché">
          <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
            <Stat label="Prix" value={price(v(m.price_usd))} p={m.price_usd} />
            <Stat label="Market cap" value={usd(v(m.mcap))} p={m.mcap} />
            <Stat label="FDV" value={usd(v(m.fdv))} p={m.fdv} />
            <Stat label="Liquidité" value={usd(v(m.liquidity_usd))} p={m.liquidity_usd} />
            {(["m1", "m5", "m15", "h1", "h24"] as const).map((k) => (
              <Stat key={k} label={`Volume ${k.replace("m", "").replace("h", "")}${k.startsWith("m") ? " min" : " h"}`} value={usd(v(m.volume?.[k]))} p={m.volume?.[k]} />
            ))}
            <Stat label="Variation 1 h" value={pct(m.price_change?.h1)} tone={(m.price_change?.h1 ?? 0) >= 0 ? "good" : "bad"} />
            <Stat label="Variation 24 h" value={pct(m.price_change?.h24)} tone={(m.price_change?.h24 ?? 0) >= 0 ? "good" : "bad"} />
            <Stat label="Achats / ventes 1 h" value={`${num(m.txns?.h1?.buys)} / ${num(m.txns?.h1?.sells)}`} />
            <Stat label="Acheteurs / vendeurs 1 h" value={`${num(m.unique_traders?.h1?.buyers)} / ${num(m.unique_traders?.h1?.sellers)}`} sub="uniques (GeckoTerminal)" />
          </div>
          {m.bonding_curve && <div className="mt-2 text-[12px] text-ink2">Bonding curve : <b>{m.bonding_curve.progress_pct?.toFixed(1)}%</b> · réserves {m.bonding_curve.real_sol_reserves?.toFixed(2)} SOL</div>}
          {m.main_pair && <div className="mt-1 text-[11px] text-muted">Paire principale : {m.main_pair.dex} {m.main_pair.url && <Link href={m.main_pair.url}>DexScreener</Link>} · {m.pairs_count ?? "?"} paire(s)</div>}
        </Card>
        {last30.length > 1 && (
          <Card title="Volume — 30 dernières minutes">
            <BarChart labels={last30.map((c) => hm(c[0]))} series={[{ name: "Volume", color: S1, values: last30.map((c) => c[5]) }]} fmtY={(n) => usd(n, 0)} label="Volume par minute" />
          </Card>
        )}
        {m.txns && (
          <Card title="Achats et ventes (nombre de transactions)">
            <BarChart labels={["5 min", "1 h", "6 h", "24 h"]}
              series={[{ name: "Achats", color: S1, values: ["m5", "h1", "h6", "h24"].map((k) => m.txns[k]?.buys || 0) },
                       { name: "Ventes", color: S2, values: ["m5", "h1", "h6", "h24"].map((k) => m.txns[k]?.sells || 0) }]}
              fmtY={(n) => num(Math.round(n))} label="Achats et ventes" />
          </Card>
        )}
        <Card title="Momentum">
          {mom.unavailable ? <div className="text-[12px] text-muted">{mom.unavailable}</div> : (
            <div className="grid grid-cols-2 gap-x-4 sm:grid-cols-3">
              <Row k="Variation 5 / 15 / 60 min">{pct(mom.change?.["5m"])} · {pct(mom.change?.["15m"])} · {pct(mom.change?.["60m"])}</Row>
              <Row k="Accélération du volume">{mom.volume_acceleration ? `×${mom.volume_acceleration.toFixed(2)}` : "—"}</Row>
              <Row k="Sous le plus haut (fenêtre)">{pct(mom.drawdown_from_high_pct)}</Row>
              <Row k="Volatilité (1 min)">{mom.volatility_1m_pct ? `${mom.volatility_1m_pct.toFixed(2)}%` : "—"}</Row>
              <Row k="Consolidation">{mom.consolidating ? "oui" : "non"} ({pct(mom.range_30m_pct)} sur 30 min)</Row>
              <Row k="Volume sur 3 pics">{mom.top3_candles_volume_share ? `${(mom.top3_candles_volume_share * 100).toFixed(0)}%` : "—"}</Row>
            </div>
          )}
          {m.organic && (
            <div className="mt-2 text-[12px]">
              Activité : <Badge tone={m.organic.level === "suspect" ? "bad" : m.organic.level === "à surveiller" ? "warn" : "muted"}>{m.organic.level}</Badge>
              {m.organic.flags.map((f: string, i: number) => <div key={i} className="text-warn">• {f}</div>)}
              {m.organic.notes.map((f: string, i: number) => <div key={i} className="text-muted">• {f}</div>)}
            </div>
          )}
        </Card>
        <Card title={L.mode === "bonding_curve" ? "Liquidité — bonding curve (non retirable)" : "Liquidité réelle (devis Jupiter, aucune transaction)"} right={L.risk_level && <Badge tone={L.risk_level.score >= 2 ? "bad" : L.risk_level.score === 1 ? "warn" : "good"}>risque {L.risk_level.level}</Badge>}>
          {L.impact_tests ? (
            <table className="w-full text-[12px]">
              <thead><tr className="text-left text-[10px] uppercase text-muted"><th>Taille</th><th>Impact achat</th><th>Impact vente</th><th>Route</th></tr></thead>
              <tbody>{L.impact_tests.map((t: any) => (
                <tr key={t.size_sol} className="border-t border-line/60">
                  <td className="py-1">{t.size_sol} SOL</td>
                  <td className={(t.buy_impact_pct ?? 0) > 5 ? "text-warn" : ""}>{t.buy_impact_pct != null ? `${t.buy_impact_pct.toFixed(2)}%` : t.buy_error ? "erreur" : "pas de route"}</td>
                  <td className={(t.sell_impact_pct ?? 0) > 5 ? "text-warn" : ""}>{t.sell_impact_pct != null ? `${t.sell_impact_pct.toFixed(2)}%` : t.sell_error ? "erreur" : <span className="text-bad">pas de route</span>}</td>
                  <td className="truncate text-muted">{t.sell_route || t.buy_route || "—"}</td>
                </tr>))}</tbody>
            </table>
          ) : <div className="text-[12px] text-muted">Tests d'impact indisponibles (prix ou SOL inconnus).</div>}
          {L.note && <div className="mt-1 text-[12px] text-ink2">{L.note}</div>}
          {L.impact_source && <div className="text-[10px] text-muted">{L.impact_source}{L.position_sol ? ` · ta taille de position : ${L.position_sol} SOL` : ""}</div>}
          {L.mode !== "bonding_curve" && L.liq_to_mcap_pct != null && <div className="mt-1 text-[12px] text-ink2">Liquidité / market cap : {L.liq_to_mcap_pct.toFixed(1)}%</div>}
          {L.lp_locks?.map((l: any, i: number) => <div key={i} className="text-[12px] text-ink2">LP {l.market} : {l.locked_pct?.toFixed(0)}% verrouillée/brûlée <span className="text-muted">(RugCheck)</span></div>)}
          {L.risk_level?.reasons?.length > 0 && <div className="mt-1 text-[11px] text-muted">{L.risk_level.reasons.join(" · ")}</div>}
        </Card>
        <Card title="Sécurité technique">
          <div className="space-y-1">
            {(sec.checks || []).map((c: any) => (
              <div key={c.name} className="flex items-start gap-2 text-[12px]">
                <Badge tone={c.ok ? "good" : "bad"}>{c.ok ? "OK" : "RISQUE"}</Badge><span>{c.detail}</span>
              </div>
            ))}
          </div>
          <div className="mt-2 grid grid-cols-2 gap-2 text-[12px]">
            <Row k="Programme">{v(d.token?.token_program)}<Src p={d.token?.token_program} /></Row>
            {sec.metadata && <Row k="Métadonnées">{sec.metadata.mutable ? "modifiables" : "figées"}</Row>}
            {sec.token2022_extensions && <Row k="Extensions Token-2022">{sec.token2022_extensions.join(", ") || "aucune"}</Row>}
            {sec.rugcheck && <Row k="Score RugCheck (normalisé)">{sec.rugcheck.score_normalised ?? "—"}</Row>}
          </div>
          {sec.rugcheck?.risks?.length > 0 && (
            <Collapse title={`Signalements RugCheck (${sec.rugcheck.risks.length})`}>
              {sec.rugcheck.risks.map((r: any, i: number) => <div key={i} className="text-[12px]"><Badge tone={r.level === "danger" ? "bad" : "warn"}>{r.level}</Badge> {r.name}{r.description ? ` — ${r.description}` : ""}</div>)}
            </Collapse>
          )}
          {sec.rugcheck_error && <div className="mt-1 text-[11px] text-warn">RugCheck indisponible : {sec.rugcheck_error}</div>}
          <div className="mt-2 text-[11px] text-muted">{sec.note}</div>
        </Card>
      </div>
    </Pending>
  );
}

export function Holders({ d }: { d: any }) {
  const H = d.holders || {}, C = d.clusters || {};
  return (
    <Pending d={d} mod={["holders", "clusters"]}>
      <div className="space-y-2.5">
        <Card title="Concentration">
          <div className="grid grid-cols-3 gap-2 sm:grid-cols-5">
            <Stat label="Holders" value={num(v(H.total))} p={H.total} sub={H.holders_is_minimum ? "minimum" : undefined} />
            <Stat label="Top 5 (hors pools)" value={`${H.concentration_excl_technical?.top5 ?? "—"}%`} />
            <Stat label="Top 10 (hors pools)" value={`${H.concentration_excl_technical?.top10 ?? "—"}%`} tone={(H.concentration_excl_technical?.top10 ?? 0) > 45 ? "bad" : undefined} />
            <Stat label="Top 20 (hors pools)" value={`${H.concentration_excl_technical?.top20 ?? "—"}%`} />
            <Stat label="Top 50 (brut)" value={H.top50_pct_raw != null ? `${H.top50_pct_raw}%` : "—"} sub={H.top50_pct_raw == null ? "clé Helius requise" : undefined} />
          </div>
          <div className="mt-1 text-[11px] text-muted">Brut (avec pools/burn) : top 10 {H.concentration_raw?.top10 ?? "—"}% · comptes techniques {H.technical_pct ?? "—"}%
            {H.evolution_since_last && <> · évolution depuis la dernière analyse : {H.evolution_since_last.delta >= 0 ? "+" : ""}{H.evolution_since_last.delta} holders</>}</div>
        </Card>
        <Card title="Répartition des 20 plus gros comptes" right={<span className="text-[10px] text-muted">hachuré = pool / programme / burn</span>}>
          {H.top?.length ? <HBars fmt={(n) => `${n.toFixed(2)}%`} rows={H.top.map((r: any) => ({
            label: r.label || short(r.owner, 5), value: r.pct, technical: r.kind !== "wallet", title: `${r.owner}\n${r.kind}`,
          }))} /> : <Empty>Holders indisponibles.</Empty>}
          <div className="mt-1 text-[10px] text-muted">{H.source}</div>
        </Card>
        <Card title="Clusters de wallets (observations)">
          {C.unavailable ? <div className="text-[12px] text-muted">{C.unavailable}</div> : (
            <>
              {(C.clusters || []).length === 0 && <div className="text-[12px] text-muted">Aucun financement commun observé parmi les gros wallets.</div>}
              {(C.clusters || []).map((c: any, i: number) => (
                <div key={i} className="border-b border-line/60 py-1.5 text-[12px] last:border-0">
                  <b>{c.wallets.length} wallets</b> financés par <span className="font-mono">{short(c.funder, 6)}</span> — {c.supply_pct}% du supply <Badge tone="warn">lien observé</Badge>
                </div>
              ))}
              {C.fresh_wallets && <div className="mt-1 text-[12px] text-ink2">Wallets neufs (&lt; 20 tx) : {C.fresh_wallets.count}/{C.fresh_wallets.of}, {C.fresh_wallets.supply_pct}% du supply</div>}
              {C.rugcheck_insiders && <div className="text-[12px] text-ink2">RugCheck : réseaux d'initiés détectés = {String(C.rugcheck_insiders.detected)} ({C.rugcheck_insiders.networks})</div>}
              <div className="mt-1 text-[11px] text-muted">{C.method}</div>
            </>
          )}
        </Card>
      </div>
    </Pending>
  );
}

export function Developer({ d }: { d: any }) {
  const D = d.developer || {};
  const rep = D.reputation;
  return (
    <Pending d={d} mod="developer">
      {D.identified === false ? (
        <Card title="Développeur"><Badge tone="warn">NON IDENTIFIÉ</Badge><div className="mt-1 text-[12px] text-muted">{D.note}</div></Card>
      ) : (
        <div className="space-y-2.5">
          <Card title="Développeur" right={rep && <Badge tone={rep.score == null ? "muted" : rep.score >= 7 ? "good" : rep.score >= 4.5 ? "warn" : "bad"}>réputation {rep.score ?? "—"}/10 · {rep.label}</Badge>}>
            <div className="selectable font-mono text-[11px] break-all">{D.address}</div>
            <div className="text-[11px] text-muted">Identifié via : {D.address_source} ({D.address_status})</div>
            <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Stat label="Détient encore" value={v(D.current_holding_pct) != null ? `${Number(v(D.current_holding_pct)).toFixed(2)}%` : "—"} p={D.current_holding_pct} />
              <Stat label="Solde SOL" value={v(D.sol_balance) != null ? Number(v(D.sol_balance)).toFixed(2) : "—"} p={D.sol_balance} />
              <Stat label="Transactions" value={D.tx_count ? `${D.tx_count.is_minimum ? "≥ " : ""}${D.tx_count.value}` : "—"} />
              <Stat label="Wallet vu depuis" value={age(v(D.wallet_first_seen))} p={D.wallet_first_seen} />
            </div>
            {rep?.reasons?.length > 0 && <div className="mt-2 text-[12px] text-ink2">{rep.reasons.map((r: string, i: number) => <div key={i}>• {r}</div>)}</div>}
          </Card>
          <Card title="Lancements précédents">
            {D.history_stats ? (
              <>
                <div className="mb-1 text-[12px] text-ink2">{D.history_stats.count}{D.history_stats.count_is_minimum ? "+" : ""} token(s) · {D.history_stats.migrated} migré(s) · {D.history_stats.alive_now} encore liquide(s) · durée de vie médiane {D.history_stats.median_lifetime_h ? `${D.history_stats.median_lifetime_h.toFixed(1)} h` : "—"}</div>
                <div className="max-h-56 overflow-auto">
                  {(D.previous_tokens || []).map((t: any) => (
                    <div key={t.mint} className="flex justify-between border-b border-line/60 py-1 text-[12px]">
                      <span>{t.symbol || short(t.mint)} <span className="text-muted">{dateTime(t.created_at)}</span></span>
                      <span>{t.migrated && <Badge tone="info">migré</Badge>} <Badge tone={t.alive ? "good" : "muted"}>{t.alive ? `liq. ${usd(t.liquidity_usd)}` : "mort"}</Badge></span>
                    </div>
                  ))}
                </div>
                <div className="mt-1 text-[10px] text-muted">{D.previous_tokens_source}</div>
              </>
            ) : <div className="text-[12px] text-muted">{D.previous_tokens_error || "Aucun historique disponible."}</div>}
          </Card>
        </div>
      )}
    </Pending>
  );
}

const PLAT: Record<string, string> = { x: "X / Twitter", telegram: "Telegram", discord: "Discord", website: "Site web", github: "GitHub",
  instagram: "Instagram", tiktok: "TikTok", youtube: "YouTube", medium: "Medium", reddit: "Reddit" };

export function Social({ d }: { d: any }) {
  const S = d.social || {}, P = d.project || {};
  return (
    <Pending d={d} mod={isTech() ? ["social", "project"] : "social"}>
      <div className="space-y-2.5">
        {S.score && <Card title="Score social" right={<Badge tone={scoreTone(S.score.score) as any}>{S.score.score}/10 · confiance {Math.round(S.score.confidence * 100)}%</Badge>}>
          <div className="text-[12px] text-ink2">{S.score.reasons.join(" · ")}</div>
        </Card>}
        <Card title="Authenticité par réseau">
          <div className="space-y-2">
            {Object.entries(S.accounts || {}).map(([plat, accs]: any) => accs.map((a: any, i: number) => (
              <div key={plat + i} className="border-b border-line/60 pb-1.5 last:border-0">
                <div className="flex flex-wrap items-center gap-2 text-[12px]">
                  <b className="w-24">{PLAT[plat] || plat}</b>
                  <Badge tone={socialTone(a.status)}>{a.status}</Badge>
                  {a.url && <Link href={a.url}>{a.url.replace(/^https?:\/\//, "").slice(0, 48)}</Link>}
                </div>
                {a.reasons?.length > 0 && <div className="ml-26 mt-0.5 pl-[104px] text-[11px] text-muted">{a.reasons.map((r: string, k: number) => <div key={k}>• {r}</div>)}</div>}
                {a.declared_by && <div className="pl-[104px] text-[10px] text-muted">déclaré par : {a.declared_by.join(", ")}</div>}
              </div>
            )))}
          </div>
        </Card>
        <Card title="Limites de la vérification"><div className="text-[11px] text-muted">{(S.limitations || []).map((l: string, i: number) => <div key={i}>• {l}</div>)}</div></Card>
        {isTech() && (
        <Card title="Crédibilité du projet" right={P.score && <Badge tone={scoreTone(P.score.score) as any}>{P.score.score}/10</Badge>}>
            {P.has_site === false ? <div className="text-[12px] text-muted">Aucun site web analysable.</div> : (
              <div className="grid grid-cols-2 gap-x-4 text-[12px] sm:grid-cols-3">
                {[["Documentation", P.has_docs], ["Page équipe", P.team_page], ["Roadmap", P.roadmap], ["Produit décrit", P.product_signals],
                  ["Tokenomics", P.tokenomics], ["GitHub actif", P.github_active]].map(([k, val]: any) => (
                  <Row key={k} k={k}>{val ? <span className="text-good">oui</span> : <span className="text-muted">non</span>}</Row>
                ))}
              </div>
            )}
            {P.note && <div className="mt-1 text-[11px] text-muted">{P.note}</div>}
          </Card>
        )}
        {isTech() && P.github && !P.github.error && (
          <Card title="Code (GitHub)" right={<Badge tone={P.github.fork ? "bad" : P.github.active ? "good" : "warn"}>{P.github.fork ? "copie (fork)" : P.github.active ? "actif" : "inactif"}</Badge>}>
            <div className="text-[12px]"><Link href={P.github.url || "#"}>{P.github.repo}</Link> · {P.github.language || "—"} · {P.github.stars ?? 0} étoiles</div>
            <div className="text-[11px] text-muted">Créé le {String(P.github.created_at).slice(0, 10)} · dernier commit {String(P.github.pushed_at).slice(0, 10)}{P.github.fork ? ` · copie de ${P.github.parent}` : ""}{P.github.created_for_launch ? " · créé au moment du lancement" : ""}</div>
          </Card>
        )}
      </div>
    </Pending>
  );
}

export function Narrative({ d }: { d: any }) {
  const N = d.narrative || {};
  return (
    <Pending d={d} mod="narrative">
      <div className="space-y-2.5">
        <Card title="Correspondance narrative" right={N.score?.score != null && <Badge tone={scoreTone(N.score.score) as any}>{N.score.score}/10</Badge>}>
          {(N.score?.reasons || []).map((r: string, i: number) => <div key={i} className="text-[12px] text-ink2">• {r}</div>)}
          {N.score?.coverage_note && <div className="mt-1 text-[11px] text-muted">{N.score.coverage_note}</div>}
        </Card>
        {(N.matches || []).map((m: any) => (
          <Card key={m.name} title={m.name} right={<Badge tone={m.state === "ÉMERGENTE" || m.state === "EN ACCÉLÉRATION" ? "good" : m.state === "SATURÉE" || m.state === "EN DÉCLIN" ? "warn" : "info"}>{m.state}</Badge>}>
            <div className="text-[12px] text-ink2">Catégorie {m.category} · rang {m.rank} · accélération ×{m.acceleration} · termes communs : {m.matched_terms.join(", ")} · force {Math.round(m.strength * 100)}%</div>
            {m.trigger && <div className="mt-1 text-[12px]">Déclencheur : <Link href={m.trigger.url}>{m.trigger.title}</Link> <span className="text-muted">({m.trigger.domain}, {dateTime(m.trigger.published_at)})</span></div>}
            {m.solana_tokens_24h != null && <div className="text-[11px] text-muted">{m.solana_tokens_24h} token(s) Solana liés créés en 24 h</div>}
          </Card>
        ))}
        {N.competitors && !N.competitors.error && <Card title="Concurrence (même nom / ticker)"><div className="text-[12px] text-ink2">{N.competitors.count} homonyme(s), dont {N.competitors.older_count} plus ancien(s) et {N.competitors.bigger_count} plus gros.</div></Card>}
      </div>
    </Pending>
  );
}

export function News({ d }: { d: any }) {
  const F = d.factcheck || {};
  return (
    <Pending d={d} mod="factcheck">
      <div className="space-y-2.5">
        {F.note && <Empty>{F.note}</Empty>}
        {(F.claims || []).map((c: any, i: number) => (
          <Card key={i} title={<span className="normal-case tracking-normal">Affirmation {i + 1}</span>} right={<Badge tone={claimTone(c.status)}>{c.status}</Badge>}>
            <div className="selectable text-[12px] italic text-ink">« {c.text} »</div>
            <div className="mt-1 text-[11px] text-muted">Origine : {c.origin} · extraite par {c.extracted_by}{c.entity ? ` · entité : ${c.entity}` : ""} · confiance {Math.round(c.confidence * 100)}%</div>
            {c.reason && <div className="text-[11px] text-muted">{c.reason}</div>}
            {c.sources.length > 0 && <div className="mt-1 space-y-0.5">{c.sources.map((s: any, k: number) => <div key={k} className="text-[12px]">• <Link href={s.url}>{s.title}</Link> <span className="text-muted">({s.domain})</span></div>)}</div>}
            {c.note && <div className="mt-1 text-[10px] text-muted">{c.note}</div>}
          </Card>
        ))}
        {F.method && <div className="text-[11px] text-muted">{F.method}</div>}
      </div>
    </Pending>
  );
}

export function Originality({ d }: { d: any }) {
  const O = d.originality || {};
  const tone = O.verdict === "originale" ? "good" : O.verdict === "copie probable" ? "bad" : "warn";
  return (
    <Pending d={d} mod="originality">
      <div className="space-y-2.5">
        <Card title="Originalité" right={O.verdict && <Badge tone={tone as any}>{O.verdict} · {O.score}/10</Badge>}>
          {O.unavailable ? <div className="text-[12px] text-muted">{O.unavailable}</div> :
            (O.reasons || []).map((x: string, i: number) => <div key={i} className="text-[12px] text-ink2">• {x}</div>)}
          {O.keywords?.length > 0 && <div className="mt-1 text-[11px] text-muted">Mots-clés du concept : {O.keywords.join(", ")}</div>}
          {O.brand && <div className="text-[11px] text-warn">Marque reprise dans le nom : {O.brand}</div>}
        </Card>
        <Card title={`Tokens Solana au concept similaire (${O.similar_recent_7d ?? 0} lancés cette semaine)`}>
          {(O.similar_tokens || []).length === 0 ? <div className="text-[12px] text-muted">Aucun trouvé.</div> :
            O.similar_tokens.map((t: any) => (
              <div key={t.mint} className="flex justify-between border-b border-line/60 py-1 text-[12px] last:border-0">
                <span>${t.symbol} <span className="text-muted">{t.name} · « {t.keyword} »</span></span>
                <span className="text-muted">{usd(t.mcap)} · {age(t.created_at)}</span>
              </div>))}
        </Card>
        <Card title="Même nom / ticker">
          {(O.homonyms || []).length === 0 ? <div className="text-[12px] text-muted">Aucun homonyme.</div> :
            O.homonyms.map((t: any) => (
              <div key={t.mint} className="flex justify-between border-b border-line/60 py-1 text-[12px] last:border-0">
                <span>${t.symbol} <span className="text-muted">{t.name} · {short(t.mint)}</span></span>
                <span className="text-muted">{usd(t.mcap)} · {age(t.created_at)}</span>
              </div>))}
        </Card>
        <Card title="Projets open source similaires (GitHub)">
          {(O.similar_repos || []).length === 0 ? <div className="text-[12px] text-muted">{O.similar_repos_error ? `Recherche indisponible : ${O.similar_repos_error}` : "Aucun projet similaire trouvé."}</div> :
            O.similar_repos.map((x: any) => (
              <div key={x.repo} className="border-b border-line/60 py-1 text-[12px] last:border-0">
                <Link href={x.url}>{x.repo}</Link> <span className="text-muted">· {x.stars} étoiles · créé {String(x.created_at).slice(0, 10)}</span>
                {x.description && <div className="text-[11px] text-muted">{x.description}</div>}
              </div>))}
        </Card>
        {O.method && <div className="text-[11px] text-muted">{O.method} Ce sont des indices : un concept existant n'interdit pas un bon projet.</div>}
      </div>
    </Pending>
  );
}

export function Smart({ d }: { d: any }) {
  const SM = d.smart_money || {};
  return (
    <Pending d={d} mod="smart_money">
      <Card title="Smart money" right={SM.score?.score != null && <Badge tone={scoreTone(SM.score.score) as any}>{SM.score.score}/10</Badge>}>
        {(SM.score?.reasons || []).map((r: string, i: number) => <div key={i} className="text-[12px] text-ink2">• {r}</div>)}
        {(SM.holders || []).map((h: any) => (
          <div key={h.address} className="flex justify-between border-b border-line/60 py-1 text-[12px]">
            <span>{h.label || short(h.address, 6)} {h.performant ? <Badge tone="good">performant</Badge> : h.reliable ? <Badge tone="muted">fiable</Badge> : <Badge tone="muted">non évalué / &lt; 20 trades</Badge>}</span>
            <span>{h.supply_pct}% du supply{h.win_rate != null ? ` · win rate ${Math.round(h.win_rate * 100)}%` : ""}</span>
          </div>
        ))}
        {SM.note && <div className="mt-1 text-[11px] text-muted">{SM.note}</div>}
      </Card>
    </Pending>
  );
}

export function Risk({ d }: { d: any }) {
  const risks = [...(d.risks || [])].sort((a: any, b: any) => ["critique", "élevé", "moyen", "info"].indexOf(a.level) - ["critique", "élevé", "moyen", "info"].indexOf(b.level));
  const r = d.scores?.risk;
  return (
    <div className="space-y-2.5">
      {r && <Card title="Score de risque"><div className="text-[13px]"><b className={r.score >= 5 ? "text-bad" : r.score >= 2 ? "text-warn" : "text-good"}>{r.score}/10</b> · {r.label} · {r.count} risque(s) identifié(s)</div><div className="text-[11px] text-muted">{r.note}</div></Card>}
      <Card title="Risques identifiés">
        {risks.length === 0 ? <div className="text-[12px] text-muted">Aucun risque identifié par les modules terminés. Cela ne garantit pas l'absence de risque.</div> :
          risks.map((x: any) => (
            <div key={x.code} className="flex items-start gap-2 border-b border-line/60 py-1.5 text-[12px] last:border-0">
              <Badge tone={riskTone(x.level)}>{x.level}</Badge><span className="flex-1">{x.message}</span><span className="text-[11px] text-muted">{x.source}</span>
            </div>
          ))}
      </Card>
    </div>
  );
}

export function AIVerdict({ d }: { d: any }) {
  const sc = d.scores, P = d.probabilities;
  if (!sc) return <Empty><Spinner /> En attente…</Empty>;
  return (
    <div className="space-y-2.5">
      <Card title="Verdict">
        <div className="text-[14px] font-bold">{sc.verdict} — {sc.global ?? "—"}/10</div>
        <div className="text-[12px] text-ink2">{sc.verdict_reason}</div>
        {d.summary && <p className="selectable mt-2 text-[12px] leading-relaxed">{d.summary}</p>}
        <div className="mt-1 text-[10px] text-muted">Rédaction : {d.summary_source || "règles"}. {d.ai_error ? `IA indisponible : ${d.ai_error}` : ""}</div>
      </Card>
      <Card title="Calcul du score"><div className="text-[12px] text-ink2">{sc.explanation}</div><div className="mt-1 text-[11px] text-muted">{sc.disclaimer}</div></Card>
      <Factors sc={sc} />
      <Card title="Probabilité estimée de hausse">
        {!P ? <Empty>Disponible à la fin de l'analyse.</Empty> : (
          <>
            {P.scalp && <Row k={<b>{P.scalp.label}</b>}>{P.scalp.available
              ? <span>{Math.round(P.scalp.probability * 100)}% <span className="text-muted">[IC95 {Math.round(P.scalp.ci95[0] * 100)}–{Math.round(P.scalp.ci95[1] * 100)}%] · {P.scalp.comparable_observations} obs.</span></span>
              : <span className="text-warn">{P.scalp.message} <span className="text-muted">({P.scalp.observations} trades rejoués)</span></span>}</Row>}
            <div className="mb-1 mt-2 text-[11px] text-muted">Autres horizons — définition : {P.definition}</div>
            {Object.entries(P.horizons).map(([h, x]: any) => (
              <Row key={h} k={h}>{x.available ? <span>{Math.round(x.probability * 100)}% <span className="text-muted">[IC95 {Math.round(x.ci95[0] * 100)}–{Math.round(x.ci95[1] * 100)}%] · {x.comparable_observations} obs. comparables</span></span>
                : <span className="text-warn" title={x.detail || ""}>{x.message} <span className="text-muted">({x.observations} obs.)</span></span>}</Row>
            ))}
          </>
        )}
      </Card>
      {d.performance?.length > 0 && (
        <Card title="Suivi depuis l'analyse">
          {d.performance.map((p: any) => (
            <Row key={p.horizon} k={p.horizon}>{p.status === "pending" ? <span className="text-muted">prévu {dateTime(p.due_at)}</span> : p.status === "no_data" ? "plus de données" :
              <span>{pct(p.change_pct)} · MC {usd(p.mcap)}{p.status === "late" ? <span className="text-warn"> (relevé en retard)</span> : ""}</span>}</Row>
          ))}
        </Card>
      )}
    </div>
  );
}
