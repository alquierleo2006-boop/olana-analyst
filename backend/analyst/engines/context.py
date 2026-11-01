"""Contexte d'une analyse : services partagés + résultats intermédiaires échangés entre modules."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable


class TokenNotFound(Exception):
    pass


class InvalidAddress(Exception):
    pass


@dataclass
class Services:
    http: Any
    rpc: Any
    dex: Any
    gecko: Any
    jup: Any
    rug: Any
    pump: Any
    web: Any
    news: Any
    llm: Any
    db: Any
    settings: Any
    secrets: Any


@dataclass
class Ctx:
    mint: str
    svc: Services
    result: dict
    emit: Callable[[str, Any], None] = lambda *_: None
    _futures: dict[str, asyncio.Future] = field(default_factory=dict)

    def _fut(self, key: str) -> asyncio.Future:
        if key not in self._futures:
            self._futures[key] = asyncio.get_event_loop().create_future()
        return self._futures[key]

    def provide(self, key: str, value: Any) -> None:
        f = self._fut(key)
        if not f.done():
            f.set_result(value)

    async def need(self, key: str, timeout: float = 10.0, default: Any = None) -> Any:
        try:
            return await asyncio.wait_for(asyncio.shield(self._fut(key)), timeout)
        except asyncio.TimeoutError:
            return default

    def has(self, key: str) -> bool:
        f = self._futures.get(key)
        return bool(f and f.done())

    def risk(self, level: str, code: str, message: str, source: str) -> None:
        """level : critique | élevé | moyen | info"""
        risks = self.result.setdefault("risks", [])
        if not any(r["code"] == code for r in risks):
            risks.append({"level": level, "code": code, "message": message, "source": source})

    def section(self, name: str) -> dict:
        return self.result.setdefault(name, {})
