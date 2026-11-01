import { ReactNode, useEffect, useState } from "react";
import { api } from "../lib/api";
import { registerShortcut } from "../lib/native";
import { Badge, Button, Card } from "../components/ui";

const SECRETS: [string, string, string][] = [
  ["helius_api_key", "Clé Helius (gratuite)", "helius.dev → plan gratuit. Débloque le nombre de holders, le top 50 et le smart money."],
  ["llm_api_key", "Clé API de l'IA", "Facultatif : Groq / Gemini / OpenRouter ont des paliers gratuits. Inutile avec Ollama local."],
  ["github_token", "Jeton GitHub", "Facultatif : relève la limite de l'API publique GitHub."],
  ["telegram_bot_token", "Bot Telegram (notifications)", "Facultatif : jeton fourni par @BotFather."],
  ["telegram_chat_id", "Chat ID Telegram", "Facultatif : destinataire des notifications."],
];
const PROVIDERS: [string, string][] = [["dexscreener", "DexScreener"], ["geckoterminal", "GeckoTerminal"], ["jupiter", "Jupiter"], ["rugcheck", "RugCheck"],
  ["pumpfun_api", "pump.fun (API non officielle)"], ["gdelt", "GDELT"], ["rss", "Flux RSS / Google News"], ["reddit_rss", "Reddit RSS"],
  ["x_oembed", "X oEmbed public"], ["telegram_public", "Pages publiques Telegram"], ["discord_public", "Invitations Discord"], ["github", "GitHub"], ["rdap", "RDAP (âge des domaines)"]];
const LLM_PRESETS: Record<string, { base_url: string; model: string }> = {
  ollama: { base_url: "http://localhost:11434/v1", model: "llama3.1:8b" },
  groq: { base_url: "https://api.groq.com/openai/v1", model: "llama-3.3-70b-versatile" },
  gemini: { base_url: "https://generativelanguage.googleapis.com/v1beta/openai", model: "gemini-2.5-flash" },
  openrouter: { base_url: "https://openrouter.ai/api/v1", model: "meta-llama/llama-3.3-70b-instruct:free" },
};
const WEIGHTS: [string, string][] = [["onchain", "On-chain & sécurité"], ["momentum", "Momentum & marché"], ["narrative", "Narrative & actualités"],
  ["social", "Réseaux sociaux"], ["credibility", "Qualité & crédibilité"], ["smart_money", "Smart money"]];

export default function Settings({ back, onSaved }: { back: () => void; onSaved: (s: any) => void }) {
  const [s, setS] = useState<any>(null);
  const [sec, setSec] = useState<Record<string, boolean>>({});
  const [secVals, setSecVals] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState<string | null>(null);
  const [llmPreset, setLlmPreset] = useState("custom");
  useEffect(() => { api("/api/settings").then((r) => { setS(r.settings); setSec(r.secrets); }); }, []);
  if (!s) return null;
  const up = (patch: any) => setS({ ...s, ...patch });
  const save = async () => {
    setMsg(null);
    const err = await registerShortcut(s.shortcut);
    const r = await api("/api/settings", { method: "PUT", body: JSON.stringify(s) });
    for (const [k, val] of Object.entries(secVals)) {
      if (val !== undefined) await api(`/api/secrets/${k}`, { method: "PUT", body: JSON.stringify({ value: val }) });
    }
    const st = await api("/api/settings");
    setSec(st.secrets); setSecVals({});
    onSaved(r.settings);
    setMsg(err ? `Enregistré, mais raccourci refusé : ${err}` : "Paramètres enregistrés. Une modification des pondérations crée une nouvelle version du modèle.");
  };
  const inp = "rounded-md border border-line bg-panel2 px-2 py-1 text-[12px] outline-none focus:border-info/60";
  const totalW = WEIGHTS.reduce((a, [k]) => a + (Number(s.weights[k]) || 0), 0);
  return (
    <div className="space-y-2.5 p-3">
      <div className="flex items-center justify-between"><Button onClick={back}>← Accueil</Button><h2 className="text-[13px] font-bold">PARAMÈTRES</h2><Button kind="primary" onClick={save}>Enregistrer</Button></div>
      {msg && <div className="text-[12px] text-info">{msg}</div>}
      <Card title="Fenêtre et raccourci">
        <F k="Raccourci global"><input className={inp + " w-56 font-mono"} value={s.shortcut} onChange={(e) => up({ shortcut: e.target.value })} /></F>
        <div className="mb-1 text-[11px] text-muted">Format : CommandOrControl+Shift+Space, Alt+Shift+A… Choisis une combinaison non utilisée par ton terminal de trading. Le presse-papiers n'est lu qu'au moment où tu presses le raccourci.</div>
        <Chk label="Lancer l'analyse automatiquement après le raccourci" v={s.auto_analyze_on_shortcut} set={(x) => up({ auto_analyze_on_shortcut: x })} />
        <Chk label="Toujours au premier plan" v={s.always_on_top} set={(x) => up({ always_on_top: x })} />
        <Chk label="Mode compact par défaut" v={s.compact_mode} set={(x) => up({ compact_mode: x })} />
      </Card>
      <Card title="Clés API (stockées dans le coffre sécurisé du système)">
        {SECRETS.map(([k, label, help]) => (
          <div key={k} className="mb-2">
            <F k={<>{label} {sec[k] ? <Badge tone="good">configurée</Badge> : <Badge>absente</Badge>}</>}>
              <input type="password" className={inp + " w-56"} placeholder={sec[k] ? "•••••• (laisser vide = inchangé)" : "coller la clé"} value={secVals[k] ?? ""} onChange={(e) => setSecVals({ ...secVals, [k]: e.target.value })} />
            </F>
            <div className="text-[11px] text-muted">{help}{sec[k] && <> · <button className="text-bad" onClick={() => setSecVals({ ...secVals, [k]: "" })}>supprimer à l'enregistrement</button></>}</div>
          </div>
        ))}
        <F k="RPC Solana"><input className={inp + " w-72 font-mono"} value={s.rpc_url} onChange={(e) => up({ rpc_url: e.target.value })} /></F>
        <div className="text-[11px] text-muted">Ignoré si une clé Helius est configurée.</div>
      </Card>
      <Card title="Intelligence artificielle (facultative, gratuite possible)">
        <F k="Fournisseur">
          <select className={inp} value={s.llm.provider === "none" ? "none" : s.llm.provider === "anthropic" ? "anthropic" : llmPreset}
            onChange={(e) => { const p = e.target.value; setLlmPreset(p);
              if (p === "none" || p === "anthropic") up({ llm: { ...s.llm, provider: p } });
              else up({ llm: { provider: "openai_compatible", ...(LLM_PRESETS[p] || s.llm) } }); }}>
            <option value="none">Aucune (règles uniquement)</option><option value="ollama">Ollama (local, gratuit)</option><option value="groq">Groq (palier gratuit)</option>
            <option value="gemini">Google Gemini (palier gratuit)</option><option value="openrouter">OpenRouter (modèles gratuits)</option><option value="custom">Autre API compatible OpenAI</option><option value="anthropic">Anthropic (payant)</option>
          </select>
        </F>
        {s.llm.provider !== "none" && <>
          {s.llm.provider !== "anthropic" && <F k="URL de l'API"><input className={inp + " w-72 font-mono"} value={s.llm.base_url} onChange={(e) => up({ llm: { ...s.llm, base_url: e.target.value } })} /></F>}
          <F k="Modèle"><input className={inp + " w-56 font-mono"} value={s.llm.model} onChange={(e) => up({ llm: { ...s.llm, model: e.target.value } })} /></F>
        </>}
        <div className="text-[11px] text-muted">L'IA rédige la conclusion et extrait les affirmations à vérifier. Elle ne calcule jamais le score et reçoit les contenus externes comme données non fiables.</div>
      </Card>
      <Card title={<>Pondérations du score {totalW !== 100 && <span className="text-warn">(total {totalW}% — normalisé automatiquement)</span>}</>}>
        {WEIGHTS.map(([k, label]) => (
          <F key={k} k={label}><input type="range" min={0} max={50} value={s.weights[k]} onChange={(e) => up({ weights: { ...s.weights, [k]: Number(e.target.value) } })} /><span className="num w-10 text-right">{s.weights[k]}%</span></F>
        ))}
      </Card>
      <Card title="Seuils et risque">
        <F k="BUY SETUP si score ≥"><Num v={s.thresholds.buy_setup_min} set={(x) => up({ thresholds: { ...s.thresholds, buy_setup_min: x } })} /></F>
        <F k="AVOID si score <"><Num v={s.thresholds.avoid_below} set={(x) => up({ thresholds: { ...s.thresholds, avoid_below: x } })} /></F>
        <F k="Confiance minimale pour BUY SETUP"><Num v={s.thresholds.min_confidence_buy} step={0.05} set={(x) => up({ thresholds: { ...s.thresholds, min_confidence_buy: x } })} /></F>
        <F k="Niveau de risque accepté">
          <select className={inp} value={s.risk_tolerance} onChange={(e) => up({ risk_tolerance: e.target.value })}><option value="prudent">Prudent (risque max 3,5)</option><option value="normal">Normal (risque max 5)</option><option value="agressif">Agressif (risque max 6,5)</option></select>
        </F>
        <F k="Définition d'une hausse (%)"><Num v={s.rise_definition_pct} step={5} set={(x) => up({ rise_definition_pct: x })} /></F>
        <F k="Horizon affiché par défaut">
          <select className={inp} value={s.default_horizon} onChange={(e) => up({ default_horizon: e.target.value })}>{["15m", "1h", "6h", "24h", "7j"].map((h) => <option key={h}>{h}</option>)}</select>
        </F>
      </Card>
      <Card title="Sources de données">
        <div className="grid grid-cols-2">{PROVIDERS.map(([k, label]) => <Chk key={k} label={label} v={s.providers[k]} set={(x) => up({ providers: { ...s.providers, [k]: x } })} />)}</div>
        <F k="Launchpads reconnus">
          <div className="flex flex-wrap gap-2">{[["pumpfun", "Pump.fun"], ["letsbonk", "LetsBonk"], ["meteora_dbc", "Meteora DBC"], ["stonkfun", "Stonk.fun"]].map(([k, l]) => (
            <label key={k} className="flex items-center gap-1 text-[12px]"><input type="checkbox" checked={s.launchpads.includes(k)} onChange={(e) => up({ launchpads: e.target.checked ? [...s.launchpads, k] : s.launchpads.filter((x: string) => x !== k) })} />{l}</label>))}</div>
        </F>
        <F k="Rafraîchissement des narratives (min)"><Num v={s.narrative_refresh_minutes} step={1} set={(x) => up({ narrative_refresh_minutes: x })} /></F>
        <F k="Conservation de l'historique (jours)"><Num v={s.history_retention_days} step={30} set={(x) => up({ history_retention_days: x })} /></F>
        <Chk label="Suivi automatique des performances après analyse" v={s.tracking_enabled} set={(x) => up({ tracking_enabled: x })} />
      </Card>
      <Card title="Notifications">
        <Chk label="Activer les notifications" v={s.notifications.enabled} set={(x) => up({ notifications: { ...s.notifications, enabled: x } })} />
        <F k="Alerte si score ≥"><Num v={s.notifications.score_above} set={(x) => up({ notifications: { ...s.notifications, score_above: x } })} /></F>
        <F k="Alerte si le score varie de ≥"><Num v={s.notifications.score_change} set={(x) => up({ notifications: { ...s.notifications, score_change: x } })} /></F>
        {[["critical_risk", "Risque critique"], ["smart_money", "Plusieurs wallets suivis sur un token"], ["narrative_acceleration", "Narrative en accélération"], ["claim_confirmed", "Information confirmée"], ["telegram", "Envoyer aussi sur Telegram"]].map(([k, l]) => (
          <Chk key={k} label={l} v={s.notifications[k] !== false} set={(x) => up({ notifications: { ...s.notifications, [k]: x } })} />))}
      </Card>
      <div className="pb-2 text-center text-[11px] text-muted">Logiciel en lecture seule : aucune clé privée de wallet, aucune signature, aucun achat.</div>
    </div>
  );
}

function F({ k, children }: { k: ReactNode; children: ReactNode }) {
  return <div className="flex items-center justify-between gap-3 py-1 text-[12px]"><span className="text-ink2">{k}</span><span className="flex items-center gap-2">{children}</span></div>;
}
function Chk({ label, v, set }: { label: string; v: boolean; set: (x: boolean) => void }) {
  return <label className="flex items-center gap-2 py-0.5 text-[12px]"><input type="checkbox" checked={!!v} onChange={(e) => set(e.target.checked)} />{label}</label>;
}
function Num({ v, set, step = 0.5 }: { v: number; set: (x: number) => void; step?: number }) {
  return <input type="number" step={step} value={v} onChange={(e) => set(Number(e.target.value))} className="w-20 rounded-md border border-line bg-panel2 px-2 py-1 text-right text-[12px] outline-none" />;
}
