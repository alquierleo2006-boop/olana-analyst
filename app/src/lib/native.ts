// Pont vers les fonctions natives (Tauri). Toutes les fonctions sont sans effet hors de l'application desktop.
export const isTauri = () => typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

export async function setAlwaysOnTop(on: boolean) {
  if (!isTauri()) return;
  const { getCurrentWindow } = await import("@tauri-apps/api/window");
  await getCurrentWindow().setAlwaysOnTop(on);
}

export async function windowAction(a: "minimize" | "hide" | "startDrag") {
  if (!isTauri()) return;
  const { getCurrentWindow } = await import("@tauri-apps/api/window");
  const w = getCurrentWindow();
  if (a === "minimize") await w.minimize();
  if (a === "hide") await w.hide();
  if (a === "startDrag") await w.startDragging();
}

export async function setWindowSize(width: number, height: number) {
  if (!isTauri()) return;
  const { getCurrentWindow, LogicalSize } = await import("@tauri-apps/api/window");
  await getCurrentWindow().setSize(new LogicalSize(width, height));
}

/** Enregistre le raccourci global (côté Rust). Le presse-papiers n'est lu QUE quand il est déclenché. */
export async function registerShortcut(accelerator: string): Promise<string | null> {
  if (!isTauri()) return null;
  const { invoke } = await import("@tauri-apps/api/core");
  try {
    await invoke("set_shortcut", { accelerator });
    return null;
  } catch (e) {
    return String(e);
  }
}

export async function onShortcut(cb: (clipboard: string) => void): Promise<() => void> {
  if (!isTauri()) return () => {};
  const { listen } = await import("@tauri-apps/api/event");
  return listen<string>("shortcut-triggered", (e) => cb(e.payload || ""));
}

export async function readClipboard(): Promise<string> {
  if (isTauri()) {
    const { readText } = await import("@tauri-apps/plugin-clipboard-manager");
    return (await readText()) || "";
  }
  return navigator.clipboard?.readText?.() ?? "";
}

export async function copyText(text: string) {
  if (isTauri()) {
    const { writeText } = await import("@tauri-apps/plugin-clipboard-manager");
    return writeText(text);
  }
  return navigator.clipboard?.writeText?.(text);
}

export async function notify(title: string, body: string) {
  if (!isTauri()) return;
  const n = await import("@tauri-apps/plugin-notification");
  let ok = await n.isPermissionGranted();
  if (!ok) ok = (await n.requestPermission()) === "granted";
  if (ok) n.sendNotification({ title, body });
}

export async function openUrl(url: string) {
  if (!/^https?:\/\//.test(url)) return;
  if (isTauri()) {
    const { openUrl } = await import("@tauri-apps/plugin-opener");
    return openUrl(url);
  }
  window.open(url, "_blank", "noopener");
}
