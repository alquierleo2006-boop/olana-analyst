"""Faux réseau : simule tous les fournisseurs pour tester sans accès Internet."""
from __future__ import annotations

import base64
import json
import struct
import time

import httpx
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from analyst.providers.solana import (LAUNCHLAB_PROGRAM, METAPLEX_PROGRAM, PUMPFUN_PROGRAM, WSOL_MINT, find_pda,
                                      pubkey_bytes)

NOW = time.time()
MINT = str(Keypair().pubkey())[:-4] if False else "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr"
CREATOR = str(Keypair().pubkey())
WHALE = str(Keypair().pubkey())
FUNDER = str(Keypair().pubkey())
H1, H2 = str(Keypair().pubkey()), str(Keypair().pubkey())
PAIR = "PairAddr1111111111111111111111111111111111"
CURVE = find_pda([b"bonding-curve", pubkey_bytes(MINT)], PUMPFUN_PROGRAM)
MD_PDA = find_pda([b"metadata", pubkey_bytes(METAPLEX_PROGRAM), pubkey_bytes(MINT)], METAPLEX_PROGRAM)
POOL_OWNER = CURVE  # la curve (PDA) détient des tokens


def curve_bytes(complete=True, vsol=30 * 10**9, rsol=85 * 10**9, rtok=0):
    b = bytearray(8) + struct.pack("<QQQQQ", 1_073_000_000 * 10**6, vsol, rtok, rsol, 10**15)
    b += bytes([1 if complete else 0]) + pubkey_bytes(CREATOR)
    return bytes(b)


def borsh(s):
    e = s.encode()
    return struct.pack("<I", len(e)) + e


def metadata_bytes():
    b = bytes([4]) + pubkey_bytes("TSLvdd1pWpHVjahSpsvCXUbgwsL3JAcvokwaKt1eokM") + pubkey_bytes(MINT)
    b += borsh("Robo Cat") + borsh("RCAT") + borsh("https://ipfs.io/ipfs/QmMeta")
    b += struct.pack("<H", 0) + bytes([0]) + bytes([1, 1])  # no creators, primary sale, mutable
    return b


def token_acc(owner, amount):
    return {"data": {"parsed": {"info": {"owner": owner, "mint": MINT,
                                         "tokenAmount": {"amount": str(amount), "decimals": 6}}}}}


class RateLimited(Exception):
    pass


class Fake:
    def __init__(self, **opts):
        self.opts = opts
        self.curve_i = 0
        self.curve_fails = 0
        self.dev_balance = 5 * 10**12
        self.insider_amounts: dict = {}
        self.calls: list[str] = []

    def rpc(self, method, params):
        o = self.opts
        if method == "getAccountInfo":
            addr, enc = params[0], params[1].get("encoding")
            if addr == MINT and enc == "jsonParsed":
                if o.get("no_mint"):
                    return {"value": None}
                return {"value": {"owner": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", "data": {"parsed": {
                    "type": "mint", "info": {"decimals": 6, "supply": str(10**15),
                                             "mintAuthority": o.get("mint_auth"), "freezeAuthority": None}}}}}
            if addr == CURVE:
                if o.get("curve_fail", 0) > self.curve_fails:
                    self.curve_fails += 1
                    raise RateLimited()
                if o.get("curve_active"):
                    data = curve_bytes(False, vsol=31 * 10**9, rsol=1 * 10**9, rtok=760_000_000 * 10**6)
                    return {"value": {"owner": PUMPFUN_PROGRAM, "data": [base64.b64encode(data).decode(), "base64"]}}
                if o.get("curve_seq"):  # curve active dont les réserves évoluent à chaque lecture
                    i = min(self.curve_i, len(o["curve_seq"]) - 1)
                    self.curve_i += 1
                    vsol = o["curve_seq"][i]
                    data = curve_bytes(False, vsol=int(vsol * 10**9), rsol=int((vsol - 30) * 10**9), rtok=600_000_000 * 10**6)
                else:
                    data = curve_bytes()
                return {"value": {"owner": PUMPFUN_PROGRAM, "data": [base64.b64encode(data).decode(), "base64"]}}
            if addr == MD_PDA:
                return {"value": {"owner": METAPLEX_PROGRAM, "data": [base64.b64encode(metadata_bytes()).decode(), "base64"]}}
            return {"value": None}
        if method == "getSignaturesForAddress":
            addr = params[0]
            if addr == MINT:
                return [{"signature": f"s{i}", "blockTime": NOW - 7200 + i} for i in range(40)][::-1]
            if addr in (H1, H2):
                return [{"signature": f"f_{addr}", "blockTime": NOW - 7000}]
            return [{"signature": f"x{i}", "blockTime": NOW - 86400 * 30} for i in range(300)]
        if method == "getTransaction":
            sig = params[0]
            if sig == "s0":
                return {"blockTime": NOW - 7200, "transaction": {"message": {
                    "accountKeys": [{"pubkey": CREATOR}], "instructions": [{"programId": PUMPFUN_PROGRAM}]}}, "meta": {}}
            if sig.startswith("f_"):
                w = sig[2:]
                return {"blockTime": NOW - 7000, "transaction": {"message": {"accountKeys": [{"pubkey": FUNDER}],
                        "instructions": [{"programId": "11111111111111111111111111111111", "parsed": {
                            "type": "transfer", "info": {"source": FUNDER, "destination": w, "lamports": 10**9}}}]}}}
            return None
        if method == "getTokenLargestAccounts":
            return {"value": [{"address": "TA_curve", "amount": str(200 * 10**12)},
                              {"address": "TA_whale", "amount": str(o.get("whale", 40) * 10**12)},
                              {"address": "TA_h1", "amount": str(30 * 10**12)},
                              {"address": "TA_h2", "amount": str(25 * 10**12)},
                              {"address": "TA_dev", "amount": str(5 * 10**12)}]}
        if method == "getMultipleAccounts":
            amts = self.insider_amounts
            def ta(owner, key):
                if key in amts and amts[key] is None:
                    return None  # compte fermé (tout vendu)
                acc = token_acc(owner, amts.get(key, 0))
                acc["data"]["parsed"]["info"]["tokenAmount"]["uiAmountString"] = str(amts.get(key, 0) / 10**6)
                return acc
            m = {"TA_curve": ta(CURVE, "TA_curve"), "TA_whale": ta(WHALE, "TA_whale"), "TA_h1": ta(H1, "TA_h1"),
                 "TA_h2": ta(H2, "TA_h2"), "TA_dev": ta(CREATOR, "TA_dev")}
            return {"value": [m.get(a) for a in params[0]]}
        if method == "getTokenAccountsByOwner":
            owner = params[0]
            amt = {CREATOR: self.dev_balance, WHALE: 40 * 10**12}.get(owner, 0)
            return {"value": [{"account": token_acc(owner, amt)}] if amt else []}
        if method == "getBalance":
            return {"value": 3 * 10**9}
        if method == "getTokenSupply":
            return {"value": {"amount": str(10**15), "decimals": 6}}
        raise AssertionError(f"RPC non simulé : {method}")

    def handle(self, req: httpx.Request) -> httpx.Response:
        u = str(req.url)
        self.calls.append(u)
        o = self.opts
        if o.get("down") and any(d in u for d in o["down"]):
            return httpx.Response(503, text="down")
        if "mainnet-beta.solana.com" in u or "helius-rpc" in u:
            body = json.loads(req.content)
            try:
                result = self.rpc(body["method"], body["params"])
            except RateLimited:
                return httpx.Response(429, text="Too many requests")
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})
        if "dexscreener.com/tokens/v1/solana/" in u:
            if MINT not in u:
                return httpx.Response(200, json=[])
            if o.get("tiny"):
                return httpx.Response(200, json=[{
                    "chainId": "solana", "dexId": "pumpfun", "pairAddress": CURVE, "url": "https://dexscreener.com/x",
                    "baseToken": {"address": MINT, "name": "Robo Cat", "symbol": "RCAT"}, "quoteToken": {"symbol": "SOL"},
                    "priceUsd": "0.000004", "marketCap": 4000, "fdv": 4000, "liquidity": {"usd": 1500},
                    "volume": {"m5": 900, "h1": 3000, "h6": 3000, "h24": 3000},
                    "txns": {"m5": {"buys": 30, "sells": 12}, "h1": {"buys": 80, "sells": 40}, "h6": {"buys": 80, "sells": 40},
                             "h24": {"buys": 80, "sells": 40}},
                    "priceChange": {"m5": 10, "h1": 40, "h6": 40, "h24": 40}, "pairCreatedAt": (NOW - 600) * 1000}])
            return httpx.Response(200, json=[{
                "chainId": "solana", "dexId": "pumpswap", "pairAddress": PAIR, "url": "https://dexscreener.com/solana/x",
                "baseToken": {"address": MINT, "name": "Robo Cat", "symbol": "RCAT"}, "quoteToken": {"symbol": "SOL"},
                "priceUsd": "0.00042", "marketCap": 420000, "fdv": 420000, "liquidity": {"usd": 61000},
                "volume": {"m5": 9000, "h1": 120000, "h6": 400000, "h24": 900000},
                "txns": {"m5": {"buys": 40, "sells": 20}, "h1": {"buys": 520, "sells": 300},
                         "h6": {"buys": 2000, "sells": 1500}, "h24": {"buys": 5000, "sells": 4000}},
                "priceChange": {"m5": 4.2, "h1": 35, "h6": 120, "h24": 300}, "pairCreatedAt": (NOW - 6000) * 1000,
                "info": {"imageUrl": "https://img/x.png", "websites": [{"url": "https://robocat.example"}],
                         "socials": [{"type": "twitter", "url": "https://x.com/robocatsol"},
                                     {"type": "telegram", "url": "https://t.me/robocatsol"}]}}])
        if "dexscreener.com/latest/dex/search" in u:
            extra = [{"chainId": "solana", "baseToken": {"address": "Orig111", "symbol": "RCAT", "name": "Robo Cat"},
                      "pairCreatedAt": (NOW - 40 * 86400) * 1000, "marketCap": 42_000_000, "volume": {"h24": 900000}}] \
                if o.get("copycat") else []
            if o.get("declared"):
                decl = lambda addr, sym, age: {"chainId": "solana", "baseToken": {"address": addr, "symbol": sym, "name": "Robo Cat"},
                                               "pairCreatedAt": (NOW - age) * 1000, "marketCap": 420000, "liquidity": {"usd": 61000},
                                               "info": {"socials": [{"type": "twitter", "url": "https://x.com/RoboCatSol"}],
                                                        "websites": [{"url": "https://robocat.example"}]}}
                extra.append(decl(MINT, "RCAT", 6000))
                if o.get("impostor"):
                    extra.append(decl("Fake1111111111111111111111111111111111111111", "RCAT", 600))
            return httpx.Response(200, json={"pairs": extra + [
                {"chainId": "solana", "baseToken": {"address": "Other111", "symbol": "RCAT", "name": "Robo Cat"},
                 "pairCreatedAt": (NOW - 3600) * 1000, "marketCap": 1000, "volume": {"h24": 10}},
                {"chainId": "solana", "baseToken": {"address": "Ai1", "symbol": "AGENT", "name": "AI Agent"},
                 "pairCreatedAt": (NOW - 3600) * 1000, "marketCap": 50000, "volume": {"h24": 9000}}]})
        if "geckoterminal.com" in u and "/pools" in u and "ohlcv" not in u:
            return httpx.Response(200, json={"data": [{"attributes": {
                "address": PAIR, "reserve_in_usd": "61000", "volume_usd": {"m15": "30000"},
                "transactions": {"h1": {"buys": 520, "sells": 300, "buyers": 260, "sellers": 150}}},
                "relationships": {"dex": {"data": {"id": "pumpswap"}}}}]})
        if "ohlcv" in u:
            t = int(NOW) - 300 * 60
            candles = [[t + i * 60, 0.0003 + i * 4e-7, 0.0003 + i * 4e-7 + 1e-6, 0.0003 + i * 4e-7 - 1e-6,
                        0.0003 + i * 4e-7, 300 + (2000 if i > 295 else 0)] for i in range(300)]
            return httpx.Response(200, json={"data": {"attributes": {"ohlcv_list": candles[::-1]}}})
        if "lite-api.jup.ag/price" in u:
            return httpx.Response(200, json={WSOL_MINT: {"usdPrice": 180.0}})
        if "lite-api.jup.ag/swap/v1/quote" in u:
            if o.get("no_sell") and f"inputMint={MINT}" in u:
                return httpx.Response(400, json={"error": "no route"})
            amt = int(req.url.params["amount"])
            scale = 1e11 if o.get("thin") else 1e15
            return httpx.Response(200, json={"priceImpactPct": str(min(0.5, amt / scale)),
                                             "routePlan": [{"swapInfo": {"label": "PumpSwap"}}]})
        if "rugcheck.xyz" in u:
            return httpx.Response(200, json={"score_normalised": 12, "rugged": False, "totalHolders": 1834,
                                             "creator": CREATOR, "risks": [{"name": "Low amount of LP Providers",
                                                                            "level": "warn", "description": "x"},
                                                                           {"name": "Low Liquidity", "level": "danger",
                                                                            "description": "Low amount of liquidity in the token pool"}],
                                             "markets": [{"marketType": "pump_amm", "lp": {"lpLockedPct": 100}}]})
        if "frontend-api-v3.pump.fun/coins/user-created-coins" in u:
            return httpx.Response(200, json=[{"mint": "Old1", "symbol": "OLD", "complete": True,
                                              "created_timestamp": (NOW - 20 * 86400) * 1000,
                                              "last_trade_timestamp": (NOW - 10 * 86400) * 1000}])
        if "frontend-api-v3.pump.fun/coins/" in u:
            return httpx.Response(200, json={"mint": MINT, "description": "Robo Cat is the first AI agent cat on "
                                             "Solana. Official partnership with OpenAI announced.",
                                             "twitter": "https://x.com/robocatsol"})
        if "ipfs.io" in u:
            return httpx.Response(200, json={"name": "Robo Cat", "description": "AI agent cat",
                                             "website": "https://robocat.example"})
        if "other.example" in u and "rdap.org" not in u:
            return httpx.Response(200, text=f"<html><title>Robo Cat official</title><body>CA {MINT} "
                                             '<a href="https://docs.other.example">Docs</a>' + " word" * 200 + "</body></html>")
        if "robocat.example" in u and "rdap.org" not in u:
            site_ca = o.get("site_ca") or MINT
            return httpx.Response(200, text=f"<html><title>Robo Cat $RCAT</title><body>CA: {site_ca} "
                                             '<a href="https://x.com/robocatsol">X</a> <a href="https://t.me/robocatsol">TG</a>'
                                             '<a href="https://github.com/robocat/agent">Code</a> <a href="https://docs.robocat.example">Docs</a>'
                                             " Our team. Roadmap. " + "word " * 200 + "</body></html>")
        if "api.github.com/search/repositories" in u:
            return httpx.Response(200, json={"items": [
                {"full_name": "elizaOS/eliza", "html_url": "https://github.com/elizaOS/eliza", "stargazers_count": 15000,
                 "description": "Autonomous AI agents for everyone", "created_at": "2024-07-01T00:00:00Z", "fork": False},
                {"full_name": "robocat/agent", "html_url": "https://github.com/robocat/agent", "stargazers_count": 120,
                 "description": "Robo Cat agent", "created_at": "2025-06-01T00:00:00Z", "fork": False}]})
        if "api.github.com/repos/robocat/agent" in u:
            d = {"full_name": "robocat/agent", "html_url": "https://github.com/robocat/agent", "created_at": "2025-06-01T00:00:00Z",
                 "pushed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW - 3 * 86400)), "stargazers_count": 120,
                 "fork": bool(o.get("gh_fork")), "size": 4200, "language": "TypeScript", "archived": False}
            if o.get("gh_fork"):
                d["parent"] = {"full_name": "famous/ai-agent"}
            return httpx.Response(200, json=d)
        if "rdap.org" in u:
            date = "2024-03-01T10:00:00Z" if o.get("old_domain") else \
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW - 86400)) if o.get("new_domain") else "2026-10-30T10:00:00Z"
            return httpx.Response(200, json={"events": [{"eventAction": "registration", "eventDate": date}]})
        if "cdn.syndication.twimg.com/tweet-result" in u:
            return httpx.Response(200, json={
                "text": f"$RCAT is live! CA: {MINT} https://t.co/abc", "created_at": "2026-11-01T12:00:00.000Z",
                "entities": {"urls": [{"expanded_url": "https://robocat.example"}]},
                "user": {"screen_name": "robocatsol", "name": "Robo Cat", "is_blue_verified": False}})
        if "syndication.twitter.com/srv/timeline-profile" in u:
            return httpx.Response(404, text="")
        if "publish.twitter.com" in u:
            return httpx.Response(200, json={"author_name": "Robo Cat", "html": "<blockquote>timeline</blockquote>"})
        if "t.me/" in u:
            return httpx.Response(200, text='<div class="tgme_page_title"><span>Robo Cat $RCAT</span></div>'
                                            '<div class="tgme_page_extra">2 450 members, 180 online</div>')
        if "news.google.com" in u or "reddit.com" in u or "cointelegraph" in u or "decrypt.co" in u \
                or "coindesk" in u or "theblock" in u:
            items = "".join(f"<item><title>AI agent craze sweeps markets {i} - Src{i}</title><link>https://n{i}.com/{abs(hash(u)) % 9999}/{i}</link>"
                            f"<pubDate>{time.strftime('%a, %d %b %Y %H:%M:%S +0000', time.gmtime(NOW - i * 600))}</pubDate>"
                            f"<source url='https://src{i}.com'>Src{i}</source></item>" for i in range(5))
            return httpx.Response(200, text=f"<rss><channel>{items}</channel></rss>")
        if "gdeltproject" in u:
            return httpx.Response(200, json={"articles": [
                {"url": f"https://g{i}.com/a{i}", "title": f"AI agent stocks surge as robots go viral {i}",
                 "seendate": time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(NOW - i * 900)), "domain": f"g{i}.com",
                 "language": "English", "sourcecountry": "US"} for i in range(8)]})
        return httpx.Response(404, text="not simulated")

    def transport(self):
        return httpx.MockTransport(self.handle)
