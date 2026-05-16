#!/usr/bin/env python3
"""
Smart Grid Energy Arbitrage Agent — Main Loop
==============================================
A multi-turn reasoning agent that optimizes microgrid energy decisions
(store, use, sell, buy) across a 24-hour cycle using mock LLM + tools.
"""

import json
import random
import math
import copy
from typing import Any

# ─── Configuration ───────────────────────────────────────────────────────────

PANEL_CAPACITY_KW = 10.0
PANEL_EFFICIENCY = 0.18
BATTERY_CAPACITY_KWH = 13.5
BATTERY_MIN_SOC = 0.0
SELL_THRESHOLD = 0.15      # $/kWh — sell if price exceeds this
BUY_THRESHOLD = 0.20       # $/kWh — buy from grid if price below this
PEAK_PRICE = 0.35           # $/kWh — peak pricing trigger
BATTERY_HIGH = 0.80 * BATTERY_CAPACITY_KWH
BATTERY_LOW = 0.20 * BATTERY_CAPACITY_KWH
BATTERY_CRITICAL = 0.10 * BATTERY_CAPACITY_KWH
TEMP_DERATE_PER_DEGREE = 0.004
TEMP_DERATE_BASELINE = 25.0
VERIFY_TOLERANCE = 0.01

# ─── Fallback Defaults ──────────────────────────────────────────────────────

FALLBACK_WEATHER = {"cloud_cover": 40.0, "temperature": 28.0, "uv_index": 5.0}
FALLBACK_PRICE = {"buy_price": 0.22, "sell_price": 0.10}
FALLBACK_LOAD = {"load_kWh": 1.8}

# ─── Mock Tool Functions ────────────────────────────────────────────────────

def fetch_weather(location: str, hour: int) -> dict:
    """Simulate weather API. Returns cloud_cover (%), temperature (°C), uv_index."""
    random.seed(hour * 31 + hash(location) % 100)
    is_daytime = 6 <= hour <= 18
    cloud = random.uniform(10, 90) if is_daytime else 100.0
    temp = 20 + 10 * math.sin(math.pi * (hour - 6) / 12) if is_daytime else random.uniform(15, 22)
    uv = max(0, int(8 * math.sin(math.pi * (hour - 6) / 12))) if is_daytime else 0
    return {"cloud_cover": round(cloud, 1), "temperature": round(temp, 1), "uv_index": uv}


def get_grid_price(hour: int) -> dict:
    """Simulate dynamic grid pricing. Peak hours = expensive."""
    random.seed(hour * 17)
    base_buy = 0.12
    if 7 <= hour <= 9 or 17 <= hour <= 21:
        base_buy = random.uniform(0.25, 0.45)  # peak
    elif 10 <= hour <= 16:
        base_buy = random.uniform(0.14, 0.22)  # mid
    else:
        base_buy = random.uniform(0.08, 0.14)  # off-peak
    sell_price = round(base_buy * random.uniform(0.45, 0.70), 4)
    return {"buy_price": round(base_buy, 4), "sell_price": sell_price}


def get_household_load(hour: int) -> dict:
    """Simulate household consumption pattern."""
    random.seed(hour * 43)
    base = 0.5
    if 7 <= hour <= 9:
        base = random.uniform(1.5, 2.5)  # morning
    elif 12 <= hour <= 14:
        base = random.uniform(1.0, 2.0)  # midday
    elif 17 <= hour <= 22:
        base = random.uniform(2.0, 3.5)  # evening peak
    else:
        base = random.uniform(0.3, 0.8)  # overnight / idle
    return {"load_kWh": round(base, 2)}


def sell_to_grid(amount_kWh: float, sell_price: float) -> dict:
    """Execute a sell-to-grid transaction."""
    revenue = round(amount_kWh * sell_price, 4)
    return {"confirmed": True, "revenue": revenue}


def buy_from_grid(amount_kWh: float, buy_price: float) -> dict:
    """Execute a buy-from-grid transaction."""
    cost = round(amount_kWh * buy_price, 4)
    return {"confirmed": True, "cost": cost}


def charge_battery(amount_kWh: float, current_soc: float) -> dict:
    """Charge battery, clamping to capacity."""
    new_soc = min(current_soc + amount_kWh, BATTERY_CAPACITY_KWH)
    actual = round(new_soc - current_soc, 4)
    return {"confirmed": True, "new_soc": round(new_soc, 4), "actual_stored": actual}


def discharge_battery(amount_kWh: float, current_soc: float) -> dict:
    """Discharge battery, clamping to zero."""
    new_soc = max(current_soc - amount_kWh, BATTERY_MIN_SOC)
    actual = round(current_soc - new_soc, 4)
    return {"confirmed": True, "new_soc": round(new_soc, 4), "actual_discharged": actual}


# ─── Tool Dispatcher ────────────────────────────────────────────────────────

TOOL_REGISTRY = {
    "fetch_weather": fetch_weather,
    "get_grid_price": get_grid_price,
    "get_household_load": get_household_load,
    "sell_to_grid": sell_to_grid,
    "buy_from_grid": buy_from_grid,
    "charge_battery": charge_battery,
    "discharge_battery": discharge_battery,
}


def execute_tool(name: str, params: dict) -> dict:
    """Dispatch a tool call; return result or error."""
    fn = TOOL_REGISTRY.get(name)
    if fn is None:
        return {"error": f"Unknown tool: {name}"}
    try:
        return fn(**params)
    except Exception as e:
        return {"error": str(e)}


# ─── Mock LLM — deterministic reasoning engine ─────────────────────────────

def call_llm(state: dict, system_prompt: str) -> dict:
    """
    Simulates the LLM agent's reasoning for one hour.
    In production, this would call an actual LLM API with the system prompt
    and state, then parse the JSON response. Here we implement the same
    decision logic directly so the loop can be demonstrated end-to-end.
    """
    hour = state["hour"]
    battery_soc = state["battery_soc_kWh"]
    cum_revenue = state["cumulative_revenue"]
    cum_cost = state["cumulative_cost"]
    location = state.get("location", "Austin, TX")

    reasoning_trace = []
    actions = []
    fallbacks_used = []

    # ── Step A: Gather Data [API_CALL] ──────────────────────────────────
    weather = fetch_weather(location, hour)
    price = get_grid_price(hour)
    load = get_household_load(hour)

    step_a = {
        "step": "A", "tag": "[API_CALL]",
        "description": f"Fetched weather, grid price, and household load for hour {hour}.",
        "tool_calls": [
            {"tool": "fetch_weather", "params": {"location": location, "hour": hour}, "result": weather},
            {"tool": "get_grid_price", "params": {"hour": hour}, "result": price},
            {"tool": "get_household_load", "params": {"hour": hour}, "result": load},
        ]
    }
    reasoning_trace.append(step_a)

    # ── Step B: Calculate Solar Generation [MATH] ───────────────────────
    cloud = weather["cloud_cover"]
    temp = weather["temperature"]
    solar_raw = PANEL_CAPACITY_KW * (1 - cloud / 100) * PANEL_EFFICIENCY * 1  # 1-hour slot
    derate = 0.0
    if temp > TEMP_DERATE_BASELINE:
        derate = (temp - TEMP_DERATE_BASELINE) * TEMP_DERATE_PER_DEGREE
    solar_output = round(solar_raw * (1 - derate), 4)
    # Night hours produce zero
    if hour < 6 or hour > 18:
        solar_output = 0.0

    step_b = {
        "step": "B", "tag": "[MATH]",
        "description": (
            f"solar_raw = {PANEL_CAPACITY_KW} × (1 - {cloud}/100) × {PANEL_EFFICIENCY} × 1 = {round(solar_raw, 4)} kWh. "
            f"Temp derate: {temp}°C → {round(derate * 100, 2)}% loss → solar_output = {solar_output} kWh."
        )
    }
    reasoning_trace.append(step_b)

    # ── Step C: Energy Balance [MATH] ───────────────────────────────────
    household_load = load["load_kWh"]
    net_energy = round(solar_output - household_load, 4)
    surplus = net_energy > 0
    deficit = net_energy < 0

    step_c = {
        "step": "C", "tag": "[MATH]",
        "description": (
            f"net_energy = {solar_output} - {household_load} = {net_energy} kWh. "
            f"{'Surplus' if surplus else 'Deficit' if deficit else 'Balanced'} of {abs(net_energy)} kWh."
        )
    }
    reasoning_trace.append(step_c)

    # ── Step D: Optimize Decision [LOGIC] ───────────────────────────────
    energy_used = household_load  # Total load met by solar + grid + battery
    energy_stored = 0.0
    energy_sold = 0.0
    energy_bought = 0.0
    energy_discharged = 0.0
    decision_desc = ""

    buy_price = price["buy_price"]
    sell_price_val = price["sell_price"]

    if surplus:
        surplus_amount = abs(net_energy)
        if sell_price_val > SELL_THRESHOLD and battery_soc > BATTERY_HIGH:
            # Sell surplus
            energy_sold = surplus_amount
            result = sell_to_grid(energy_sold, sell_price_val)
            cum_revenue += result["revenue"]
            actions.append({"action": "SELL", "amount_kWh": energy_sold, "tool": "sell_to_grid"})
            decision_desc = (
                f"Surplus {surplus_amount} kWh. sell_price ${sell_price_val} > ${SELL_THRESHOLD} "
                f"AND battery SOC {battery_soc} > {BATTERY_HIGH}. → SELL {energy_sold} kWh. "
                f"Revenue: ${result['revenue']}."
            )
        elif battery_soc < BATTERY_HIGH:
            # Store in battery
            can_store = min(surplus_amount, BATTERY_CAPACITY_KWH - battery_soc)
            result = charge_battery(can_store, battery_soc)
            energy_stored = result["actual_stored"]
            battery_soc = result["new_soc"]
            remainder = round(surplus_amount - energy_stored, 4)
            actions.append({"action": "STORE", "amount_kWh": energy_stored, "tool": "charge_battery"})
            decision_desc = f"Surplus {surplus_amount} kWh. Battery below 80% → STORE {energy_stored} kWh."
            if remainder > 0:
                # Sell the rest
                res2 = sell_to_grid(remainder, sell_price_val)
                energy_sold = remainder
                cum_revenue += res2["revenue"]
                actions.append({"action": "SELL", "amount_kWh": remainder, "tool": "sell_to_grid"})
                decision_desc += f" Remainder {remainder} kWh SOLD at ${sell_price_val}."
        else:
            # Battery full, sell at whatever rate
            energy_sold = surplus_amount
            result = sell_to_grid(energy_sold, sell_price_val)
            cum_revenue += result["revenue"]
            actions.append({"action": "SELL", "amount_kWh": energy_sold, "tool": "sell_to_grid"})
            decision_desc = f"Battery full. SELL {energy_sold} kWh at ${sell_price_val}."
    elif deficit:
        deficit_amount = abs(net_energy)
        if buy_price > PEAK_PRICE and battery_soc > BATTERY_CRITICAL:
            # Peak pricing — discharge battery
            can_discharge = min(deficit_amount, battery_soc - BATTERY_CRITICAL)
            result = discharge_battery(can_discharge, battery_soc)
            energy_discharged = result["actual_discharged"]
            battery_soc = result["new_soc"]
            shortfall = round(deficit_amount - energy_discharged, 4)
            actions.append({"action": "DISCHARGE", "amount_kWh": energy_discharged, "tool": "discharge_battery"})
            decision_desc = f"Peak pricing ${buy_price} > ${PEAK_PRICE}. DISCHARGE {energy_discharged} kWh."
            if shortfall > 0:
                res2 = buy_from_grid(shortfall, buy_price)
                energy_bought = shortfall
                cum_cost += res2["cost"]
                actions.append({"action": "BUY", "amount_kWh": shortfall, "tool": "buy_from_grid"})
                decision_desc += f" Still short {shortfall} kWh → BUY at ${buy_price}."
        elif buy_price <= BUY_THRESHOLD:
            # Cheap grid power — buy
            energy_bought = deficit_amount
            result = buy_from_grid(energy_bought, buy_price)
            cum_cost += result["cost"]
            actions.append({"action": "BUY", "amount_kWh": energy_bought, "tool": "buy_from_grid"})
            decision_desc = f"buy_price ${buy_price} ≤ ${BUY_THRESHOLD} → BUY {energy_bought} kWh. Cost: ${result['cost']}."
        elif battery_soc > BATTERY_LOW:
            # Discharge battery
            can_discharge = min(deficit_amount, battery_soc - BATTERY_LOW)
            result = discharge_battery(can_discharge, battery_soc)
            energy_discharged = result["actual_discharged"]
            battery_soc = result["new_soc"]
            shortfall = round(deficit_amount - energy_discharged, 4)
            actions.append({"action": "DISCHARGE", "amount_kWh": energy_discharged, "tool": "discharge_battery"})
            decision_desc = f"buy_price ${buy_price} > ${BUY_THRESHOLD}, battery OK → DISCHARGE {energy_discharged} kWh."
            if shortfall > 0:
                res2 = buy_from_grid(shortfall, buy_price)
                energy_bought = shortfall
                cum_cost += res2["cost"]
                actions.append({"action": "BUY", "amount_kWh": shortfall, "tool": "buy_from_grid"})
                decision_desc += f" Shortfall {shortfall} kWh → BUY."
        else:
            # Battery low, must buy
            energy_bought = deficit_amount
            result = buy_from_grid(energy_bought, buy_price)
            cum_cost += result["cost"]
            actions.append({"action": "BUY", "amount_kWh": energy_bought, "tool": "buy_from_grid"})
            decision_desc = f"Battery low ({battery_soc} kWh). BUY {energy_bought} kWh at ${buy_price}."
    else:
        decision_desc = "Perfectly balanced. No action needed."

    actions.insert(0, {"action": "USE", "amount_kWh": round(energy_used, 4), "tool": "none"})

    step_d = {"step": "D", "tag": "[LOGIC]", "description": decision_desc}
    reasoning_trace.append(step_d)

    # ── Step E: Verify Energy Conservation [VERIFY] ─────────────────────
    lhs = round(energy_used + energy_stored + energy_sold, 4)
    rhs = round(solar_output + energy_bought + energy_discharged, 4)
    balanced = abs(lhs - rhs) <= VERIFY_TOLERANCE

    step_e = {
        "step": "E", "tag": "[VERIFY]",
        "description": (
            f"LHS(used {energy_used} + stored {energy_stored} + sold {energy_sold}) = {lhs}. "
            f"RHS(solar {solar_output} + bought {energy_bought} + discharged {energy_discharged}) = {rhs}. "
            f"{'✓ Balanced' if balanced else '✗ IMBALANCED — recheck needed'}."
        ),
        "balance_check": {"lhs": str(lhs), "rhs": str(rhs), "balanced": balanced}
    }
    reasoning_trace.append(step_e)

    if not balanced:
        print(f"  ⚠️  Hour {hour}: Energy imbalance detected! LHS={lhs}, RHS={rhs}")

    # ── Step F: Update State [STATE_UPDATE] ─────────────────────────────
    new_soc = round(battery_soc, 4)
    step_f = {
        "step": "F", "tag": "[STATE_UPDATE]",
        "description": f"new_battery_soc = {new_soc} kWh (clamped to [0, {BATTERY_CAPACITY_KWH}])."
    }
    reasoning_trace.append(step_f)

    return {
        "hour": hour,
        "reasoning_trace": reasoning_trace,
        "actions": actions,
        "new_state": {
            "battery_soc_kWh": new_soc,
            "cumulative_revenue": round(cum_revenue, 4),
            "cumulative_cost": round(cum_cost, 4),
            "hour": hour + 1
        },
        "fallbacks_used": fallbacks_used
    }


# ─── Daily Summary ──────────────────────────────────────────────────────────

def generate_daily_summary(history: list, final_state: dict) -> dict:
    """Produce end-of-day financial and energy summary."""
    total_solar = 0.0
    total_load = 0.0
    total_bought = 0.0
    total_sold = 0.0
    total_stored = 0.0
    total_discharged = 0.0
    soc_readings = []

    for entry in history:
        for action in entry.get("actions", []):
            amt = action["amount_kWh"]
            if action["action"] == "USE":
                total_load += amt
            elif action["action"] == "BUY":
                total_bought += amt
            elif action["action"] == "SELL":
                total_sold += amt
            elif action["action"] == "STORE":
                total_stored += amt
            elif action["action"] == "DISCHARGE":
                total_discharged += amt
        soc_readings.append(entry["new_state"]["battery_soc_kWh"])

    return {
        "type": "DAILY_SUMMARY",
        "total_revenue": round(final_state["cumulative_revenue"], 4),
        "total_cost": round(final_state["cumulative_cost"], 4),
        "net_profit": round(final_state["cumulative_revenue"] - final_state["cumulative_cost"], 4),
        "total_energy_bought_kWh": round(total_bought, 2),
        "total_energy_sold_kWh": round(total_sold, 2),
        "total_energy_stored_kWh": round(total_stored, 2),
        "total_energy_discharged_kWh": round(total_discharged, 2),
        "avg_battery_soc_kWh": round(sum(soc_readings) / max(len(soc_readings), 1), 2),
        "min_battery_soc_kWh": round(min(soc_readings, default=0), 2),
        "max_battery_soc_kWh": round(max(soc_readings, default=0), 2),
    }


# ─── Load System Prompt ─────────────────────────────────────────────────────

def load_system_prompt(path: str = "system_prompt.md") -> str:
    """Load the master system prompt from file."""
    try:
        with open(path, "r") as f:
            return f.read()
    except FileNotFoundError:
        print(f"Warning: {path} not found. Using embedded fallback prompt.")
        return "You are GridMind, a smart grid energy arbitrage agent."


# ─── Main Agent Loop ────────────────────────────────────────────────────────

def run_agent(hours: int = 24, location: str = "Austin, TX"):
    """
    Execute the multi-turn agent loop for the specified number of hours.
    Each iteration:
      1. Pass current state + system prompt to the LLM.
      2. Parse the structured JSON response.
      3. Execute any tool calls specified in the response.
      4. Update state for the next turn.
    """
    system_prompt = load_system_prompt()

    # Initialize state
    state = {
        "hour": 0,
        "battery_soc_kWh": 6.75,  # Start at 50% charge
        "cumulative_revenue": 0.0,
        "cumulative_cost": 0.0,
        "location": location,
        "history": []
    }

    print("=" * 70)
    print("  ⚡ SMART GRID ENERGY ARBITRAGE AGENT — GridMind")
    print("=" * 70)
    print(f"  Location       : {location}")
    print(f"  Battery Capacity: {BATTERY_CAPACITY_KWH} kWh")
    print(f"  Solar Panels   : {PANEL_CAPACITY_KW} kW peak")
    print(f"  Starting SOC   : {state['battery_soc_kWh']} kWh ({state['battery_soc_kWh']/BATTERY_CAPACITY_KWH*100:.0f}%)")
    print(f"  Simulation     : {hours} hours")
    print("=" * 70)

    history = []

    for h in range(hours):
        state["hour"] = h
        print(f"\n{'─' * 60}")
        print(f"  ⏰ HOUR {h:02d}:00")
        print(f"{'─' * 60}")

        # ── 1. Call LLM (mock) ──────────────────────────────────────────
        response = call_llm(state, system_prompt)

        # ── 2. Parse & display reasoning trace ──────────────────────────
        for step in response["reasoning_trace"]:
            tag = step["tag"]
            desc = step["description"]
            print(f"  {tag:16s} {desc[:100]}{'...' if len(desc) > 100 else ''}")

        # ── 3. Display actions ──────────────────────────────────────────
        print(f"  {'Actions':16s}", end="")
        action_strs = []
        for a in response["actions"]:
            action_strs.append(f"{a['action']} {a['amount_kWh']:.2f} kWh")
        print(" | ".join(action_strs))

        # ── 4. Display balance check ────────────────────────────────────
        verify = next((s for s in response["reasoning_trace"] if s["step"] == "E"), None)
        if verify and "balance_check" in verify:
            bc = verify["balance_check"]
            symbol = "✓" if bc["balanced"] else "✗"
            print(f"  {'Verify':16s} {symbol} LHS={bc['lhs']} RHS={bc['rhs']}")

        # ── 5. Update state for next turn ───────────────────────────────
        new = response["new_state"]
        state["battery_soc_kWh"] = new["battery_soc_kWh"]
        state["cumulative_revenue"] = new["cumulative_revenue"]
        state["cumulative_cost"] = new["cumulative_cost"]

        soc_pct = state["battery_soc_kWh"] / BATTERY_CAPACITY_KWH * 100
        print(f"  {'State':16s} SOC={state['battery_soc_kWh']:.2f} kWh ({soc_pct:.0f}%) | "
              f"Rev=${state['cumulative_revenue']:.4f} | Cost=${state['cumulative_cost']:.4f}")

        # ── 6. Display fallbacks if any ─────────────────────────────────
        if response["fallbacks_used"]:
            for fb in response["fallbacks_used"]:
                print(f"  [FALLBACK]     {fb['tool']}: {fb['reason']}")

        history.append(response)

    # ── Daily Summary ───────────────────────────────────────────────────
    summary = generate_daily_summary(history, state)
    print(f"\n{'=' * 70}")
    print("  📊 DAILY SUMMARY")
    print(f"{'=' * 70}")
    print(f"  Total Revenue      : ${summary['total_revenue']:.4f}")
    print(f"  Total Cost         : ${summary['total_cost']:.4f}")
    print(f"  Net Profit/Loss    : ${summary['net_profit']:.4f}")
    print(f"  Energy Bought      : {summary['total_energy_bought_kWh']:.2f} kWh")
    print(f"  Energy Sold        : {summary['total_energy_sold_kWh']:.2f} kWh")
    print(f"  Energy Stored      : {summary['total_energy_stored_kWh']:.2f} kWh")
    print(f"  Energy Discharged  : {summary['total_energy_discharged_kWh']:.2f} kWh")
    print(f"  Avg Battery SOC    : {summary['avg_battery_soc_kWh']:.2f} kWh")
    print(f"  Min/Max SOC        : {summary['min_battery_soc_kWh']:.2f} / {summary['max_battery_soc_kWh']:.2f} kWh")
    print(f"{'=' * 70}")

    # Save full trace to JSON
    output_path = "agent_trace.json"
    with open(output_path, "w") as f:
        json.dump({"history": history, "daily_summary": summary}, f, indent=2)
    print(f"\n  💾 Full trace saved to {output_path}")

    return summary


# ─── Entry Point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run_agent(hours=24, location="Austin, TX")
