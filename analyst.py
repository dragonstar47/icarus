"""
analyst.py — Options analysis: Black-Scholes pricing, Greeks, chain filtering.
No scipy needed — uses stdlib math.erf for normal CDF.
"""

import math
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("icarus.analyst")


# ──────────────────────────────────────────────
# Black-Scholes (stdlib only — no scipy)
# ──────────────────────────────────────────────
def norm_cdf(x):
    """Standard normal CDF using math.erf."""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def black_scholes(S, K, T, r, sigma, option_type="call"):
    """
    Black-Scholes option pricing.
    S = spot price, K = strike, T = time to expiry (years),
    r = risk-free rate, sigma = volatility
    """
    if T <= 0 or sigma <= 0:
        return max(0, S - K) if option_type == "call" else max(0, K - S)

    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    if option_type == "call":
        price = S * norm_cdf(d1) - K * math.exp(-r * T) * norm_cdf(d2)
    else:
        price = K * math.exp(-r * T) * norm_cdf(-d2) - S * norm_cdf(-d1)

    return max(0, price)


def calculate_greeks(S, K, T, r, sigma, option_type="call"):
    """Calculate option Greeks: delta, gamma, theta, vega."""
    if T <= 0 or sigma <= 0:
        return {"delta": 0, "gamma": 0, "theta": 0, "vega": 0}

    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    # Normal PDF
    pdf_d1 = math.exp(-0.5 * d1**2) / math.sqrt(2 * math.pi)

    # Delta
    if option_type == "call":
        delta = norm_cdf(d1)
    else:
        delta = norm_cdf(d1) - 1

    # Gamma
    gamma = pdf_d1 / (S * sigma * math.sqrt(T))

    # Theta (per day)
    if option_type == "call":
        theta = (-(S * pdf_d1 * sigma) / (2 * math.sqrt(T))
                 - r * K * math.exp(-r * T) * norm_cdf(d2)) / 365
    else:
        theta = (-(S * pdf_d1 * sigma) / (2 * math.sqrt(T))
                 + r * K * math.exp(-r * T) * norm_cdf(-d2)) / 365

    # Vega (per 1% move in vol)
    vega = S * pdf_d1 * math.sqrt(T) / 100

    return {
        "delta": round(delta, 4),
        "gamma": round(gamma, 6),
        "theta": round(theta, 4),
        "vega": round(vega, 4),
    }


# ──────────────────────────────────────────────
# Chain Filtering
# ──────────────────────────────────────────────
def days_to_expiry(expiry_str):
    """Calculate days to expiry from date string."""
    try:
        if isinstance(expiry_str, str):
            exp = datetime.strptime(expiry_str[:10], "%Y-%m-%d")
        else:
            exp = expiry_str
        return max(0, (exp - datetime.now()).days)
    except Exception:
        return 0
def parse_occ_symbol(occ_symbol):
    """Parse OCC option symbol like NVDA260902C00285000."""
    try:
        # Work backwards: last 8 digits = strike, before that C/P, before that 6 digit date
        strike_str = occ_symbol[-8:]
        opt_char = occ_symbol[-9]
        date_str = occ_symbol[-15:-9]
        root = occ_symbol[:-15]

        strike = int(strike_str) / 1000
        opt_type = "call" if opt_char == "C" else "put"
        expiry = f"20{date_str[:2]}-{date_str[2:4]}-{date_str[4:6]}"
        return root, expiry, opt_type, strike
    except Exception:
        return None, None, None, None

def filter_options_chain(chain_data, spot_price, direction="call"):
    """
    Filter options chain for quality candidates.
    Handles both contract list and snapshot formats.
    """
    candidates = []

    if not chain_data:
        return candidates

    source = chain_data.get("source", "unknown")
    data = chain_data.get("data", chain_data)

    contracts_list = []

    if source == "contracts":
        # get_option_contracts format: {"option_contracts": [...]}
        raw = data if isinstance(data, list) else data.get("option_contracts", [])
        if isinstance(raw, list):
            contracts_list = raw
    elif source == "chain":
        # get_option_chain snapshot format
        snapshots = data.get("snapshots", {}) if isinstance(data, dict) else {}
        for symbol, snap in snapshots.items():
            root, expiry, opt_type, strike = parse_occ_symbol(symbol)
            if root:
                contracts_list.append({
                    "symbol": symbol,
                    "strike_price": str(strike),
                    "expiration_date": expiry,
                    "type": opt_type,
                    "snapshot": snap,
                })
    else:
        # Try to auto-detect
        if isinstance(data, dict) and "snapshots" in data:
            snapshots = data["snapshots"]
            for symbol, snap in snapshots.items():
                root, expiry, opt_type, strike = parse_occ_symbol(symbol)
                if root:
                    contracts_list.append({
                        "symbol": symbol,
                        "strike_price": str(strike),
                        "expiration_date": expiry,
                        "type": opt_type,
                        "snapshot": snap,
                    })
        elif isinstance(data, list):
            contracts_list = data
        elif isinstance(data, dict) and "option_contracts" in data:
            contracts_list = data["option_contracts"]

    logger.info(f"Processing {len(contracts_list)} contracts for filtering")

    for contract in contracts_list:
        try:
            if isinstance(contract, str):
                continue

            symbol = contract.get("symbol", contract.get("id", ""))
            strike = float(contract.get("strike_price", contract.get("strike", 0)))
            expiry = contract.get("expiration_date", contract.get("expiry", ""))
            contract_type = contract.get("type", contract.get("option_type", "")).lower()

            # Filter by direction
            if direction == "call" and contract_type != "call":
                continue
            if direction == "put" and contract_type != "put":
                continue

            dte = days_to_expiry(expiry)

            # Quality gates
            if dte < 5 or dte > 45:
                continue
            if strike <= 0 or spot_price <= 0:
                continue

            # Max 10% OTM
            if direction == "call" and strike > spot_price * 1.10:
                continue
            if direction == "put" and strike < spot_price * 0.90:
                continue

            # Calculate pricing
            T = dte / 365
            sigma = 0.30
            r = 0.05

            # Check for snapshot data with greeks
            snap = contract.get("snapshot", {})
            greeks_data = snap.get("greeks", {}) if snap else {}

            if greeks_data and greeks_data.get("delta"):
                greeks = {
                    "delta": round(float(greeks_data.get("delta", 0)), 4),
                    "gamma": round(float(greeks_data.get("gamma", 0)), 6),
                    "theta": round(float(greeks_data.get("theta", 0)), 4),
                    "vega": round(float(greeks_data.get("vega", 0)), 4),
                }
                iv = float(greeks_data.get("implied_volatility", sigma))
            else:
                greeks = calculate_greeks(spot_price, strike, T, r, sigma, direction)
                iv = sigma

            theo_price = black_scholes(spot_price, strike, T, r, iv, direction)

            # Get market price if available
            market_price = 0
            if snap:
                quote = snap.get("latestQuote", {})
                ask = float(quote.get("ap", 0))
                bid = float(quote.get("bp", 0))
                if ask > 0 and bid > 0:
                    market_price = (ask + bid) / 2

            # Reject garbage
            if theo_price < 0.10:
                continue
            if abs(greeks["delta"]) < 0.15:
                continue

            # Theta check
            if theo_price > 0:
                theta_pct = abs(greeks["theta"]) / theo_price
                if theta_pct > 0.05:
                    continue

            candidates.append({
                "symbol": symbol,
                "strike": strike,
                "expiry": expiry,
                "dte": dte,
                "type": direction,
                "theo_price": round(theo_price, 2),
                "market_price": round(market_price, 2),
                "delta": greeks["delta"],
                "gamma": greeks["gamma"],
                "theta": greeks["theta"],
                "vega": greeks["vega"],
                "iv": round(iv, 4),
                "otm_pct": round(abs(strike - spot_price) / spot_price * 100, 2),
            })

        except Exception as e:
            logger.debug(f"Skipping contract: {e}")
            continue

    candidates.sort(key=lambda x: x["otm_pct"])

    return candidates[:5]


# ──────────────────────────────────────────────
# Simple Technical Analysis
# ──────────────────────────────────────────────
def calculate_rsi(closes, period=14):
    """Calculate RSI from closing prices."""
    if len(closes) < period + 1:
        return 50

    changes = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [max(0, c) for c in changes[-period:]]
    losses = [abs(min(0, c)) for c in changes[-period:]]

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def calculate_ema(closes, period=20):
    """Calculate EMA."""
    if not closes:
        return 0
    multiplier = 2 / (period + 1)
    ema = closes[0]
    for price in closes[1:]:
        ema = (price - ema) * multiplier + ema
    return round(ema, 2)


def analyze_technicals(bars_data):
    """Quick technical analysis from bar data."""
    try:
        if not bars_data:
            return {"rsi": 50, "ema20": 0, "trend": "neutral", "spot_price": 0}

        closes = []

        # Handle MCP format: {"bars": {"AAPL": [{"c": 316.85, ...}, ...]}}
        if isinstance(bars_data, dict) and "bars" in bars_data:
            symbol_bars = bars_data["bars"]
            if isinstance(symbol_bars, dict):
                # Get the first (and usually only) symbol's bars
                first_key = list(symbol_bars.keys())[0]
                bar_list = symbol_bars[first_key]
                for bar in bar_list:
                    closes.append(float(bar.get("c", bar.get("close", 0))))
            elif isinstance(symbol_bars, list):
                for bar in symbol_bars:
                    closes.append(float(bar.get("c", bar.get("close", 0))))
        elif isinstance(bars_data, list):
            for bar in bars_data:
                if isinstance(bar, dict):
                    closes.append(float(bar.get("c", bar.get("close", 0))))
                else:
                    closes.append(float(getattr(bar, "close", 0)))
        elif isinstance(bars_data, dict) and "data" in bars_data:
            return analyze_technicals(bars_data["data"])

        if not closes:
            return {"rsi": 50, "ema20": 0, "trend": "neutral", "spot_price": 0}

        spot = closes[-1]
        rsi = calculate_rsi(closes)
        ema20 = calculate_ema(closes, 20)

        if spot > ema20 * 1.015:
            trend = "bullish"
        elif spot < ema20 * 0.985:
            trend = "bearish"
        else:
            trend = "neutral"

        return {
            "rsi": rsi,
            "ema20": ema20,
            "spot_price": round(spot, 2),
            "trend": trend,
            "above_ema": spot > ema20,
        }
    except Exception as e:
        logger.error(f"Technical analysis error: {e}")
        return {"rsi": 50, "ema20": 0, "trend": "neutral", "spot_price": 0}