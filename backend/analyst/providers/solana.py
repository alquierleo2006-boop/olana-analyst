"""Accès blockchain Solana : RPC standard (public ou Helius gratuit) + décodage des comptes utiles."""
from __future__ import annotations

import base64
import struct

from ..http import Http, ProviderError

TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
METAPLEX_PROGRAM = "metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s"
WSOL_MINT = "So11111111111111111111111111111111111111112"
INCINERATOR = "1nc1nerator11111111111111111111111111111111"
SYSTEM_PROGRAM = "11111111111111111111111111111111"

# Programmes de launchpads / AMM connus (détection par le programme réel, pas par le nom).
PROGRAMS = {
    "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P": ("pumpfun", "Pump.fun (bonding curve)"),
    "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA": ("pumpswap", "PumpSwap AMM"),
    "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj": ("launchlab", "Raydium LaunchLab"),
    "dbcij3LWUppWqq96dh6gJWwBifmcGfLSB5D4DuSMaqN": ("meteora_dbc", "Meteora Dynamic Bonding Curve"),
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8": ("raydium_amm", "Raydium AMM v4"),
    "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C": ("raydium_cpmm", "Raydium CPMM"),
    "cpamdpZCGKUy5JxQXB4dcpGPiikHawvSWAd6mEn1sGG": ("meteora_damm2", "Meteora DAMM v2"),
}
PUMPFUN_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
LAUNCHLAB_PROGRAM = "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj"
PUMP_INITIAL_REAL_TOKENS = 793_100_000 * 10**6
PUMP_TOTAL_SUPPLY = 1_000_000_000 * 10**6


def find_pda(seeds: list[bytes], program: str) -> str:
    from solders.pubkey import Pubkey
    return str(Pubkey.find_program_address(seeds, Pubkey.from_string(program))[0])


def pubkey_bytes(addr: str) -> bytes:
    from solders.pubkey import Pubkey
    return bytes(Pubkey.from_string(addr))


def is_on_curve(addr: str) -> bool:
    """Une adresse hors courbe ed25519 est une PDA (compte de programme : pool, bonding curve, vault…)."""
    from solders.pubkey import Pubkey
    try:
        return Pubkey.from_string(addr).is_on_curve()
    except Exception:
        return True


def decode_pump_curve(data: bytes) -> dict | None:
    if len(data) < 49:
        return None
    vtok, vsol, rtok, rsol, supply = struct.unpack_from("<QQQQQ", data, 8)
    complete = bool(data[48])
    creator = None
    if len(data) >= 81:
        from solders.pubkey import Pubkey
        creator = str(Pubkey.from_bytes(data[49:81]))
        if creator == SYSTEM_PROGRAM:
            creator = None
    progress = None
    if not complete and rtok <= PUMP_INITIAL_REAL_TOKENS:
        progress = 100 * (1 - rtok / PUMP_INITIAL_REAL_TOKENS)
    return {"virtual_token_reserves": vtok, "virtual_sol_reserves": vsol, "real_token_reserves": rtok,
            "real_sol_reserves": rsol, "token_total_supply": supply, "complete": complete,
            "creator": creator, "progress_pct": 100.0 if complete else progress,
            "price_sol": (vsol / 1e9) / (vtok / 1e6) if vtok else None}


def _borsh_str(data: bytes, off: int) -> tuple[str, int]:
    n = struct.unpack_from("<I", data, off)[0]
    off += 4
    s = data[off:off + n].decode("utf-8", "replace").rstrip("\x00").strip()
    return s, off + n


def decode_metaplex_metadata(data: bytes) -> dict | None:
    try:
        from solders.pubkey import Pubkey
        update_auth = str(Pubkey.from_bytes(data[1:33]))
        off = 65
        name, off = _borsh_str(data, off)
        symbol, off = _borsh_str(data, off)
        uri, off = _borsh_str(data, off)
        # seller_fee(2) + creators option… ; is_mutable se trouve après les créateurs
        off += 2
        has_creators = data[off]
        off += 1
        if has_creators:
            n = struct.unpack_from("<I", data, off)[0]
            off += 4 + n * 34
        primary_sale = data[off]
        is_mutable = bool(data[off + 1])
        return {"update_authority": update_auth, "name": name, "symbol": symbol, "uri": uri,
                "primary_sale_happened": bool(primary_sale), "mutable": is_mutable}
    except Exception:
        return None


class SolanaRPC:
    def __init__(self, http: Http, rpc_url: str, helius_key: str | None = None) -> None:
        self.http = http
        self.helius_key = helius_key
        self.url = f"https://mainnet.helius-rpc.com/?api-key={helius_key}" if helius_key else rpc_url
        self.provider = "helius" if helius_key else "solana_rpc"
        self._id = 0

    async def call(self, method: str, params: list | None = None, timeout: float = 8.0):
        self._id += 1
        body = await self.http.post_json(self.provider, self.url,
                                         {"jsonrpc": "2.0", "id": self._id, "method": method,
                                          "params": params or []}, timeout=timeout)
        if "error" in body:
            raise ProviderError(self.provider, f"{method}: {body['error'].get('message', body['error'])}")
        return body.get("result")

    async def account_info(self, address: str, encoding: str = "jsonParsed") -> dict | None:
        res = await self.call("getAccountInfo", [address, {"encoding": encoding, "commitment": "confirmed"}])
        return (res or {}).get("value")

    async def account_bytes(self, address: str) -> tuple[bytes, str] | None:
        acc = await self.account_info(address, "base64")
        if not acc:
            return None
        return base64.b64decode(acc["data"][0]), acc["owner"]

    async def multiple_accounts(self, addresses: list[str]) -> list[dict | None]:
        out: list[dict | None] = []
        for i in range(0, len(addresses), 100):
            res = await self.call("getMultipleAccounts", [addresses[i:i + 100], {"encoding": "jsonParsed"}])
            out.extend(res["value"])
        return out

    async def token_supply(self, mint: str) -> dict:
        return (await self.call("getTokenSupply", [mint]))["value"]

    async def largest_accounts(self, mint: str) -> list[dict]:
        return (await self.call("getTokenLargestAccounts", [mint, {"commitment": "confirmed"}]))["value"]

    async def balance(self, address: str) -> int:
        return (await self.call("getBalance", [address]))["value"]

    async def token_balance_of(self, owner: str, mint: str) -> int:
        res = await self.call("getTokenAccountsByOwner", [owner, {"mint": mint}, {"encoding": "jsonParsed"}])
        return sum(int(a["account"]["data"]["parsed"]["info"]["tokenAmount"]["amount"]) for a in res["value"])

    async def signatures(self, address: str, limit: int = 1000, before: str | None = None) -> list[dict]:
        opts: dict = {"limit": limit}
        if before:
            opts["before"] = before
        return await self.call("getSignaturesForAddress", [address, opts], timeout=12)

    async def oldest_signatures(self, address: str, max_pages: int = 3) -> tuple[list[dict], bool]:
        """Remonte l'historique ; retourne (dernière page, True si le début de l'historique est atteint)."""
        before, page = None, []
        for _ in range(max_pages):
            page = await self.signatures(address, 1000, before)
            if len(page) < 1000:
                return page, True
            before = page[-1]["signature"]
        return page, False

    async def transaction(self, sig: str) -> dict | None:
        return await self.call("getTransaction", [sig, {"encoding": "jsonParsed",
                                                        "maxSupportedTransactionVersion": 0,
                                                        "commitment": "confirmed"}], timeout=10)

    # ---------- Helius (clé gratuite) : comptage des holders, transactions enrichies
    async def helius_holders(self, mint: str, max_pages: int = 10) -> tuple[list[dict], bool] | None:
        if not self.helius_key:
            return None
        accounts, complete = [], False
        for page in range(1, max_pages + 1):
            res = await self.call("getTokenAccounts", {"mint": mint, "page": page, "limit": 1000}, timeout=12)
            items = (res or {}).get("token_accounts", [])
            accounts.extend(items)
            if len(items) < 1000:
                complete = True
                break
        return accounts, complete

    async def helius_transactions(self, address: str, limit: int = 100, before: str | None = None) -> list[dict]:
        if not self.helius_key:
            raise ProviderError("helius", "clé Helius (gratuite) non configurée")
        params = {"api-key": self.helius_key, "limit": limit}
        if before:
            params["before"] = before
        return await self.http.get_json("helius", f"https://api.helius.xyz/v0/addresses/{address}/transactions",
                                        params=params, timeout=15)
