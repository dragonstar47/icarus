"""
brain.py — Claude AI decision maker.
Evaluates options trade candidates and approves/rejects with reasoning.
"""

import os
import json
import logging
from datetime import datetime

logger = logging.getLogger("icarus.brain")


class IcarusBrain:
    """Claude AI brain that reasons through every trade."""

    def __init__(self):
        self.client = None
        self.model = "claude-sonnet-4-6"
        self.decisions = []

    def _get_client(self):
        if not self.client:
            import anthropic
            self.client = anthropic.Anthropic(
                api_key=os.environ.get("ANTHROPIC_API_KEY")
            )
        return self.client

    async def evaluate(self, candidate, technicals, news=None, positions=None):
        """
        Evaluate an options trade candidate.
        Returns: {"action": "APPROVE"/"REJECT", "reasoning": str, "confidence": float}
        """
        try:
            prompt = self._build_prompt(candidate, technicals, news, positions)
            client = self._get_client()

            response = client.messages.create(
                model=self.model,
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}]
            )

            result = self._parse_response(response.content[0].text)
            result["timestamp"] = datetime.now().isoformat()
            result["candidate"] = candidate.get("symbol", "unknown")

            self.decisions.append(result)
            if len(self.decisions) > 50:
                self.decisions = self.decisions[-50:]

            logger.info(f"AI Decision: {result['action']} — {result['reasoning'][:100]}")
            return result

        except Exception as e:
            logger.error(f"AI Brain error: {e}")
            return {
                "action": "REJECT",
                "reasoning": f"AI Brain error: {str(e)}. Defaulting to REJECT for safety.",
                "confidence": 0.0,
                "timestamp": datetime.now().isoformat(),
            }

    def _build_prompt(self, candidate, technicals, news=None, positions=None):
        """Build the analysis prompt for Claude."""
        news_text = ""
        if news:
            if isinstance(news, list):
                headlines = [n.get("headline", n.get("title", "")) for n in news[:5]]
                news_text = "\n".join(f"  - {h}" for h in headlines if h)
            elif isinstance(news, str):
                news_text = news

        positions_text = "None"
        if positions:
            if isinstance(positions, list) and positions:
                positions_text = json.dumps(positions[:3], indent=2)

        recent_decisions = ""
        if self.decisions:
            recent = self.decisions[-3:]
            recent_decisions = "\n".join(
                f"  - {d.get('candidate', '?')}: {d.get('action', '?')}"
                for d in recent
            )

        return f"""You are Icarus, an AI options trading agent. Evaluate this trade candidate and decide: APPROVE or REJECT.
Be selective but not paralyzed. Approve trades with reasonable edge. This is paper trading for a hackathon demo — we need to demonstrate the system works end to end.

## CANDIDATE
Symbol: {candidate.get('symbol', 'N/A')}
Type: {candidate.get('type', 'N/A').upper()}
Strike: ${candidate.get('strike', 0)}
Expiry: {candidate.get('expiry', 'N/A')} ({candidate.get('dte', 0)} DTE)
Theoretical Price: ${candidate.get('theo_price', 0)}
OTM %: {candidate.get('otm_pct', 0)}%

## GREEKS
Delta: {candidate.get('delta', 0)}
Gamma: {candidate.get('gamma', 0)}
Theta: {candidate.get('theta', 0)} (daily decay)
Vega: {candidate.get('vega', 0)}

## TECHNICALS
Spot Price: ${technicals.get('spot_price', 0)}
RSI: {technicals.get('rsi', 50)}
EMA20: ${technicals.get('ema20', 0)}
Trend: {technicals.get('trend', 'unknown')}

## NEWS
{news_text if news_text else "No recent news"}

## CURRENT POSITIONS
{positions_text}

## RECENT DECISIONS
{recent_decisions if recent_decisions else "None yet"}

## RULES
- REJECT if trend is bearish and candidate is a CALL
- REJECT if trend is bullish and candidate is a PUT
- REJECT if RSI > 75 for calls (overbought) or RSI < 25 for puts (oversold)
- REJECT if delta < 0.20 (too far OTM)
- REJECT if theta decay > 3% of price per day
- APPROVE only with clear reasoning

Respond in this exact JSON format:
{{"action": "APPROVE" or "REJECT", "reasoning": "your 1-2 sentence explanation", "confidence": 0.0 to 1.0, "risk_notes": "any warnings"}}
"""

    def _parse_response(self, text):
        """Parse Claude's response into structured decision."""
        try:
            if "{" in text and "}" in text:
                json_str = text[text.index("{"):text.rindex("}") + 1]
                data = json.loads(json_str)
                return {
                    "action": data.get("action", "REJECT").upper(),
                    "reasoning": data.get("reasoning", "No reasoning provided"),
                    "confidence": float(data.get("confidence", 0.5)),
                    "risk_notes": data.get("risk_notes", ""),
                }
        except (json.JSONDecodeError, ValueError):
            pass

        action = "APPROVE" if "APPROVE" in text.upper() else "REJECT"
        return {
            "action": action,
            "reasoning": text[:200],
            "confidence": 0.5,
            "risk_notes": "",
        }

    def get_recent_decisions(self, limit=10):
        """Get recent decisions for dashboard."""
        return self.decisions[-limit:]