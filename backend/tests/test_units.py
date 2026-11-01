import time

from analyst.engines.smartmoney import compute_wallet_stats
from analyst.engines.social import classify_link, extract_claims_rules
from analyst.engines.tracker import fit_probability_model
from analyst.providers.solana import decode_pump_curve, is_on_curve
from analyst.util import is_valid_mint_format

from .fakes import CREATOR, CURVE, curve_bytes

W = "WalletAAAA"
M = "MintBBBB"


def swap(ts, sol, tok, fee=5000):
    return {"timestamp": ts, "fee": fee, "feePayer": W, "accountData": [
        {"account": W, "nativeBalanceChange": int(sol * 1e9),
         "tokenBalanceChanges": [{"userAccount": W, "mint": M, "rawTokenAmount": {"tokenAmount": str(int(tok * 1e6)), "decimals": 6}}]}]}


def test_wallet_pnl():
    now = time.time()
    txs = [swap(now - 100, -1.0, 1000), swap(now - 50, 2.5, -1000)]
    st = compute_wallet_stats(W, txs)
    assert st["closed_positions"] == 1 and st["win_rate"] == 1.0
    assert abs(st["realized_pnl_sol"] - 1.5) < 1e-6
    assert st["reliable"] is False  # < 20 positions : jamais « fiable »


def test_pump_curve_decode():
    c = decode_pump_curve(curve_bytes(complete=False))
    assert c["creator"] == CREATOR and c["complete"] is False
    assert c["price_sol"] > 0


def test_pda_detection():
    assert is_on_curve(CREATOR) is True
    assert is_on_curve(CURVE) is False


def test_address_validation():
    assert is_valid_mint_format("So11111111111111111111111111111111111111112")
    assert not is_valid_mint_format("0xdeadbeef")
    assert not is_valid_mint_format("")


def test_link_classification():
    assert classify_link("https://x.com/elonmusk/status/123")[1]["kind"] == "tweet"
    assert classify_link("https://twitter.com/foo")[1] == {"kind": "profile", "handle": "foo", "url": "https://twitter.com/foo"}
    assert classify_link("t.me/+abc")[1]["kind"] == "private_invite"
    assert classify_link("https://discord.gg/xyz")[0] == "discord"


def test_claims_rules():
    cl = extract_claims_rules("We are proud. Official partnership with Binance announced today. Buy now!")
    assert cl and "Binance" in cl[0]


def test_probability_model_requires_data():
    few = [{"score": 8, "change_pct": 50}] * 50
    assert fit_probability_model(few, 20, 100)["usable"] is False


def test_probability_model_calibrated():
    import random
    random.seed(1)
    S = []
    for _ in range(1500):
        s = random.uniform(0, 10)
        p = 0.05 + 0.08 * s
        S.append({"score": s, "change_pct": 60 if random.random() < p else -10})
    m = fit_probability_model(S, 20, 100)
    assert m["usable"] is True and m["brier"] < m["brier_base_rate"]
    assert m["buckets"][-1]["probability"] > m["buckets"][0]["probability"]


def test_curve_liquidity_not_critical_on_fresh_pumpfun_token():
    from analyst.engines.market import curve_impact, curve_liquidity_risk
    # Curve neuve (~8 k$ de market cap) : 30 SOL virtuels, 1,073 Md de tokens virtuels, presque rien de réel.
    curve = {"virtual_sol_reserves": 31 * 10**9, "virtual_token_reserves": 1_040_000_000 * 10**6,
             "real_token_reserves": 760_000_000 * 10**6}
    tests = [curve_impact(curve, s) for s in (0.5, 2.0, 10.0)]
    assert 1.0 < tests[0]["buy_impact_pct"] < 2.5  # 0,5 SOL ≈ 1,6 %
    assert tests[2]["buy_impact_pct"] > 25
    risk = curve_liquidity_risk(tests, 0.5)
    assert risk["level"] == "faible"
    assert curve_liquidity_risk(tests, 2.0)["level"] == "modéré"
