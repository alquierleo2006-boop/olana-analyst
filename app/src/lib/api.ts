// Client du backend local (127.0.0.1). Dans Tauri, l'URL et le jeton de session viennent de la couche Rust.
// Hors Tauri (développement), ils viennent des paramètres d'URL ?backend=…&token=…
import { isTauri } from "./native";

let base = "http://127.0.0.1:8765";
let token = "";

export async function initBackend(): Promise<void> {
  if (isTauri()) {
    const { invoke } = await import("@tauri-apps/api/core");
    const cfg = await invoke<{ url: string; token: string }>("backend_config");
    base = cfg.url;
    token = cfg.token;
  } else {
    const p = new URLSearchParams(location.search);
    base = p.get("backend") || base;
    token = p.get("token") || "";
  }
}

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

export async function api<T = any>(path: string, init: RequestInit = {}): Promise<T> {
  const r = await fetch(base + path, {
    ...init,
    headers: { "Content-Type": "application/json", "x-analyst-token": token, ...(init.headers || {}) },
  });
  if (!r.ok) {
    let msg = `Erreur ${r.status}`;
    try {
      const j = await r.json();
      msg = typeof j.detail === "string" ? j.detail : msg;
    } catch {}
    throw new ApiError(msg, r.status);
  }
  return r.json();
}

export function wsUrl(path: string): string {
  return base.replace(/^http/, "ws") + path + (path.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(token);
}

export async function waitForBackend(timeoutMs = 30000): Promise<boolean> {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    try {
      await api("/api/health");
      return true;
    } catch {
      await new Promise((r) => setTimeout(r, 400));
    }
  }
  return false;
}
