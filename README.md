# 🌧️ POLYMARKET WEATHER TRADING BOT

> Automated trading bot for Polymarket weather bracket markets using Volume Distribution Strategy

[![Status](https://img.shields.io/badge/status-production%20ready-brightgreen)]()
[![Python](https://img.shields.io/badge/python-3.8+-blue)]()
[![Version](https://img.shields.io/badge/version-3.0-orange)]()

---

## 📊 What Is This?

Automated trading bot for Polymarket weather bracket markets. Uses **Volume Distribution Analysis** instead of weather forecast APIs (which have ±3-5°C error — too imprecise for 1°C bracket markets).

**Two core strategies:**

1. **🆕 Fresh Market** — When a new bracket market opens (~17:00 WIB), all brackets are ~50¢. Bot auto BUY NO all brackets before other traders flood them to 99.9¢.

2. **📊 Pre-Closing Volume** — 4 hours before market closes, bot analyzes volume distribution per bracket. Bracket with highest volume = market consensus. If still underpriced → Telegram alert with EXECUTE/SKIP button.

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
/status   — bot status, balance, signals hari ini
/signals  — 5 signal terbaru
/balance  — saldo USDC wallet
/scan     — trigger manual pre-closing scan
/pause    — pause bot
/unpause  — resume bot
/help     — semua commands
```

---

## 🎯 How It Works

### Strategy 1: Fresh Market (~17:00 WIB setiap hari)
```
Market baru buka → semua brackets ~50¢
        ↓
Bot detect via slug: highest-temperature-in-{city}-on-{month}-{day}-{year}
Scan 30 kota setiap 5 menit
        ↓
Auto BUY NO semua brackets @ $1
Auto BUY YES predicted winner @ $2
        ↓
9/10 brackets menang → payout ~2x
Net profit: ~$9 dari $10 modal
        ↓
Alert Telegram: "⚡ EXECUTED FRESH MARKET"
```

### Strategy 2: Pre-Closing Volume (13:00 & 15:00 WIB)
```
4 jam sebelum closing (market tutup 19:00 WIB)
        ↓
VolumeAnalyzer ambil volume per bracket
        ↓
Bracket volume terbesar = market consensus
        ↓
Hitung edge: vol_share% vs YES price
        ↓
conf ≥ 90% → auto-execute $5
conf 70-89% → alert Telegram EXECUTE/SKIP
        ↓
User klik EXECUTE → bot tanya jumlah → eksekusi
```
---

## 🔑 CLOB Authentication

| Level | Method | Used For |
|-------|--------|---------|
| L1 | Private Key (EIP-712) | Sign orders |
| L2 | API Key (HMAC-SHA256) | Place/cancel orders |

**Wallet type:** Gnosis Safe (`signature_type=2`)

---

## 📊 Why Volume Distribution?

| Source | Error D-1 | Akurat untuk 1°C bracket? |
|--------|-----------|--------------------------|
| ECMWF | ±3-4°C | ❌ Tidak |
| GFS | ±3-5°C | ❌ Tidak |
| Volume Distribution | — | ✅ Ya |

---

## 🏗️ Architecture

```
app.py (Main Process)
├── Fresh Market Monitor  (setiap 5 menit)      → auto BUY NO @ ~50¢
├── Pre-Closing Scanner   (06:00 & 08:00 UTC)   → volume signal
├── Market DB Sync        (setiap 60 menit)      → update DB
├── Telegram Handler      (background daemon)    → polling + commands
├── Flask Dashboard       (port 5000)            → web UI
└── APScheduler           (background)           → job scheduling
```
---

**Developer:** Dayo | 
**Version:** 3.0 | March 2026 | 
