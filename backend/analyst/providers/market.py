"""Données de marché gratuites : DexScreener, GeckoTerminal, Jupiter (prix + impact réel)."""
from __future__ import annotations

from ..http import Http, ProviderError

DEX = "https://api.dexscreener.com"
GECKO = "https://api.geckoterminal.com/api/v2"
JUP = "https://lite-api.jup.ag"


class DexScreener:
    def __init__(self, http: Http) -> None:
        self.http = http

    async def pairs(self, mints: list[str]) -> list[dict]:
        out = []
        for i in range(0, len(mints), 30):
            data = await self.http.get_json("dexscreener", f"{DEX}/tokens/v1/solana/{','.join(mints[i:i + 30])}")
            out.extend(data if isinstance(data, list) else [])
        return out

    async def search(self, query: str) -> list[dict]:
        data = await self.http.get_json("dexscreener", f"{DEX}/latest/dex/search", params={"q": query})
        return [p for p in (data or {}).get("pairs") or [] if p.get("chainId") == "solana"]


class GeckoTerminal:
    def __init__(self, http: Http) -> None:
        self.http = http

    async def pools(self, mint: str) -> list[dict]:
        data = await self.http.get_json("geckoterminal", f"{GECKO}/networks/solana/tokens/{mint}/pools",
                                        headers={"Accept": "application/json;version=20230302"})
        return [d.get("attributes", {}) | {"dex": ((d.get("relationships") or {}).get("dex") or {}).get("data", {}).get("id")}
                for d in (data or {}).get("data") or []]

    async def ohlcv(self, pool: str, timeframe: str = "minute", aggregate: int = 1, limit: int = 300) -> list[list]:
        data = await self.http.get_json(
            "geckoterminal", f"{GECKO}/networks/solana/pools/{pool}/ohlcv/{timeframe}",
            params={"aggregate": aggregate, "limit": limit, "currency": "usd"},
            headers={"Accept": "application/json;version=20230302"})
        lst = ((data or {}).get("data") or {}).get("attributes", {}).get("ohlcv_list") or []
        return sorted(lst, key=lambda c: c[0])


class Jupiter:
    def __init__(self, http: Http) -> None:
        self.http = http

    async def prices(self, mints: list[str]) -> dict[str, float]:
        data = await self.http.get_json("jupiter", f"{JUP}/price/v3", params={"ids": ",".join(mints)})
        out = {}
        for m, info in (data or {}).items():
            if isinstance(info, dict) and info.get("usdPrice") is not None:
                out[m] = float(info["usdPrice"])
        return out

    async def quote(self, input_mint: str, output_mint: str, amount: int, slippage_bps: int = 5000) -> dict | None:
        try:
            return await self.http.get_json("jupiter", f"{JUP}/swap/v1/quote", params={
                "inputMint": input_mint, "outputMint": output_mint, "amount": str(amount),
                "slippageBps": slippage_bps}, timeout=6)
        except ProviderError as exc:
            if exc.status in (400, 404):
                return None  # pas de route : information utile en soi
            raise


class RugCheck:
    def __init__(self, http: Http) -> None:
        self.http = http

    async def report(self, mint: str) -> dict:
        return await self.http.get_json("rugcheck", f"https://api.rugcheck.xyz/v1/tokens/{mint}/report", timeout=10)


class PumpFunAPI:
    """API publique non officielle de pump.fun : utilisée comme source secondaire, toujours étiquetée."""
    BASE = "https://frontend-api-v3.pump.fun"

    def __init__(self, http: Http) -> None:
        self.http = http

    async def coin(self, mint: str) -> dict | None:
        try:
            return await self.http.get_json("pumpfun_api", f"{self.BASE}/coins/{mint}", timeout=5)
        except ProviderError as exc:
            if exc.status == 404:
                return None
            raise

    async def created_by(self, creator: str, limit: int = 50) -> list[dict]:
        data = await self.http.get_json("pumpfun_api", f"{self.BASE}/coins/user-created-coins/{creator}",
                                        params={"offset": 0, "limit": limit, "includeNsfw": "true"}, timeout=6)
        if isinstance(data, dict):
            data = data.get("coins") or data.get("data") or []
        return data if isinstance(data, list) else []
