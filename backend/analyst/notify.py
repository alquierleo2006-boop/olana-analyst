"""Notifications : diffusées à l'application (WebSocket → notification Windows) et optionnellement sur Telegram."""
from __future__ import annotations

import asyncio
import time


class Notifier:
    def __init__(self, http, settings, secrets) -> None:
        self.http, self.settings, self.secrets = http, settings, secrets
        self.subscribers: set[asyncio.Queue] = set()
        self.recent: list[dict] = []

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self.subscribers.add(q)
        return q

    def unsubscribe(self, q) -> None:
        self.subscribers.discard(q)

    def emit(self, kind: str, data: dict, title: str | None = None, body: str | None = None) -> None:
        cfg = self.settings.get("notifications", {})
        if not cfg.get("enabled", True) or cfg.get(kind) is False:
            return
        ev = {"kind": kind, "data": data, "title": title or kind, "body": body or "", "ts": time.time()}
        self.recent = (self.recent + [ev])[-50:]
        for q in list(self.subscribers):
            if not q.full():
                q.put_nowait(ev)
        if cfg.get("telegram"):
            asyncio.create_task(self._telegram(f"{ev['title']}\n{ev['body']}"))

    async def _telegram(self, text: str) -> None:
        tok, chat = self.secrets.get("telegram_bot_token"), self.secrets.get("telegram_chat_id")
        if not tok or not chat:
            return
        try:
            await self.http.post_json("telegram", f"https://api.telegram.org/bot{tok}/sendMessage",
                                      {"chat_id": chat, "text": text[:3500], "disable_web_page_preview": True})
        except Exception:
            pass
