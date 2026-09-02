"""
SMOKE TEST — Run this FIRST before anything else.
Verifies Alpaca MCP server connects and shows you the real tool names.

Usage:
  pip install mcp alpaca-mcp-server
  export ALPACA_API_KEY=your_paper_key
  export ALPACA_SECRET_KEY=your_paper_secret
  python smoke_mcp.py
"""

import asyncio
import os
import json

async def smoke_test():
    try:
        from mcp.client.stdio import stdio_client
        from mcp import ClientSession, StdioServerParameters
        print("✅ MCP SDK imported")
    except ImportError:
        print("❌ MCP SDK not found. Run: pip install mcp")
        return

    api_key = os.environ.get("ALPACA_API_KEY", "")
    secret_key = os.environ.get("ALPACA_SECRET_KEY", "")
    if not api_key or not secret_key:
        print("❌ Set ALPACA_API_KEY and ALPACA_SECRET_KEY env vars")
        return
    print(f"✅ API key loaded: {api_key[:8]}...")

    print("\n🔌 Connecting to Alpaca MCP server...")

    commands_to_try = [
        {"command": "alpaca-mcp-server", "args": ["serve"]},
        {"command": "alpaca-mcp-server", "args": []},
        {"command": "python", "args": ["-m", "alpaca_mcp_server"]},
        {"command": "uvx", "args": ["alpaca-mcp-server"]},
    ]

    session = None
    from contextlib import AsyncExitStack
    exit_stack = AsyncExitStack()

    for cmd in commands_to_try:
        try:
            print(f"  Trying: {cmd['command']} {' '.join(cmd['args'])}")
            server_params = StdioServerParameters(
                command=cmd["command"],
                args=cmd["args"],
                env={
                    "ALPACA_API_KEY": api_key,
                    "ALPACA_SECRET_KEY": secret_key,
                    "ALPACA_PAPER_TRADE": "true",
                    "PATH": os.environ.get("PATH", ""),
                }
            )
            transport = await exit_stack.enter_async_context(
                stdio_client(server_params)
            )
            read, write = transport
            session = await exit_stack.enter_async_context(
                ClientSession(read, write)
            )
            await session.initialize()
            print(f"  ✅ Connected with: {cmd['command']} {' '.join(cmd['args'])}")
            break
        except Exception as e:
            print(f"  ❌ Failed: {e}")
            await exit_stack.aclose()
            exit_stack = AsyncExitStack()
            session = None
            continue

    if not session:
        print("\n❌ Could not connect to MCP server with any method.")
        print("   Make sure alpaca-mcp-server is installed: pip install alpaca-mcp-server")
        await exit_stack.aclose()
        return

    print("\n📋 Available MCP Tools:")
    print("=" * 60)
    response = await session.list_tools()
    tools = response.tools
    print(f"Total tools: {len(tools)}\n")

    for i, tool in enumerate(tools):
        desc = tool.description[:80] if tool.description else "No description"
        print(f"  {i+1:3d}. {tool.name}")
        print(f"       {desc}")

    print("\n\n💰 Testing: Get Account Info")
    print("=" * 60)
    account_tools = [t for t in tools if "account" in t.name.lower()]
    if account_tools:
        tool_name = account_tools[0].name
        print(f"  Using tool: {tool_name}")
        try:
            result = await session.call_tool(tool_name, {})
            print(f"  ✅ Result: {result.content[0].text[:500] if result.content else 'empty'}")
        except Exception as e:
            print(f"  ❌ Error: {e}")
    else:
        print("  No account tool found")

    print("\n\n📊 Testing: Get Options Chain (AAPL)")
    print("=" * 60)
    option_tools = [t for t in tools if "option" in t.name.lower()]
    if option_tools:
        for t in option_tools:
            print(f"  Found option tool: {t.name}")
            if t.inputSchema:
                print(f"    Schema: {json.dumps(t.inputSchema, indent=2)[:300]}")
        tool_name = option_tools[0].name
        print(f"\n  Calling: {tool_name}")
        try:
            result = await session.call_tool(tool_name, {"underlying_symbol": "AAPL"})
            text = result.content[0].text if result.content else "empty"
            print(f"  ✅ Result (first 500 chars): {text[:500]}")
        except Exception as e:
            print(f"  ❌ Error: {e}")
            try:
                result = await session.call_tool(tool_name, {"symbol": "AAPL"})
                text = result.content[0].text if result.content else "empty"
                print(f"  ✅ Retry result: {text[:500]}")
            except Exception as e2:
                print(f"  ❌ Retry also failed: {e2}")
    else:
        print("  No options tools found")

    print("\n\n📝 TOOL NAMES FOR YOUR CODE:")
    print("=" * 60)
    for t in tools:
        name_lower = t.name.lower()
        if any(kw in name_lower for kw in ["order", "option", "account", "position", "bar", "quote", "chain", "news"]):
            print(f"  ⭐ {t.name}")

    await exit_stack.aclose()
    print("\n✅ Smoke test complete!")

if __name__ == "__main__":
    asyncio.run(smoke_test())