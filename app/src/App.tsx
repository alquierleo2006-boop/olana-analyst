import { useCallback, useEffect, useRef, useState } from "react";
import { api, initBackend, waitForBackend, wsUrl } from "./lib/api";
import { extractMint } from "./lib/mint";
import { notify, onShortcut, registerShortcut, setAlwaysOnTop, setWindowSize } from "./lib/native";
import TitleBar from "./components/TitleBar";
import Home from "./pages/Home";
import Analysis from "./pages/Analysis";
import History from "./pages/History";
import Narratives from "./pages/Narratives";
import Wallets from "./pages/Wallets";
import Performance from "./pages/Performance";
import Settings from "./pages/Settings";
import { Spinner } from "./components/ui";
import { setEdition } from "./lib/edition";

type Page = "home" | "analysis" | "history" | "narratives" | "wallets" | "performance" | "settings";

export default function App() {
  const [ready, setReady] = useState<"wait" | "ok" | "fail">("wait");
  const [page, setPage] = useState<Page>("home");
  const [aid, setAid] = useState<number | null>(null);
  const [settings, setSettings] = useState<any>(null);
  const [health, setHealth] = useState<any>(null);
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [compact, setCompact] = useState(false);
  const settingsRef = useRef<any>(null);
  settingsRef.current = settings;

  const analyze = useCallback(async (mint: string) => {
    setBusy(true); setError(null);
    try {
      const r = await api("/api/analyze", { method: "POST", body: JSON.stringify({ mint }) });
      setAid(r.analysis_id); setPage("analysis");
    } catch (e: any) {
      setError(e.message); setPage("home");
    } finally { setBusy(false); }
  }, []);

  useEffect(() => {
    (async () => {
      await initBackend();
      if (!(await waitForBackend())) { setReady("fail"); return; }
      try { setEdition((await api("/api/health")).edition); } catch {}
      document.title = (await import("./lib/edition")).appFullName();
      const s = (await api("/api/settings")).settings;
      setSettings(s); setCompact(!!s.compact_mode);
      setAlwaysOnTop(!!s.always_on_top);
      registerShortcut(s.shortcut);
      setReady("ok");
    })();
  }, []);

  // Santé des fournisseurs (indicateurs de l'accueil)
  useEffect(() => {
    if (ready !== "ok") return;
    const load = () => api("/api/health").then(setHealth).catch(() => setHealth(null));
    load();
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, [ready]);

  // Raccourci global : le presse-papiers est lu par la couche native uniquement à ce moment-là.
  useEffect(() => {
    let off = () => {};
    onShortcut((clip) => {
      const m = extractMint(clip);
      setPage("home");
      if (!m) { setInput(clip.slice(0, 100)); setError("Le presse-papiers ne contient pas d'adresse Solana valide."); return; }
      setInput(m); setError(null);
      if (settingsRef.current?.auto_analyze_on_shortcut) analyze(m);
    }).then((f) => (off = f));
    return () => off();
  }, [analyze]);

  // Notifications du backend → notifications Windows
  useEffect(() => {
    if (ready !== "ok") return;
    let ws: WebSocket | null = null, stop = false;
    const connect = () => {
      ws = new WebSocket(wsUrl("/ws/events"));
      ws.onmessage = (e) => { const ev = JSON.parse(e.data); notify(ev.title, ev.body); };
      ws.onclose = () => { if (!stop) setTimeout(connect, 3000); };
    };
    connect();
    return () => { stop = true; ws?.close(); };
  }, [ready]);

  useEffect(() => { setWindowSize(compact ? 420 : 560, compact ? 560 : 760); }, [compact]);

  const go = (p: string, arg?: any) => { if (p === "analysis") setAid(arg); setPage(p as Page); };
  const home = () => setPage("home");

  return (
    <div className="app-shell flex h-full flex-col overflow-hidden">
      <TitleBar pinned={!!settings?.always_on_top} compact={compact}
        onPin={async () => { const s = (await api("/api/settings", { method: "PUT", body: JSON.stringify({ always_on_top: !settings.always_on_top }) })).settings; setSettings(s); setAlwaysOnTop(s.always_on_top); }}
        onCompact={() => setCompact(!compact)} onSettings={() => setPage("settings")} />
      <main className="min-h-0 flex-1 overflow-y-auto">
        {ready === "wait" && <div className="grid h-full place-items-center text-muted"><div><Spinner /> Démarrage du moteur d'analyse…</div></div>}
        {ready === "fail" && <div className="p-6 text-center text-bad">Le moteur d'analyse local ne répond pas. Redémarre l'application ; si le problème persiste, consulte le fichier journal (voir README).</div>}
        {ready === "ok" && <>
          {page === "home" && <Home onAnalyze={analyze} go={go} health={health} input={input} setInput={setInput} error={error} setError={setError} busy={busy} />}
          {page === "analysis" && aid && <Analysis key={aid} id={aid} compact={compact} onBack={home} onReanalyze={analyze} />}
          {page === "history" && <History open={(id) => go("analysis", id)} back={home} />}
          {page === "narratives" && <Narratives back={home} analyze={analyze} />}
          {page === "wallets" && <Wallets back={home} />}
          {page === "performance" && <Performance back={home} />}
          {page === "settings" && <Settings back={home} onSaved={(s) => { setSettings(s); setAlwaysOnTop(s.always_on_top); }} />}
        </>}
      </main>
    </div>
  );
}
