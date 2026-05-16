#!/usr/bin/env python3
"""
GridMind MCP Server — Real-Time Energy Tools
=============================================
Exposes energy management tools via MCP (Model Context Protocol).
Weather data comes from Open-Meteo API (free, no API key needed).
Grid pricing uses realistic ERCOT (Texas) Time-of-Use rate structure.
"""

from mcp.server.fastmcp import FastMCP
import httpx
import json
import random
import math

mcp = FastMCP("GridMind Energy Tools")

# ─── Constants ───────────────────────────────────────────────────────────────
BATTERY_CAPACITY_KWH = 13.5
BATTERY_MIN_SOC = 0.0

# ─── Weather Cache (fetch once per day, serve per hour) ──────────────────────
_weather_cache = {}


@mcp.tool()
async def fetch_weather(latitude: float, longitude: float, hour: int) -> str:
    """Fetch real-time weather data from Open-Meteo API for a given location and hour.

    Args:
        latitude: Latitude of the location (e.g., 30.27 for Austin, TX)
        longitude: Longitude of the location (e.g., -97.74 for Austin, TX)
        hour: Hour of the day (0-23)

    Returns:
        JSON string with cloud_cover (%), temperature (°C), and uv_index
    """
    cache_key = f"{latitude:.2f},{longitude:.2f}"

    if cache_key not in _weather_cache:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    "https://api.open-meteo.com/v1/forecast",
                    params={
                        "latitude": latitude,
                        "longitude": longitude,
                        "hourly": "temperature_2m,cloud_cover,uv_index",
                        "forecast_days": 1,
                        "timezone": "auto",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                _weather_cache[cache_key] = data["hourly"]
        except Exception as e:
            return json.dumps(
                {
                    "cloud_cover": 40.0,
                    "temperature": 28.0,
                    "uv_index": 5,
                    "source": "FALLBACK — Open-Meteo unavailable",
                    "error": str(e),
                }
            )

    hourly = _weather_cache[cache_key]
    idx = min(hour, len(hourly["temperature_2m"]) - 1)

    cloud = hourly["cloud_cover"][idx]
    temp = hourly["temperature_2m"][idx]
    uv = hourly.get("uv_index", [0] * 24)[idx]

    return json.dumps(
        {
            "cloud_cover": round(cloud if cloud is not None else 50.0, 1),
            "temperature": round(temp if temp is not None else 25.0, 1),
            "uv_index": round(uv if uv is not None else 0, 1),
            "source": "Open-Meteo (LIVE)",
        }
    )


@mcp.tool()
def get_grid_price(hour: int) -> str:
    """Get current grid electricity pricing based on ERCOT (Texas) Time-of-Use rates.

    Args:
        hour: Hour of the day (0-23)

    Returns:
        JSON string with buy_price ($/kWh) and sell_price ($/kWh)
    """
    random.seed(42 + hour)

    if 7 <= hour <= 9 or 17 <= hour <= 21:
        buy = round(random.uniform(0.25, 0.45), 4)
        period = "PEAK"
    elif 10 <= hour <= 16:
        buy = round(random.uniform(0.14, 0.22), 4)
        period = "MID"
    else:
        buy = round(random.uniform(0.08, 0.14), 4)
        period = "OFF_PEAK"

    sell = round(buy * random.uniform(0.45, 0.70), 4)

    return json.dumps(
        {"buy_price": buy, "sell_price": sell, "period": period, "source": "ERCOT TOU Model"}
    )


@mcp.tool()
def get_household_load(hour: int) -> str:
    """Get predicted household electricity consumption based on DOE residential load profiles.

    Args:
        hour: Hour of the day (0-23)

    Returns:
        JSON string with load_kWh (predicted consumption for this hour)
    """
    random.seed(42 + hour * 43)

    if 7 <= hour <= 9:
        load = round(random.uniform(1.5, 2.5), 2)
        pattern = "MORNING_PEAK"
    elif 12 <= hour <= 14:
        load = round(random.uniform(1.0, 2.0), 2)
        pattern = "MIDDAY"
    elif 17 <= hour <= 22:
        load = round(random.uniform(2.0, 3.5), 2)
        pattern = "EVENING_PEAK"
    else:
        load = round(random.uniform(0.3, 0.8), 2)
        pattern = "OVERNIGHT"

    return json.dumps(
        {"load_kWh": load, "pattern": pattern, "source": "DOE Residential Profile"}
    )


@mcp.tool()
def sell_to_grid(amount_kWh: float, sell_price: float) -> str:
    """Execute a sell-to-grid transaction.

    Args:
        amount_kWh: Amount of energy to sell in kWh
        sell_price: Current sell price in $/kWh

    Returns:
        JSON string with confirmation and revenue
    """
    revenue = round(amount_kWh * sell_price, 4)
    return json.dumps({"confirmed": True, "amount_kWh": round(amount_kWh, 4), "revenue": revenue})


@mcp.tool()
def buy_from_grid(amount_kWh: float, buy_price: float) -> str:
    """Execute a buy-from-grid transaction.

    Args:
        amount_kWh: Amount of energy to buy in kWh
        buy_price: Current buy price in $/kWh

    Returns:
        JSON string with confirmation and cost
    """
    cost = round(amount_kWh * buy_price, 4)
    return json.dumps({"confirmed": True, "amount_kWh": round(amount_kWh, 4), "cost": cost})


@mcp.tool()
def charge_battery(amount_kWh: float, current_soc: float) -> str:
    """Charge the battery by a specified amount.

    Args:
        amount_kWh: Amount of energy to store in kWh
        current_soc: Current battery state of charge in kWh

    Returns:
        JSON string with new SOC and actual amount stored
    """
    new_soc = min(current_soc + amount_kWh, BATTERY_CAPACITY_KWH)
    actual = round(new_soc - current_soc, 4)
    return json.dumps({"confirmed": True, "new_soc": round(new_soc, 4), "actual_stored": actual})


@mcp.tool()
def discharge_battery(amount_kWh: float, current_soc: float) -> str:
    """Discharge the battery by a specified amount.

    Args:
        amount_kWh: Amount of energy to discharge in kWh
        current_soc: Current battery state of charge in kWh

    Returns:
        JSON string with new SOC and actual amount discharged
    """
    new_soc = max(current_soc - amount_kWh, BATTERY_MIN_SOC)
    actual = round(current_soc - new_soc, 4)
    return json.dumps({"confirmed": True, "new_soc": round(new_soc, 4), "actual_discharged": actual})


if __name__ == "__main__":
    mcp.run(transport="stdio")
