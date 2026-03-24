# 🌧️ Polymarket Weather Trading Bot

Automated weather arbitrage trading bot for Polymarket prediction markets.
Detects timing delays between weather API updates and market odds for asymmetric payoffs.

---

## ✨ Features

- ✅ Multi-source weather data (NOAA for US, Open-Meteo global, Wunderground verification)
- ✅ Keyword-based market filtering (tag=weather API confirmed broken — fixed)
- ✅ Temperature probability with bracket formula (realistic, not gaussian peak)
- ✅ Arbitrage opportunity detection with Kelly Criterion position sizing
- ✅ Telegram alerts with EXECUTE / SKIP buttons
- ✅ Semi-auto and full-auto trading modes
- ✅ Risk management (daily loss limit, consecutive loss auto-pause)
- ✅ Web dashboard (markets, signals, positions, performance, settings)
- ✅ MySQL database with 6-table schema
- ✅ Hot-reload settings via phpMyAdmin (no restart needed)

---

## 🌤️ Weather API Strategy

| Source | Coverage | Usage |
|--------|----------|-------|
| **NOAA** | US only | Primary for US cities (official, accurate) |
| **Open-Meteo** | Global | Primary for non-US, fallback for US |
| **Wunderground** | Global | Resolution verification only |

Note: Polymarket `tag=weather` API confirmed broken (returns random markets).
Bot fetches all active markets and filters by weather keywords with word-boundary regex.

---

## 🛡️ Safety

- Mulai dengan modal kecil ($100–500) dan mode `semi-auto`
- Setiap signal butuh approval via Telegram sebelum dieksekusi
- Auto-pause setelah 3 loss berturut-turut
- Daily loss limit otomatis menghentikan trading
- Semua trade tersimpan ke database untuk audit

---

## 📁 Key Files

```
app.py                    ← Main application (start here)
check_system.py           ← Pre-flight check (run before app.py)
requirements.txt          ← Dependencies
.env                      ← Credentials (jangan di-commit ke git)
```

---

## 🔧 Development

**Built by:** Dayo 
**Version:** 2.0  
**Date:** March 2026  
**Stack:** Python 3.12 · Flask · MySQL · APScheduler · Telegram Bot API
