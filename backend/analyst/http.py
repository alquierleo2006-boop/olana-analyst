"""Client HTTP partagé avec suivi de l'état de chaque fournisseur de données."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

import httpx

USER_AGENT = "SolanaAIDesktopAnalyst/0.1 (+analyse personnelle, lecture seule)"


class ProviderError(Exception):
    def __init__(self, provider: str, message: str, status: int | None = None):
        super().__init__(f"{provider}: {message}")
        self.provider, self.status = provider, status


@dataclass
class ProviderState:
    name: str
    status: str = "inconnu"  # ok | erreur | non configuré | désactivé | inconnu
    last_ok: float | None = None
    last_error: str | None = None
    last_latency_ms: int | None = None
    calls: int = 0
    errors: int = 0
    min_interval: float = 0.0
    _last_call: float = 0.0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)


# Intervalle minimal entre deux appels (respect des limites des API gratuites).
RATE_LIMITS = {"dexscreener": 0.2, "geckoterminal": 2.1, "rugcheck": 0.5, "gdelt": 5.5,
               "github": 1.0, "rdap": 0.5, "pumpfun_api": 0.3, "jupiter": 0.25, "reddit_rss": 2.0}


class Http:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(8.0, connect=4.0), follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json, text/html;q=0.9, */*;q=0.5"},
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
            transport=transport,
        )
        self.providers: dict[str, ProviderState] = {}
        self.disabled: set[str] = set()

    def state(self, name: str) -> ProviderState:
        if name not in self.providers:
            self.providers[name] = ProviderState(name, min_interval=RATE_LIMITS.get(name, 0.0))
        return self.providers[name]

    def mark(self, name: str, status: str) -> None:
        self.state(name).status = status

    async def _throttle(self, st: ProviderState) -> None:
        if st.min_interval <= 0:
            return
        async with st._lock:
            wait = st._last_call + st.min_interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            st._last_call = time.monotonic()

    async def request(self, provider: str, method: str, url: str, *, timeout: float | None = None,
                      max_bytes: int = 5_000_000, retries: int = 1, **kw) -> httpx.Response:
        if provider in self.disabled:
            raise ProviderError(provider, "désactivé dans les paramètres")
        st = self.state(provider)
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            await self._throttle(st)
            t0 = time.monotonic()
            st.calls += 1
            try:
                if timeout is not None:
                    kw["timeout"] = timeout
                r = await self.client.request(method, url, **kw)
                st.last_latency_ms = int((time.monotonic() - t0) * 1000)
                if r.status_code == 429 and attempt < retries:
                    await asyncio.sleep(1.0 + attempt)
                    continue
                if r.status_code >= 500 and attempt < retries:
                    await asyncio.sleep(0.4)
                    continue
                if len(r.content) > max_bytes:
                    raise ProviderError(provider, "réponse trop volumineuse")
                if r.status_code >= 400:
                    raise ProviderError(provider, f"HTTP {r.status_code}", r.status_code)
                st.status, st.last_ok = "ok", time.time()
                return r
            except ProviderError as exc:
                last_exc = exc
                if exc.status == 404:  # « introuvable » n'est pas une panne du fournisseur
                    st.status, st.last_ok = "ok", time.time()
                    raise
                break
            except (httpx.HTTPError, OSError) as exc:
                last_exc = ProviderError(provider, f"{type(exc).__name__}: {exc}")
                if attempt < retries:
                    await asyncio.sleep(0.3)
                    continue
        st.errors += 1
        st.status, st.last_error = "erreur", str(last_exc)
        raise last_exc  # type: ignore[misc]

    async def get_json(self, provider: str, url: str, **kw):
        r = await self.request(provider, "GET", url, **kw)
        try:
            return r.json()
        except ValueError as exc:
            raise ProviderError(provider, "JSON invalide") from exc

    async def post_json(self, provider: str, url: str, payload, **kw):
        r = await self.request(provider, "POST", url, json=payload, **kw)
        try:
            return r.json()
        except ValueError as exc:
            raise ProviderError(provider, "JSON invalide") from exc

    async def get_text(self, provider: str, url: str, **kw) -> str:
        r = await self.request(provider, "GET", url, **kw)
        return r.text

    def snapshot(self) -> list[dict]:
        return [{"name": s.name, "status": s.status, "last_ok": s.last_ok, "last_error": s.last_error,
                 "latency_ms": s.last_latency_ms, "calls": s.calls, "errors": s.errors}
                for s in sorted(self.providers.values(), key=lambda s: s.name)]

    async def close(self) -> None:
        await self.client.aclose()
