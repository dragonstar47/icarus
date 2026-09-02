# Icarus — AI-Powered Options Alpha Agent

An autonomous AI agent that hunts for options trades on Alpaca and actually thinks before it buys.

Built for the [Alpaca AI Trading Agents Hackathon 2026](https://lablab.ai/ai-hackathons/alpaca-ai-trading-agents-hackathon).

## What It Does

Icarus scans options chains across 7 major stocks, filters candidates through Black-Scholes pricing and Greeks validation, then sends each opportunity to a Claude AI brain for a final approve/reject decision with reasoning. Only high-conviction trades get executed.

## How It Works

1. **Options Scanner** — Queries Alpaca options chains via MCP Server for AAPL, NVDA, TSLA, META, AMD, MSFT, AMZN
2. **Analyst** — Runs Black-Scholes pricing (pure stdlib math), calculates Greeks (delta, gamma, theta, vega), filters for quality (5-45 DTE, max 10% OTM, theta < 5%/day)
3. **AI Brain** — Claude evaluates each candidate with technicals, news, and current positions. Returns APPROVE/REJECT with reasoning and confidence score
4. **Executor** — Approved trades execute on Alpaca paper account via MCP Server (REST API fallback)
5. **Dashboard** — Live Flask web UI showing account, positions, AI decisions, and trade history

## Architecture

- **MCP Primary, REST Fallback** — Connects to Alpaca through their official MCP Server. If MCP fails, automatically falls back to direct REST API
- **Claude AI Brain** — Every trade gets Claude's review. Real analysis of Greeks, technicals, and market context
- **Black-Scholes without scipy** — Uses math.erf for the normal CDF. Zero heavy dependencies
- **Single-process deployment** — Agent loop + Flask dashboard in one process on Railway

## Tech Stack

- Python 3.12
- Alpaca Trading API + MCP Server
- Anthropic Claude
- Flask
- SQLite
- Railway

## Setup

```bash
git clone https://github.com/dragonstar47/icarus.git
cd icarus
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your API keys
python smoke_mcp.py  # Test MCP connection first
python icarus.py     # Run the agent
```

## Watchlist

AAPL, NVDA, TSLA, META, AMD, MSFT, AMZN

## License

MIT