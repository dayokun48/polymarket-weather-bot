# 🌧️ POLYMARKET WEATHER TRADING BOT

> Automated trading bot for Polymarket weather bracket markets using Volume Distribution Strategy

[![Status](https://img.shields.io/badge/status-production%20ready-brightgreen)]()
[![Python](https://img.shields.io/badge/python-3.8+-blue)]()
[![Strategy](https://img.shields.io/badge/strategy-volume%20distribution-orange)]()

---

## 📊 What Is This?

Automated trading bot for Polymarket weather bracket markets. Uses **Volume Distribution Analysis** instead of weather forecast APIs (which have ±3-5°C error — too imprecise for 1°C bracket markets).

**Two core strategies:**

1. **🆕 Fresh Market** — When a new bracket market opens (~17:00 WIB), all brackets are ~50¢. Bot auto BUY NO all brackets before other traders flood them to 99.9¢.

2. **📊 Pre-Closing Volume** — 4 hours before market closes, bot analyzes volume distribution per bracket. Bracket with highest volume = market consensus. If still underpriced → send Telegram alert with EXECUTE/SKIP button.

---

## ✨ Key Features

- 🆕 **Fresh Market Auto-Execute** — BUY NO all brackets at ~50¢ before NO flood
- 📊 **Volume Distribution Analysis** — Market intelligence > weather forecast
- ⚡ **Auto-Trade** — confidence ≥ 90% → execute $5 automatically
- 🤖 **Telegram Integration** — alerts with EXECUTE/SKIP buttons + /commands
- 🌐 **Web Dashboard** — Bloomberg dark theme at http://localhost:5000
- 💰 **Real Trading** — py-clob-client SDK via Polymarket CLOB API

---

---

## 📱 Telegram Commands

```
/status   — bot status, today's trades, P&L, balance
/signals  — 5 latest signals
/balance  — USDC wallet balance
/scan     — trigger manual pre-closing scan
/pause    — pause bot
/unpause  — resume bot
/help     — all commands
```

---

## 🎯 How It Works

### Strategy 1: Fresh Market (~17:00 WIB daily)
```
New bracket market opens → all brackets ~50¢
        ↓
Fresh Market Scanner detects (every 10 min)
        ↓
Bot auto BUY NO all brackets @ $1
Bot BUY YES predicted winner @ $2 (volume hint)
        ↓
9/10 brackets win → payout ~2x each
Net profit: ~$9 from $10 investment
        ↓
Alert: "⚡ EXECUTED FRESH MARKET — total $9"
```

### Strategy 2: Pre-Closing Volume (06:00 & 08:00 UTC)
```
4 hours before closing (market closes 12:00 UTC / 19:00 WIB)
        ↓
VolumeAnalyzer fetches volume per bracket
        ↓
Bracket with highest volume = market consensus
        ↓
Calculate edge: vol_share% vs YES price
        ↓
confidence ≥ 90% → auto-execute $5
confidence 70-89% → Telegram alert with EXECUTE/SKIP
        ↓
User clicks EXECUTE → bot asks bet amount → executes
```

---

---

## ⏰ Scheduler Overview

| Job | Trigger | Purpose |
|-----|---------|---------|
| Fresh Market Scan | Every 10 min | Detect new bracket markets |
| Pre-Closing Scan | 06:00 & 08:00 UTC | Volume distribution analysis |
| Daily Reset | 00:00 UTC | Reset limits, save performance |

---

## ⚙️ Bot Settings (via Dashboard)

| Setting | Default | Description |
|---------|---------|-------------|
| `automation_mode` | semi-auto | manual / semi-auto / full-auto |
| `bankroll` | 1000 | Total trading capital ($) |
| `max_bet_pct` | 5 | Max % of bankroll per trade |
| `auto_trade_threshold` | 90 | Confidence % for auto-execute |
| `auto_trade_amount` | 5 | Auto-trade bet size ($) |
| `fresh_market_window_minutes` | 5 | Fresh market detection window |
| `fresh_market_auto_bet` | 1 | Bet per bracket for fresh market ($) |
| `fresh_market_scan_interval` | 10 | Scan frequency (minutes) |
| `pre_closing_hours` | 4 | Hours before close to scan |
| `min_volume_signal` | 1000 | Min total volume for signal ($) |
| `volume_edge_threshold` | 20 | Min edge % from volume distribution |

---

## 🔑 CLOB Authentication

Polymarket uses 2-level auth:

| Level | Method | Used For |
|-------|--------|---------|
| L1 | Private Key (EIP-712) | Sign orders |
| L2 | API Key (HMAC-SHA256) | Place/cancel orders |

**Wallet type:** Gnosis Safe (`signature_type=2`) — used by most Polymarket accounts.

## 🏗️ Architecture

```
app.py (Main Process)
├── Fresh Market Monitor (every 10 min)     → auto BUY NO @ ~50¢
├── Pre-Closing Scanner (06:00 & 08:00 UTC) → volume signal analysis
├── Telegram Handler (background daemon)   → polling callbacks + commands
├── Flask Dashboard (port 5000)            → web UI
└── APScheduler (background)               → job scheduling
```

---
**Developer:** Dayo | Jakarta, Indonesia
**Version:** 3.0 | March 2026 | 
