"""
mcp_client.py — Alpaca connection layer with MCP primary + REST fallback.
If MCP fails, flip USE_MCP=false and everything still works.
"""

import os
import asyncio
import json
import logging
from contextlib import AsyncExitStack

logger = logging.getLogger("icarus.mcp")

# ──────────────────────────────────────────────
# MCP Client (Primary — uses Alpaca MCP Server)
# ──────────────────────────────────────────────
class MCPClient:
    """Connects to Alpaca via their official MCP server (stdio)."""

    def __init__(self):
        self.session = None
        self.exit_stack = AsyncExitStack()
        self.tools = {}
        self.connected = False

    async def connect(self):
        from mcp.client.stdio import stdio_client
        from mcp import ClientSession, StdioServerParameters

        server_params = StdioServerParameters(
            command="alpaca-mcp-server",
            args=["serve"],
            env={
                "ALPACA_API_KEY": os.environ["ALPACA_API_KEY"],
                "ALPACA_SECRET_KEY": os.environ["ALPACA_SECRET_KEY"],
                "ALPACA_PAPER_TRADE": "true",
                "PATH": os.environ.get("PATH", ""),
            }
        )

        transport = await self.exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        read, write = transport
        self.session = await self.exit_stack.enter_async_context(
            ClientSession(read, write)
        )
        await self.session.initialize()

        # Cache tool names
        response = await self.session.list_tools()
        self.tools = {t.name: t for t in response.tools}
        self.connected = True
        logger.info(f"MCP connected — {len(self.tools)} tools available")

    async def call_tool(self, name, args=None):
        """Call an MCP tool and return the text result."""
        result = await self.session.call_tool(name, args or {})
        if result.content:
            text = result.content[0].text
            try:
                return json.loads(text)
            except (json.JSONDecodeError, TypeError):
                return text
        return None

    async def get_account(self):
        for name in ["get_account_info", "get_account", "account_info"]:
            if name in self.tools:
                return await self.call_tool(name)
        logger.warning("No account tool found in MCP")
        return None

    async def get_options_chain(self, symbol):
        for name in ["get_option_chain", "get_options_chain", "option_chain", "get_option_contracts"]:
            if name in self.tools:
                try:
                    return await self.call_tool(name, {"underlying_symbol": symbol})
                except Exception:
                    try:
                        return await self.call_tool(name, {"symbol": symbol})
                    except Exception as e:
                        logger.error(f"Options chain error: {e}")
        return None

    async def get_bars(self, symbol, timeframe="1Day", limit=30):
        for name in ["get_stock_bars", "get_bars", "stock_bars"]:
            if name in self.tools:
                try:
                    return await self.call_tool(name, {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "limit": limit,
                    })
                except Exception as e:
                    logger.error(f"Bars error: {e}")
        return None

    async def get_positions(self):
        for name in ["get_all_positions", "get_positions", "list_positions"]:
            if name in self.tools:
                return await self.call_tool(name)
        return None

    async def place_order(self, symbol, qty, side, order_type="market", time_in_force="day", limit_price=None):
        for name in ["place_order", "create_order", "submit_order"]:
            if name in self.tools:
                params = {
                    "symbol": symbol,
                    "qty": str(qty),
                    "side": side,
                    "type": order_type,
                    "time_in_force": time_in_force,
                }
                if limit_price and order_type == "limit":
                    params["limit_price"] = str(limit_price)
                return await self.call_tool(name, params)
        return None

    async def get_news(self, symbol):
        for name in ["get_news", "news", "get_stock_news"]:
            if name in self.tools:
                try:
                    return await self.call_tool(name, {"symbols": symbol, "limit": 5})
                except Exception:
                    try:
                        return await self.call_tool(name, {"symbol": symbol})
                    except Exception as e:
                        logger.error(f"News error: {e}")
        return None

    async def disconnect(self):
        if self.connected:
            await self.exit_stack.aclose()
            self.connected = False


# ──────────────────────────────────────────────
# REST Client (Fallback — uses alpaca-py directly)
# ──────────────────────────────────────────────
class RestClient:
    """Direct Alpaca API fallback if MCP has issues."""

    def __init__(self):
        self.trading_client = None
        self.data_client = None
        self.connected = False

    async def connect(self):
        from alpaca.trading.client import TradingClient
        from alpaca.data.historical import StockHistoricalDataClient

        self.trading_client = TradingClient(
            os.environ["ALPACA_API_KEY"],
            os.environ["ALPACA_SECRET_KEY"],
            paper=True
        )
        self.data_client = StockHistoricalDataClient(
            os.environ["ALPACA_API_KEY"],
            os.environ["ALPACA_SECRET_KEY"],
        )
        self.connected = True
        logger.info("REST client connected (fallback mode)")

    async def get_account(self):
        account = self.trading_client.get_account()
        return {
            "equity": str(account.equity),
            "buying_power": str(account.buying_power),
            "cash": str(account.cash),
            "portfolio_value": str(account.portfolio_value),
        }

    async def get_options_chain(self, symbol):
        import requests
        headers = {
            "APCA-API-KEY-ID": os.environ["ALPACA_API_KEY"],
            "APCA-API-SECRET-KEY": os.environ["ALPACA_SECRET_KEY"],
        }
        url = "https://paper-api.alpaca.markets/v2/options/contracts"
        params = {
            "underlying_symbols": symbol,
            "status": "active",
            "limit": 100,
        }
        resp = requests.get(url, headers=headers, params=params)
        if resp.status_code == 200:
            return resp.json()
        logger.error(f"REST options chain error: {resp.status_code} {resp.text}")
        return None

    async def get_bars(self, symbol, timeframe="1Day", limit=30):
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        from datetime import datetime, timedelta

        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Day,
            start=datetime.now() - timedelta(days=limit + 5),
            limit=limit,
        )
        bars = self.data_client.get_stock_bars(request)
        return bars[symbol] if symbol in bars else None

    async def get_positions(self):
        positions = self.trading_client.get_all_positions()
        return [
            {
                "symbol": p.symbol,
                "qty": str(p.qty),
                "side": p.side,
                "market_value": str(p.market_value),
                "unrealized_pl": str(p.unrealized_pl),
                "current_price": str(p.current_price),
            }
            for p in positions
        ]

    async def place_order(self, symbol, qty, side, order_type="market", time_in_force="day", limit_price=None):
        from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce

        side_enum = OrderSide.BUY if side == "buy" else OrderSide.SELL
        tif_enum = TimeInForce.DAY

        if order_type == "limit" and limit_price:
            req = LimitOrderRequest(
                symbol=symbol,
                qty=qty,
                side=side_enum,
                time_in_force=tif_enum,
                limit_price=limit_price,
            )
        else:
            req = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=side_enum,
                time_in_force=tif_enum,
            )
        order = self.trading_client.submit_order(req)
        return {"id": str(order.id), "status": order.status, "symbol": order.symbol}

    async def get_news(self, symbol):
        import requests
        headers = {
            "APCA-API-KEY-ID": os.environ["ALPACA_API_KEY"],
            "APCA-API-SECRET-KEY": os.environ["ALPACA_SECRET_KEY"],
        }
        url = "https://data.alpaca.markets/v1beta1/news"
        params = {"symbols": symbol, "limit": 5}
        resp = requests.get(url, headers=headers, params=params)
        if resp.status_code == 200:
            return resp.json().get("news", [])
        return []

    async def disconnect(self):
        self.connected = False


# ──────────────────────────────────────────────
# Factory — pick the right client
# ──────────────────────────────────────────────
async def get_client():
    """Returns connected MCP client (primary) or REST client (fallback)."""
    use_mcp = os.environ.get("USE_MCP", "true").lower() == "true"

    if use_mcp:
        try:
            client = MCPClient()
            await client.connect()
            return client
        except Exception as e:
            logger.error(f"MCP failed: {e}. Falling back to REST.")

    client = RestClient()
    await client.connect()
    return client