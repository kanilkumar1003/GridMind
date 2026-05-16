#!/usr/bin/env python3
"""
GridMind Agent — MCP + Gemini Flash
====================================
Multi-turn reasoning agent that connects to MCP tools and uses
Google Gemini Flash for decision-making across a 24-hour energy cycle.
"""

import argparse
import asyncio
import json
import os
import re
import sys
import httpx
from dotenv import load_dotenv

from google import genai
from google.genai import types

from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters

load_dotenv()

# ─── Configuration ───────────────────────────────────────────────────────────
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:e4b")
BATTERY_CAPACITY_KWH = 13.5
DEFAULT_HOURS = 24

LOCATION = {
    "name": "Bengaluru, Karnataka",
    "latitude": 12.9716,
    "longitude": 77.5946,
}


def load_system_prompt(path: str = "system_prompt.md") -> str:
    """Load the master system prompt from file."""
    try:
        with open(path, "r") as f:
            return f.read()
    except FileNotFoundError:
        print(f"Error: {path} not found.")
        sys.exit(1)


def mcp_schema_to_gemini(mcp_tools) -> list:
    """Convert MCP tool schemas to Gemini function declarations."""
    declarations = []
    for tool in mcp_tools:
        schema = tool.inputSchema or {}
        # Build a clean properties dict for Gemini
        properties = {}
        for prop_name, prop_def in schema.get("properties", {}).items():
            prop_type = prop_def.get("type", "string").upper()
            # Map JSON Schema types to Gemini Schema types
            type_map = {
                "STRING": "STRING",
                "INTEGER": "INTEGER",
                "NUMBER": "NUMBER",
                "BOOLEAN": "BOOLEAN",
                "FLOAT": "NUMBER",
            }
            properties[prop_name] = types.Schema(
                type=type_map.get(prop_type, "STRING"),
                description=prop_def.get("description", ""),
            )

        params = types.Schema(
            type="OBJECT",
            properties=properties,
            required=schema.get("required", []),
        )

        declarations.append(
            types.FunctionDeclaration(
                name=tool.name,
                description=tool.description or "",
                parameters=params,
            )
        )
    return declarations


def mcp_schema_to_openai(mcp_tools) -> list:
    """Convert MCP tool schemas to OpenAI function declarations for Ollama."""
    declarations = []
    for tool in mcp_tools:
        schema = tool.inputSchema or {}
        # Ensure type is present, Ollama requires it.
        if "type" not in schema:
            schema["type"] = "object"
        declarations.append({
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": schema
            }
        })
    return declarations


def extract_json_from_text(text: str) -> dict | None:
    """Extract a JSON object from LLM text response."""
    # Try to find JSON in code fences first
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    # Try the whole text as JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try to find any JSON object
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return None


async def run_single_hour(
    client: genai.Client,
    session: ClientSession,
    gemini_tools: list,
    system_prompt: str,
    state: dict,
) -> dict:
    """Run the agent for a single hour using Gemini + MCP tools."""
    hour = state["hour"]

    user_msg = (
        f"Current state for hour {hour}:\n"
        f"```json\n{json.dumps(state, indent=2)}\n```\n\n"
        f"Location: {LOCATION['name']} (lat={LOCATION['latitude']}, lon={LOCATION['longitude']})\n\n"
        f"Execute the mandatory 6-step reasoning chain (A→F) for this hour.\n"
        f"Use the available tools to gather real data (fetch_weather, get_grid_price, get_household_load) "
        f"and to execute actions (sell_to_grid, buy_from_grid, charge_battery, discharge_battery).\n"
        f"Respond with ONLY the JSON object matching the schema in the system prompt. No extra text."
    )

    contents = [types.Content(role="user", parts=[types.Part(text=user_msg)])]

    tool_config = types.Tool(function_declarations=gemini_tools)
    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        tools=[tool_config],
        temperature=0.1,
    )

    max_rounds = 10  # Safety limit for tool-calling rounds
    for round_num in range(max_rounds):
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=contents,
            config=config,
        )
        
        # Rate limiting: add small delay between API calls (10 requests/min = 6s per request)
        if round_num < max_rounds - 1:
            await asyncio.sleep(0.5)

        candidate = response.candidates[0]

        # Check for function calls
        function_calls = [p for p in candidate.content.parts if p.function_call]

        if not function_calls:
            # Final text response — extract the JSON
            text_parts = [p.text for p in candidate.content.parts if p.text]
            full_text = "\n".join(text_parts)
            return extract_json_from_text(full_text)

        # Add assistant's response to conversation
        contents.append(candidate.content)

        # Execute each function call via MCP
        function_response_parts = []
        for part in function_calls:
            fc = part.function_call
            tool_name = fc.name
            tool_args = dict(fc.args) if fc.args else {}

            print(f"    🔧 MCP Tool: {tool_name}({json.dumps(tool_args, default=str)})")

            try:
                result = await session.call_tool(tool_name, arguments=tool_args)
                result_text = result.content[0].text if result.content else "{}"
                result_data = json.loads(result_text)
            except Exception as e:
                result_data = {"error": str(e)}

            function_response_parts.append(
                types.Part(
                    function_response=types.FunctionResponse(
                        name=tool_name,
                        response=result_data,
                    )
                )
            )

        # Add tool results to conversation
        contents.append(types.Content(role="user", parts=function_response_parts))

    print(f"  ⚠️  Hour {hour}: Max tool-calling rounds reached")
    return None


async def run_single_hour_ollama(
    session: ClientSession,
    ollama_tools: list,
    system_prompt: str,
    state: dict,
) -> dict:
    """Run the agent for a single hour using Ollama + MCP tools."""
    hour = state["hour"]

    user_msg = (
        f"Current state for hour {hour}:\n"
        f"```json\n{json.dumps(state, indent=2)}\n```\n\n"
        f"Location: {LOCATION['name']} (lat={LOCATION['latitude']}, lon={LOCATION['longitude']})\n\n"
        f"Execute the mandatory 6-step reasoning chain (A→F) for this hour.\n"
        f"Use the available tools to gather real data (fetch_weather, get_grid_price, get_household_load) "
        f"and to execute actions (sell_to_grid, buy_from_grid, charge_battery, discharge_battery).\n"
        f"Respond with ONLY the JSON object matching the schema in the system prompt. No extra text."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg}
    ]

    max_rounds = 10
    async with httpx.AsyncClient(timeout=60.0) as client:
        for round_num in range(max_rounds):
            payload = {
                "model": OLLAMA_MODEL,
                "messages": messages,
                "tools": ollama_tools,
                "options": {
                    "temperature": 0.1
                }
            }
            
            try:
                response = await client.post("http://localhost:11434/v1/chat/completions", json=payload)
                response.raise_for_status()
                data = response.json()
                
                # Rate limiting: add small delay between API calls
                if round_num < max_rounds - 1:
                    await asyncio.sleep(0.5)
            except Exception as e:
                print(f"  ❌ Ollama API error: {e}")
                return None

            message = data["choices"][0]["message"]
            messages.append(message)

            tool_calls = message.get("tool_calls")
            
            if not tool_calls:
                # Final text response
                return extract_json_from_text(message.get("content", ""))

            for tc in tool_calls:
                fn = tc["function"]
                tool_name = fn["name"]
                tool_args = json.loads(fn["arguments"]) if fn.get("arguments") else {}

                print(f"    🔧 MCP Tool: {tool_name}({json.dumps(tool_args, default=str)})")

                try:
                    result = await session.call_tool(tool_name, arguments=tool_args)
                    result_text = result.content[0].text if result.content else "{}"
                except Exception as e:
                    result_text = json.dumps({"error": str(e)})

                messages.append({
                    "role": "tool",
                    "content": result_text,
                    "name": tool_name
                })

    print(f"  ⚠️  Hour {hour}: Max tool-calling rounds reached")
    return None


async def run_agent(hours: int = DEFAULT_HOURS, mode: str = "online"):
    """Execute the full multi-turn agent loop with MCP + LLM."""
    if mode == "online" and not GOOGLE_API_KEY:
        print("Error: GOOGLE_API_KEY not set. Create a .env file with your key.")
        sys.exit(1)

    system_prompt = load_system_prompt()
    gemini_client = genai.Client(api_key=GOOGLE_API_KEY) if mode == "online" else None

    # Start MCP server as subprocess
    server_params = StdioServerParameters(
        command=sys.executable,  # Use same Python interpreter
        args=["mcp_server.py"],
    )

    print("=" * 70)
    print("  ⚡ SMART GRID ENERGY ARBITRAGE AGENT — GridMind")
    if mode == "online":
        print(f"  🤖 LLM: Google Gemini Flash ({MODEL_NAME}) | 🔌 Tools: MCP Protocol")
    else:
        print(f"  🤖 LLM: Offline Ollama ({OLLAMA_MODEL}) | 🔌 Tools: MCP Protocol")
    print("  🌤️  Weather: Open-Meteo (LIVE)  |  💰 Pricing: ERCOT TOU")
    print("=" * 70)
    print(f"  Location       : {LOCATION['name']} ({LOCATION['latitude']}, {LOCATION['longitude']})")
    print(f"  Battery Capacity: {BATTERY_CAPACITY_KWH} kWh")
    print(f"  Mode           : {mode.upper()}")
    print(f"  Simulation     : {hours} hours")
    print("=" * 70)

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("\n  ✅ MCP Server connected. Discovering tools...")

            # Discover MCP tools
            tools_result = await session.list_tools()
            tool_names = [t.name for t in tools_result.tools]
            print(f"  📋 Tools available: {', '.join(tool_names)}\n")

            # Convert to appropriate formats
            gemini_tools = mcp_schema_to_gemini(tools_result.tools)
            ollama_tools = mcp_schema_to_openai(tools_result.tools)

            # Initialize state
            state = {
                "hour": 0,
                "battery_soc_kWh": 6.75,
                "cumulative_revenue": 0.0,
                "cumulative_cost": 0.0,
            }

            history = []

            for h in range(hours):
                state["hour"] = h
                print(f"\n{'─' * 60}")
                print(f"  ⏰ HOUR {h:02d}:00")
                print(f"{'─' * 60}")

                # Call LLM with MCP tools
                if mode == "online":
                    response = await run_single_hour(
                        gemini_client, session, gemini_tools, system_prompt, state
                    )
                else:
                    response = await run_single_hour_ollama(
                        session, ollama_tools, system_prompt, state
                    )

                if response is None:
                    print(f"  ❌ Failed to get valid response for hour {h}. Skipping.")
                    continue

                # Rate limiting: 6 seconds per request = 10 requests/minute
                if h < hours - 1:  # Don't sleep after the last hour
                    await asyncio.sleep(6)

                # Display reasoning trace
                for step in response.get("reasoning_trace", []):
                    tag = step.get("tag", "")
                    desc = step.get("description", "")
                    print(f"  {tag:16s} {desc[:100]}{'...' if len(desc) > 100 else ''}")

                # Display actions
                actions = response.get("actions", [])
                if actions:
                    action_strs = [f"{a.get('action', 'UNKNOWN')} {float(a.get('amount_kWh', 0.0)):.2f} kWh" for a in actions if isinstance(a, dict)]
                    print(f"  {'Actions':16s} {' | '.join(action_strs)}")

                # Display verification
                verify = next(
                    (s for s in response.get("reasoning_trace", []) if s.get("step") == "E"),
                    None,
                )
                if verify and "balance_check" in verify:
                    bc = verify["balance_check"]
                    symbol = "✓" if bc.get("balanced") else "✗"
                    print(f"  {'Verify':16s} {symbol} LHS={bc.get('lhs')} RHS={bc.get('rhs')}")

                # Update state
                new_state = response.get("new_state", {})
                state["battery_soc_kWh"] = new_state.get(
                    "battery_soc_kWh", state["battery_soc_kWh"]
                )
                state["cumulative_revenue"] = new_state.get(
                    "cumulative_revenue", state["cumulative_revenue"]
                )
                state["cumulative_cost"] = new_state.get(
                    "cumulative_cost", state["cumulative_cost"]
                )

                soc_pct = state["battery_soc_kWh"] / BATTERY_CAPACITY_KWH * 100
                print(
                    f"  {'State':16s} SOC={state['battery_soc_kWh']:.2f} kWh ({soc_pct:.0f}%) | "
                    f"Rev=${state['cumulative_revenue']:.4f} | Cost=${state['cumulative_cost']:.4f}"
                )

                # Check for fallbacks
                for fb in response.get("fallbacks_used", []):
                    print(f"  [FALLBACK]     {fb.get('tool', '?')}: {fb.get('reason', '?')}")

                history.append(response)

            # ── Daily Summary ────────────────────────────────────────────
            print(f"\n{'=' * 70}")
            print("  📊 DAILY SUMMARY")
            print(f"{'=' * 70}")

            total_bought = sum(
                float(a.get("amount_kWh", 0.0))
                for r in history
                for a in r.get("actions", [])
                if isinstance(a, dict) and a.get("action") == "BUY"
            )
            total_sold = sum(
                float(a.get("amount_kWh", 0.0))
                for r in history
                for a in r.get("actions", [])
                if isinstance(a, dict) and a.get("action") == "SELL"
            )
            total_stored = sum(
                float(a.get("amount_kWh", 0.0))
                for r in history
                for a in r.get("actions", [])
                if isinstance(a, dict) and a.get("action") == "STORE"
            )
            total_discharged = sum(
                float(a.get("amount_kWh", 0.0))
                for r in history
                for a in r.get("actions", [])
                if isinstance(a, dict) and a.get("action") == "DISCHARGE"
            )

            net = state["cumulative_revenue"] - state["cumulative_cost"]

            print(f"  Total Revenue      : ${state['cumulative_revenue']:.4f}")
            print(f"  Total Cost         : ${state['cumulative_cost']:.4f}")
            print(f"  Net Profit/Loss    : ${net:.4f}")
            print(f"  Energy Bought      : {total_bought:.2f} kWh")
            print(f"  Energy Sold        : {total_sold:.2f} kWh")
            print(f"  Energy Stored      : {total_stored:.2f} kWh")
            print(f"  Energy Discharged  : {total_discharged:.2f} kWh")
            print(f"  Final Battery SOC  : {state['battery_soc_kWh']:.2f} kWh")
            print(f"{'=' * 70}")

            # Save full trace
            output = {"history": history, "daily_summary": {"total_revenue": state["cumulative_revenue"], "total_cost": state["cumulative_cost"], "net_profit": net}}
            output_path = "agent_trace.json"
            with open(output_path, "w") as f:
                json.dump(output, f, indent=2)
            print(f"\n  💾 Full trace saved to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Smart Grid Energy Arbitrage Agent")
    parser.add_argument("--hours", type=int, default=DEFAULT_HOURS, help="Number of hours to simulate")
    parser.add_argument("--mode", type=str, choices=["online", "offline"], default="online", help="Execution mode (online with Gemini, offline with Ollama)")
    args = parser.parse_args()

    asyncio.run(run_agent(hours=args.hours, mode=args.mode))


if __name__ == "__main__":
    main()
