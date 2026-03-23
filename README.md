# 🌧️ Polymarket Weather Trading Bot

Automated weather arbitrage trading bot for Polymarket prediction markets.

## Features

- ✅ NOAA weather data integration
- ✅ Real-time Polymarket market monitoring
- ✅ Arbitrage opportunity detection
- ✅ Telegram alerts with execute buttons
- ✅ Semi-auto and full-auto modes
- ✅ Risk management system
- ✅ Web dashboard

## Quick Start

1. **Configure credentials:**
```bash
   cp .env.example .env
   nano .env  # Add your credentials
```

2. **Deploy:**
```bash
   docker-compose up -d --build
```

3. **Access:**
   - your own

## Configuration

Edit `.env` file:
- Telegram bot token & chat ID
- Polymarket wallet address & private key
- Risk management parameters

## Architecture
```
Bot runs every 2 hours:
1. Fetch NOAA weather forecasts
2. Fetch Polymarket weather markets
3. Calculate arbitrage opportunities
4. Send Telegram alerts
5. Execute trades (semi-auto: wait for approval)
6. Track positions
7. Report results
```

## Safety

- Start with small capital ($100-500)
- Use semi-auto mode initially
- Monitor daily performance
- Adjust risk parameters as needed

## Development

Built by: Dayo 
Location: Jakarta, Indonesia
Version: 1.0
Date: March 2026
