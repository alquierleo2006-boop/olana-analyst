import { useEffect, useRef, useState } from "react";
import { api, wsUrl } from "./api";

/** Suit une analyse en direct : chaque module publie sa section dès qu'elle est prête. */
export function useAnalysis(id: number | null) {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [firstMs, setFirstMs] = useState<number | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!id) return;
    setData(null); setError(null); setFirstMs(null);
    let closed = false;
    const ws = new WebSocket(wsUrl(`/ws/analyses/${id}`));
    wsRef.current = ws;
    ws.onmessage = (e) => {
      const ev = JSON.parse(e.data);
      if (ev.type === "snapshot" || ev.type === "complete") {
        if (ev.data) setData((d: any) => ({ ...(d || {}), ...ev.data }));
        if (ev.type === "complete" && ev.data?.error) setError(ev.data.error);
      } else if (ev.type === "section") {
        setData((d: any) => ({ ...(d || {}), ...ev.data }));
      } else if (ev.type === "first_result") {
        setFirstMs(ev.data.ms);
      } else if (ev.type === "error") {
        setError(ev.data?.message || ev.data?.error || "Analyse impossible");
        if (ev.data?.status) setData((d: any) => ({ ...(d || {}), ...ev.data }));
      }
    };
    let poll: ReturnType<typeof setInterval> | null = null;
    ws.onerror = () => {
      // Repli si le WebSocket est indisponible : interrogation périodique jusqu'à la fin de l'analyse.
      if (closed || poll) return;
      const tick = () => api(`/api/analyses/${id}`).then((r) => {
        setData(r);
        if (r.error) setError(r.error);
        if (r.provisional === false && poll) { clearInterval(poll); poll = null; }
      }).catch((e) => setError(String(e.message || e)));
      tick();
      poll = setInterval(tick, 1000);
    };
    return () => { closed = true; ws.close(); if (poll) clearInterval(poll); };
  }, [id]);

  useEffect(() => {
    // Une fois terminée, recharge la version enregistrée (inclut le suivi de performance).
    if (id && data && data.provisional === false && !data.performance && !data.error) {
      api(`/api/analyses/${id}`).then((full) => setData(full)).catch(() => {});
    }
  }, [id, data?.provisional]);

  return { data, error, firstMs };
}
