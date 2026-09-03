"""
icarus.py — Main entry point for the Icarus Options Alpha Agent.
Runs the agent loop + Flask dashboard in one process.

Alpaca AI Trading Agents Hackathon 2026
"""

import asyncio
import os
import sys
import json
import logging
import threading
from datetime import datetime
from flask import Flask, render_template, jsonify

from mcp_client import get_client
from analyst import filter_options_chain, analyze_technicals
from brain import IcarusBrain
from db import init_db, log_trade, log_decision, log_scan, get_trades, get_decisions, get_stats

# ──────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("icarus")

# ──────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────
WATCHLIST = ["AAPL", "NVDA", "TSLA", "META", "AMD", "MSFT", "AMZN"]
SCAN_INTERVAL = 300  # seconds between scans (5 min)
PORT = int(os.environ.get("PORT", 8080))

# ──────────────────────────────────────────────
# Globals (shared between agent loop and dashboard)
# ──────────────────────────────────────────────
agent_state = {
    "status": "starting",
    "last_scan": None,
    "account": None,
    "positions": [],
    "current_scan": None,
    "cycle_count": 0,
}
brain = IcarusBrain()

# ──────────────────────────────────────────────
# Flask Dashboard
# ──────────────────────────────────────────────
app = Flask(__name__)


@app.route("/")
def dashboard():
    return render_template(
        "dashboard.html",
        status=agent_state["status"],
        account=agent_state["account"],
        positions=agent_state["positions"],
        decisions=get_decisions(20),
        trades=get_trades(20),
        stats=get_stats(),
    )


@app.route("/api/status")
def api_status():
    return jsonify({
        "status": agent_state["status"],
        "last_scan": agent_state["last_scan"],
        "cycle_count": agent_state["cycle_count"],
        "account": agent_state["account"],
    })


@app.route("/api/decisions")
def api_decisions():
    return jsonify(get_decisions(50))


@app.route("/api/trades")
def api_trades():
    return jsonify(get_trades(50))


@app.route("/api/stats")
def api_stats():
    return jsonify(get_stats())


def run_dashboard():
    """Run Flask in a separate thread."""
    app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)


# ──────────────────────────────────────────────
# Agent Loop
# ──────────────────────────────────────────────
async def scan_symbol(client, symbol):
    """Scan a single symbol for options opportunities."""
    logger.info(f"Scanning {symbol}...")

    # Get price bars for technicals
    bars = await client.get_bars(symbol, timeframe="1Day", limit=30)
    logger.info(f"{symbol} bars type: {type(bars)}, preview: {str(bars)[:300]}")
    technicals = analyze_technicals(bars)

    if not technicals.get("spot_price"):
        logger.warning(f"{symbol}: No price data, skipping")
        return None

    spot = technicals["spot_price"]
    logger.info(f"{symbol}: spot=${spot}, RSI={technicals['rsi']}, trend={technicals['trend']}")

    # Determine direction based on trend
    if technicals["trend"] == "bearish":
        direction = "put"
    elif technicals["trend"] == "bullish":
        direction = "call"
    else:
        direction = "call"  # Default to calls in neutral

    # Get options chain via MCP
    chain = await client.get_options_chain(symbol)
    logger.info(f"{symbol} chain type: {type(chain)}, keys: {list(chain.keys()) if isinstance(chain, dict) else 'not dict'}, preview: {str(chain)[:400]}")
    if not chain:
        logger.warning(f"{symbol}: No options chain data")
        return None

    # Filter for quality candidates
    candidates = filter_options_chain(chain, spot, direction)
    if not candidates:
        logger.info(f"{symbol}: No candidates passed filters")
        return None

    logger.info(f"{symbol}: {len(candidates)} candidates found, best: {candidates[0]['symbol']}")

    # Get news for context
    news = await client.get_news(symbol)

    # Get current positions
    positions = await client.get_positions()

    # Send best candidate to AI Brain
    best = candidates[0]
    decision = await brain.evaluate(best, technicals, news, positions)

    # Log the decision
    log_decision(
        symbol=best["symbol"],
        action=decision["action"],
        reasoning=decision["reasoning"],
        confidence=decision.get("confidence", 0),
        candidate_data=best,
    )

    if decision["action"] == "APPROVE":
        return {
            "candidate": best,
            "decision": decision,
            "technicals": technicals,
        }

    return None


async def execute_trade(client, trade_data):
    """Execute an approved trade via MCP."""
    candidate = trade_data["candidate"]
    decision = trade_data["decision"]

    try:
        logger.info(f"Executing: BUY {candidate['symbol']} (AI confidence: {decision.get('confidence', '?')})")

        result = await client.place_order(
            symbol=candidate["symbol"],
            qty=1,
            side="buy",
            order_type="market",
            time_in_force="day",
        )

        # Log the trade
        log_trade(
            symbol=candidate["symbol"],
            action="BUY",
            strike=candidate.get("strike"),
            expiry=candidate.get("expiry"),
            option_type=candidate.get("type"),
            qty=1,
            price=candidate.get("theo_price"),
            ai_reasoning=decision["reasoning"],
            metadata={"order_result": result, "technicals": trade_data["technicals"]},
        )

        logger.info(f"Order placed: {candidate['symbol']} — {result}")
        return True

    except Exception as e:
        logger.error(f"Order failed: {e}")
        return False


async def agent_loop():
    """Main agent loop — scan, analyze, decide, execute."""
    logger.info("=" * 60)
    logger.info("ICARUS — Options Alpha Agent")
    logger.info("  Alpaca AI Trading Agents Hackathon 2026")
    logger.info("=" * 60)

    # Initialize database
    init_db()

    # Connect to Alpaca (MCP primary, REST fallback)
    logger.info("Connecting to Alpaca...")
    client = await get_client()
    agent_state["status"] = "running"

    # Print options order schema
    if hasattr(client, 'tools') and 'place_option_order' in client.tools:
        logger.info(f"ORDER SCHEMA: {json.dumps(client.tools['place_option_order'].inputSchema, indent=2)}")

    # Get initial account info
    account = await client.get_account()

    agent_state["account"] = account
    if account:
        logger.info(f"Account: equity=${account.get('equity', '?')}, "
                     f"buying_power=${account.get('buying_power', '?')}")

    # Main loop
    while True:
        try:
            agent_state["cycle_count"] += 1
            cycle = agent_state["cycle_count"]
            logger.info(f"\n{'—' * 40}")
            logger.info(f"Scan cycle #{cycle}")
            logger.info(f"{'—' * 40}")

            # Refresh account
            account = await client.get_account()
            agent_state["account"] = account

            # Refresh positions
            positions = await client.get_positions()
            agent_state["positions"] = positions if isinstance(positions, list) else []

            # Scan all symbols
            trades_this_cycle = 0
            candidates_this_cycle = 0

            for symbol in WATCHLIST:
                try:
                    agent_state["current_scan"] = symbol
                    result = await scan_symbol(client, symbol)

                    if result:
                        candidates_this_cycle += 1
                        success = await execute_trade(client, result)
                        if success:
                            trades_this_cycle += 1
                            # Max 2 trades per cycle
                            if trades_this_cycle >= 2:
                                logger.info("Max trades per cycle reached")
                                break

                except Exception as e:
                    logger.error(f"Error scanning {symbol}: {e}")
                    continue

            # Log the scan
            log_scan(
                symbols_scanned=len(WATCHLIST),
                candidates_found=candidates_this_cycle,
                trades_executed=trades_this_cycle,
                summary=f"Cycle #{cycle}: {candidates_this_cycle} candidates, {trades_this_cycle} trades",
            )

            agent_state["last_scan"] = datetime.now().isoformat()
            agent_state["current_scan"] = None

            logger.info(f"Cycle #{cycle} complete: "
                         f"{candidates_this_cycle} candidates, {trades_this_cycle} trades")
            logger.info(f"Next scan in {SCAN_INTERVAL}s...")

            await asyncio.sleep(SCAN_INTERVAL)

        except Exception as e:
            logger.error(f"Agent loop error: {e}")
            agent_state["status"] = "error"
            await asyncio.sleep(60)


# ──────────────────────────────────────────────
# Entry Point
# ──────────────────────────────────────────────
def main():
    # Start Flask dashboard in background thread
    dashboard_thread = threading.Thread(target=run_dashboard, daemon=True)
    dashboard_thread.start()
    logger.info(f"Dashboard running on port {PORT}")

    # Run agent loop
    asyncio.run(agent_loop())


if __name__ == "__main__":
    main()