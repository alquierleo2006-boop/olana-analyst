import { windowAction } from "../lib/native";
import { Logo } from "../pages/Home";
import { appName } from "../lib/edition";

export default function TitleBar({ pinned, onPin, compact, onCompact, onSettings }: { pinned: boolean; onPin: () => void; compact: boolean; onCompact: () => void; onSettings: () => void }) {
  const btn = "grid h-6 w-6 place-items-center rounded text-[12px] text-muted hover:bg-panel2 hover:text-ink";
  return (
    <div data-tauri-drag-region onMouseDown={(e) => { if ((e.target as HTMLElement).dataset.tauriDragRegion !== undefined && e.button === 0) windowAction("startDrag"); }}
      className="flex h-8 shrink-0 items-center gap-2 border-b border-line px-2">
      <span data-tauri-drag-region className="pointer-events-none"><Logo size={16} /></span>
      <span data-tauri-drag-region className="flex-1 text-[11px] font-semibold text-ink2">{appName()}</span>
      <button className={btn} title={pinned ? "Ne plus garder au premier plan" : "Garder au premier plan"} onClick={onPin} aria-pressed={pinned}>
        <span className={pinned ? "text-info" : ""}>📌</span></button>
      <button className={btn} title={compact ? "Mode détaillé" : "Mode compact"} onClick={onCompact}>{compact ? "⤢" : "⤡"}</button>
      <button className={btn} title="Paramètres" onClick={onSettings}>⚙</button>
      <button className={btn} title="Réduire" onClick={() => windowAction("minimize")}>–</button>
      <button className={btn} title="Masquer (reste dans la zone de notification)" onClick={() => windowAction("hide")}>✕</button>
    </div>
  );
}
