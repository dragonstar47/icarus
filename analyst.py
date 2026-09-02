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


def filter_options_chain(chain_data, spot_price, direction="call"):
    """
    Filter options chain for quality candidates.
    Returns sorted list of best candidates.
    """
    candidates = []

    if not chain_data:
        return candidates

    # Handle different data formats
    contracts = chain_data if isinstance(chain_data, list) else chain_data.get("option_contracts", chain_data.get("contracts", []))

    if not isinstance(contracts, list):
        logger.warning(f"Unexpected chain format: {type(contracts)}")
        return candidates

    for contract in contracts:
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

            # Calculate theoretical price and Greeks
            T = dte / 365
            sigma = 0.30
            r = 0.05

            theo_price = black_scholes(spot_price, strike, T, r, sigma, direction)
            greeks = calculate_greeks(spot_price, strike, T, r, sigma, direction)

            # Reject garbage
            if theo_price < 0.10:
                continue
            if abs(greeks["delta"]) < 0.15:
                continue
            if dte <= 3 and strike != spot_price:
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
                "delta": greeks["delta"],
                "gamma": greeks["gamma"],
                "theta": greeks["theta"],
                "vega": greeks["vega"],
                "otm_pct": round(abs(strike - spot_price) / spot_price * 100, 2),
            })

        except Exception as e:
            logger.debug(f"Skipping contract: {e}")
            continue

    # Sort by delta (prefer higher probability)
    candidates.sort(key=lambda x: abs(x["delta"]), reverse=True)

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
        if isinstance(bars_data, list):
            for bar in bars_data:
                if isinstance(bar, dict):
                    closes.append(float(bar.get("close", bar.get("c", 0))))
                else:
                    closes.append(float(getattr(bar, "close", 0)))
        elif isinstance(bars_data, dict):
            bars_list = bars_data.get("bars", bars_data.get("data", []))
            for bar in bars_list:
                closes.append(float(bar.get("close", bar.get("c", 0))))

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