# ⚡ Smart Grid Energy Arbitrage Agent — GridMind

> An advanced multi-step reasoning LLM agent that manages a residential microgrid using **MCP (Model Context Protocol)**, **Google Gemini Flash**, and **real-time weather data** — performing energy arbitrage through mathematical optimization and structured decision-making across a 24-hour cycle.

---

## 📋 Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [How Multi-Step Mathematical Reasoning Works](#how-multi-step-mathematical-reasoning-works)
- [Real-Time Data Sources](#real-time-data-sources)
- [Tools \& MCP Surface](#tools--mcp-surface)
- [Getting Started](#getting-started)
- [Project Structure](#project-structure)
- [Prompt Evaluation Against the 9-Point Rubric](#prompt-evaluation-against-the-9-point-rubric)
- [Sample Output](#sample-output)
- [Demo Video](#demo-video)
- [License](#license)

---

## Overview

**GridMind** is not a summarizer or a chatbot — it is a *reasoning engine* that solves a constrained optimization problem every hour:

> *Given current weather, household load, battery state, and dynamic grid pricing, what is the mathematically optimal allocation of solar energy across storage, consumption, and grid trading?*

The agent uses **MCP (Model Context Protocol)** to connect to real tools and **Google Gemini Flash** as the LLM brain. It runs a **24-turn conversation loop** where each turn represents one hour. At every step, it:

1. Gathers real-time data via MCP tool calls (live weather, pricing, load)
2. Performs multi-step arithmetic (solar generation with temperature derating)
3. Applies rule-based optimization logic (threshold comparisons, peak shaving)
4. Verifies energy conservation (self-check equation)
5. Outputs a structured JSON decision with full reasoning trace

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   AGENT CLIENT (agent.py)                    │
│                                                             │
│  🤖 Google Gemini Flash (LLM)                               │
│  ┌──────────┐    ┌──────────────┐    ┌─────────────────┐   │
│  │  State    │───▶│  Gemini API  │───▶│  JSON Response  │   │
│  │  Object   │    │  + Tools     │    │  + Reasoning    │   │
│  └──────────┘    └──────┬───────┘    └────────┬────────┘   │
│       ▲                 │ function_call        │            │
│       │                 ▼                      │            │
│  ┌────┴─────┐    ┌──────────────┐             │            │
│  │  State   │    │  MCP Client  │◀────────────┘            │
│  │  Update  │    │  (stdio)     │                          │
│  └──────────┘    └──────┬───────┘                          │
│                         │                                   │
└─────────────────────────┼───────────────────────────────────┘
                          │ stdin/stdout
┌─────────────────────────▼───────────────────────────────────┐
│                MCP SERVER (mcp_server.py)                    │
│                     FastMCP                                  │
│                                                             │
│  🌤️  fetch_weather ──────── Open-Meteo API (LIVE, FREE)     │
│  💰 get_grid_price ──────── ERCOT TOU Rate Model            │
│  🏠 get_household_load ──── DOE Residential Profile         │
│  🔋 charge_battery ──────── Local State Calculation         │
│  🔋 discharge_battery ───── Local State Calculation         │
│  💵 sell_to_grid ─────────── Transaction Calculator         │
│  💵 buy_from_grid ────────── Transaction Calculator         │
└─────────────────────────────────────────────────────────────┘
```

---

## How Multi-Step Mathematical Reasoning Works

Each hourly decision follows a mandatory **6-step reasoning chain**:

### Step A → `[API_CALL]` — Data Gathering
The agent invokes three MCP tools to collect the current hour's data: **live weather** conditions from Open-Meteo, grid pricing, and household electricity demand.

### Step B → `[MATH]` — Solar Generation Calculation
```
solar_output = 10 kW × (1 - cloud_cover/100) × 0.18 × 1 hour
```
A temperature derating factor is applied: for every degree above 25°C, output drops by 0.4%.

### Step C → `[MATH]` — Energy Balance
```
net_energy = solar_output - household_load
```
Positive = surplus (store or sell). Negative = deficit (discharge battery or buy).

### Step D → `[LOGIC]` — Decision Optimization
A rule-based optimizer applies threshold logic:
- **Surplus + high sell price + battery above 80%** → SELL to grid
- **Surplus + battery below 80%** → STORE in battery
- **Deficit + cheap grid price** → BUY from grid
- **Deficit + peak pricing** → DISCHARGE battery (peak shaving)

### Step E → `[VERIFY]` — Energy Conservation Self-Check
```
energy_used + energy_stored + energy_sold = solar_output + energy_bought + energy_discharged
```
Both sides must balance within ±0.01 kWh. If they don't, the agent re-examines its math.

### Step F → `[STATE_UPDATE]` — Battery SOC Update
The new battery state of charge is computed and clamped to [0, 13.5] kWh.

---

## Real-Time Data Sources

| Data | Source | Type | Cost |
|------|--------|------|------|
| **Weather** | [Open-Meteo API](https://open-meteo.com/) | Live forecast (cloud cover, temperature, UV index) | **Free**, no API key |
| **Grid Pricing** | ERCOT TOU Rate Model | Realistic Time-of-Use pricing (off-peak $0.08–0.12, mid $0.14–0.22, peak $0.25–0.45) | Simulated |
| **Household Load** | DOE Residential Profile | Realistic consumption curve by time of day | Simulated |
| **LLM Reasoning** | [Google Gemini Flash](https://ai.google.dev/) | Multi-step reasoning + tool calling | Free tier available |

---

## Tools & MCP Surface

All tools are exposed via **MCP (Model Context Protocol)** using FastMCP:

| Tool                 | Input                             | Output                                      |
|----------------------|-----------------------------------|---------------------------------------------|
| `fetch_weather`      | latitude, longitude, hour         | cloud_cover, temperature, uv_index (LIVE)   |
| `get_grid_price`     | hour                              | buy_price, sell_price ($/kWh)               |
| `get_household_load` | hour                              | load_kWh                                    |
| `sell_to_grid`       | amount_kWh, sell_price            | confirmed, revenue                          |
| `buy_from_grid`      | amount_kWh, buy_price             | confirmed, cost                             |
| `charge_battery`     | amount_kWh, current_soc           | confirmed, new_soc                          |
| `discharge_battery`  | amount_kWh, current_soc           | confirmed, new_soc                          |

All tools have **documented fallback defaults** if they fail (e.g., historical average weather).

---

## Getting Started

### Prerequisites
- Python 3.10+
- A Google API key (free from [Google AI Studio](https://aistudio.google.com/apikey))

### Installation & Running

```bash
# Clone the repository
git clone https://github.com/your-username/smart-grid-agent.git
cd smart-grid-agent

# Set up virtual environment and install dependencies (requires Python 3.10+)
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Set up your API key
cp .env.example .env
# Edit .env and add your GOOGLE_API_KEY

# Run the full 24-hour simulation (MCP + Gemini)
python agent.py

# Or run a shorter test (e.g., 3 hours)
python agent.py --hours 3

# Offline mode (no API key needed, uses mock LLM)
python main.py
```

### Output
- **Terminal**: Hour-by-hour reasoning trace with real-time MCP tool calls
- **File**: `agent_trace.json` — full structured trace of all hourly decisions + daily summary

---

## Project Structure

```
smart-grid-agent/
├── agent.py               # 🤖 MCP + Gemini agent loop (main entry point)
├── mcp_server.py          # 🔌 MCP server with real tools (FastMCP)
├── main.py                # 📴 Offline mock version (no API key needed)
├── system_prompt.md       # 📝 Master system prompt for the LLM agent
├── evaluation.json        # ✅ 9-point rubric evaluation results
├── requirements.txt       # 📦 Python dependencies
├── .env.example           # 🔑 Environment variable template
├── README.md              # 📖 This file
└── agent_trace.json       # 📊 Generated after running (24-hour trace)
```

---

## Prompt Evaluation Against the 9-Point Rubric

The system prompt was evaluated by an AI assistant against the assignment's 9-point rubric:

| #  | Criterion                    | Pass | How It's Addressed                                                                                      |
|----|------------------------------|------|---------------------------------------------------------------------------------------------------------|
| 1  | Explicit Reasoning           | ✅   | Mandatory 6-step chain (A→F) must be executed before any output                                         |
| 2  | Structured Output            | ✅   | Strict JSON schema with `reasoning_trace`, `actions`, `new_state`, `fallbacks_used`                     |
| 3  | Tool Separation              | ✅   | Tools exposed via MCP with exact signatures; native function calling separate from reasoning             |
| 4  | Conversation Loop            | ✅   | State object flows between turns; 24-hour multi-turn design with history accumulation                   |
| 5  | Instructional Framing        | ✅   | Complete worked example for Hour 10 with input state and expected JSON output                           |
| 6  | Internal Self-Checks         | ✅   | Step E mandates energy conservation equation verification with ±0.01 kWh tolerance                     |
| 7  | Reasoning Type Awareness     | ✅   | Every step tagged: `[MATH]`, `[LOGIC]`, `[API_CALL]`, `[VERIFY]`, `[STATE_UPDATE]`, `[FALLBACK]`      |
| 8  | Error Handling / Fallbacks   | ✅   | Full fallback table for every tool with historical defaults; retry logic for transactional tools         |
| 9  | Overall Clarity              | ✅   | Hallucination-resistant design; forbids invented data; anchors decisions to tool-returned values         |

See `evaluation.json` for the machine-readable assessment.

---

## Sample Output

```
======================================================================
  ⚡ SMART GRID ENERGY ARBITRAGE AGENT — GridMind
  🤖 LLM: Google Gemini Flash  |  🔌 Tools: MCP Protocol
  🌤️  Weather: Open-Meteo (LIVE)  |  💰 Pricing: ERCOT TOU
======================================================================

  ✅ MCP Server connected. Discovering tools...
  📋 Tools available: fetch_weather, get_grid_price, get_household_load, ...

────────────────────────────────────────────────────────────
  ⏰ HOUR 10:00
────────────────────────────────────────────────────────────
    🔧 MCP Tool: fetch_weather({"latitude": 30.27, "longitude": -97.74, "hour": 10})
    🔧 MCP Tool: get_grid_price({"hour": 10})
    🔧 MCP Tool: get_household_load({"hour": 10})
  [API_CALL]       Fetched LIVE weather, grid price, and household load for hour 10.
  [MATH]           solar_output = 10 × (1 - 23.5/100) × 0.18 × 1 = 1.377 kWh. Temp derate: 31°C
  [MATH]           net_energy = 1.34 - 1.85 = -0.51 kWh. Deficit of 0.51 kWh.
  [LOGIC]          buy_price $0.17 ≤ $0.20 → BUY 0.51 kWh.
  [VERIFY]         ✓ LHS=1.85 RHS=1.85
  Actions          USE 1.34 kWh | BUY 0.51 kWh
  State            SOC=8.20 kWh (61%) | Rev=$0.3200 | Cost=$1.4503
```

---

## Demo Video

🎬 **Watch the demo**: [YouTube Link](https://youtu.be/fcVe9p9ZnV4)

---

## License

MIT License — see [LICENSE](LICENSE) for details.
