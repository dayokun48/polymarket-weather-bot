"""
risk_manager.py
================
Validates trades and manages risk limits.

Fixes vs sebelumnya (sesuai schema database):
  - Kolom 'executed' tidak ada di signals → pakai 'status' = 'executed'
  - outcome/pnl ada di tabel 'trades' bukan 'signals'
  - signals punya FK ke markets → market harus ada dulu sebelum insert signal
  - Load today trades dari tabel 'trades' bukan 'signals'
"""

import logging
from datetime import datetime, date, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import config

logger = logging.getLogger(__name__)


class RiskManager:
    """
    Manage trading risks and position sizing.

    Usage:
        calc = ArbitrageCalculator()
        risk = RiskManager(calc)

        is_valid, reason = risk.validate_signal(signal, bankroll)
        if is_valid:
            bet_size = risk.calculate_position_size(signal, bankroll)
            risk.record_trade(signal, bet_size)
    """

    def __init__(self, arbitrage_calculator=None):
        self.calc               = arbitrage_calculator
        self._daily_trades: List[Dict] = []
        self.consecutive_losses = 0
        self.paused             = False
        self._load_today_trades()

    # ── Validation ─────────────────────────────────────────────────────────────

    def validate_signal(self, signal: Dict, bankroll: float,
                        real_balance: float = None) -> Tuple[bool, str]:
        """
        Validasi apakah signal layak untuk ditrading.

        Args:
            signal       : signal dict dari WeatherAnalyzer
            bankroll     : bankroll dari DB (untuk % calculation)
            real_balance : saldo USDC real dari wallet (opsional)
                           jika diisi, cek apakah cukup untuk bet

        Returns (is_valid, reason).
        """
        if self.paused:
            return False, "Bot sedang di-pause"

        min_edge       = config.MIN_EDGE_PCT()
        min_confidence = config.MIN_CONFIDENCE_PCT()
        max_trades     = config.MAX_DAILY_TRADES()
        min_liquidity  = config.MIN_MARKET_LIQUIDITY()
        max_loss_pct   = config.MAX_DAILY_LOSS_PCT()

        if signal.get("edge", 0) < min_edge:
            return False, f"Edge {signal.get('edge', 0):.1f}% di bawah minimum {min_edge}%"

        if signal.get("confidence", 0) < min_confidence:
            return False, f"Confidence {signal.get('confidence', 0):.1f}% di bawah minimum {min_confidence}%"

        if signal.get("market_liquidity", 0) < min_liquidity:
            return False, f"Likuiditas ${signal.get('market_liquidity', 0):,.0f} terlalu rendah"

        today_trades = self._get_today_trades()
        if len(today_trades) >= max_trades:
            return False, f"Batas trade harian tercapai ({max_trades})"

        daily_loss = self._get_daily_loss(today_trades)
        max_loss   = bankroll * max_loss_pct / 100
        if daily_loss >= max_loss:
            return False, f"Batas loss harian tercapai (${daily_loss:.2f} / ${max_loss:.2f})"

        if self.consecutive_losses >= 3:
            return False, "3 loss berturut-turut — auto-pause aktif"

        # FIX 1: Cek saldo real jika tersedia
        if real_balance is not None:
            min_bet = max(config.AUTO_TRADE_AMOUNT() if hasattr(config, 'AUTO_TRADE_AMOUNT') else 5.0, 1.0)
            if real_balance < min_bet:
                return False, f"Saldo real tidak cukup: ${real_balance:.2f} < ${min_bet:.2f}"

        # FIX 2: Cek duplicate — market_id yang sama sudah ada signal pending hari ini
        if self._is_duplicate_signal(signal.get("market_id", "")):
            return False, f"Duplicate signal — market ini sudah ada signal pending hari ini"

        return True, "OK"

    def _is_duplicate_signal(self, market_id: str) -> bool:
        """Cek apakah sudah ada signal pending untuk market_id yang sama hari ini."""
        if not market_id:
            return False
        try:
            conn = self._get_conn()
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT COUNT(*) as cnt FROM signals
                        WHERE market_id = %s
                          AND status = 'pending'
                          AND DATE(created_at) = CURDATE()
                    """, (market_id,))
                    return cur.fetchone()["cnt"] > 0
        except Exception:
            return False

    # ── Position sizing ────────────────────────────────────────────────────────

    def calculate_position_size(self, signal: Dict, bankroll: float) -> float:
        """Hitung ukuran bet menggunakan Kelly via ArbitrageCalculator."""
        if self.calc:
            metrics = self.calc.calculate_all(
                weather_prob = signal.get("weather_prob", 50) / 100,
                market_price = signal.get("current_price", 0.5),
                bankroll     = bankroll,
                direction    = signal.get("direction", "YES"),
            )
            if metrics:
                return metrics["kelly_bet_usd"]

        # Fallback sederhana
        max_bet_pct = config.MAX_BET_PCT() / 100
        confidence  = signal.get("confidence", 60)
        multiplier  = 1.0 if confidence >= 90 else 0.8 if confidence >= 80 else 0.6
        return round(bankroll * max_bet_pct * multiplier, 2)

    # ── Trade recording ────────────────────────────────────────────────────────

    def record_signal(self, signal: Dict, bet_size: float) -> Optional[int]:
        """
        Simpan signal ke tabel signals.
        Harus dipanggil SETELAH market sudah ada di tabel markets.
        Returns signal_id atau None jika gagal.
        """
        try:
            import pymysql
            conn = self._get_conn()
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO signals
                            (market_id, location, target_date, signal_type,
                             direction, noaa_probability, market_probability,
                             edge, confidence, fair_value, expected_value,
                             recommended_bet, reasoning, status, created_at)
                        VALUES
                            (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                             'pending', %s)
                    """, (
                        signal.get("market_id"),
                        signal.get("location"),
                        signal.get("target_date"),
                        signal.get("signal_type"),
                        signal.get("direction"),
                        signal.get("weather_prob"),       # → noaa_probability
                        signal.get("market_prob"),        # → market_probability
                        signal.get("edge"),
                        signal.get("confidence"),
                        signal.get("current_price"),      # → fair_value
                        signal.get("expected_value"),
                        bet_size,                         # → recommended_bet
                        signal.get("reasoning"),
                        datetime.now(timezone.utc),
                    ))
                    signal_id = cur.lastrowid
                conn.commit()
            logger.info(f"📝 Signal #{signal_id} disimpan ke DB")
            return signal_id
        except Exception as e:
            logger.error(f"❌ Gagal simpan signal: {e}")
            return None

    def record_trade(self, signal: Dict, signal_id: int, amount: float,
                     entry_price: float, tx_hash: str = None):
        """
        Simpan eksekusi trade ke tabel trades.
        Update status signal dari 'pending' → 'executed'.
        """
        import uuid
        trade_id = str(uuid.uuid4())[:20]

        trade = {
            "date":       date.today(),
            "market_id":  signal.get("market_id", ""),
            "signal_id":  signal_id,
            "trade_id":   trade_id,
            "direction":  signal.get("direction", ""),
            "amount":     amount,
            "entry_price": entry_price,
            "timestamp":  datetime.now(timezone.utc),
            "outcome":    None,
            "pnl":        None,
        }
        self._daily_trades.append(trade)

        try:
            conn = self._get_conn()
            with conn:
                with conn.cursor() as cur:
                    # Insert ke trades
                    cur.execute("""
                        INSERT INTO trades
                            (trade_id, signal_id, market_id, direction,
                             bet_size, entry_price, executed_at, status, tx_hash)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, 'open', %s)
                    """, (
                        trade_id,
                        signal_id,
                        signal.get("market_id"),
                        signal.get("direction"),
                        amount,
                        entry_price,
                        datetime.now(timezone.utc),
                        tx_hash,
                    ))
                    # Update status signal
                    cur.execute("""
                        UPDATE signals SET status = 'executed'
                        WHERE id = %s
                    """, (signal_id,))
                conn.commit()
            logger.info(f"📝 Trade {trade_id} disimpan, signal #{signal_id} → executed")
        except Exception as e:
            logger.error(f"❌ Gagal simpan trade: {e}")

    def record_outcome(self, trade_id: str, won: bool, payout: float, pnl: float):
        """
        Catat hasil trade (menang/kalah) di tabel trades.
        Update consecutive_losses dan auto-pause jika perlu.
        """
        # Update in-memory
        for t in self._daily_trades:
            if t.get("trade_id") == trade_id:
                t["outcome"] = "win" if won else "loss"
                t["pnl"]     = pnl
                break

        if won:
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1
            if self.consecutive_losses >= 3:
                self.paused = True
                logger.warning("🛑 Auto-pause: 3 loss berturut-turut")

        try:
            conn = self._get_conn()
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE trades
                        SET outcome = %s, payout = %s, realized_pnl = %s,
                            status = 'closed', closed_at = %s
                        WHERE trade_id = %s
                    """, (
                        "win" if won else "loss",
                        payout,
                        pnl,
                        datetime.now(timezone.utc),
                        trade_id,
                    ))
                conn.commit()
        except Exception as e:
            logger.error(f"❌ Gagal update outcome: {e}")

    # ── Stats ──────────────────────────────────────────────────────────────────

    def get_daily_stats(self) -> Dict:
        today_trades = self._get_today_trades()
        max_trades   = config.MAX_DAILY_TRADES()
        daily_loss   = self._get_daily_loss(today_trades)
        daily_pnl    = sum(t.get("pnl", 0) or 0 for t in today_trades)

        return {
            "trades_today":       len(today_trades),
            "trades_remaining":   max(0, max_trades - len(today_trades)),
            "total_exposure":     sum(t["amount"] for t in today_trades),
            "daily_pnl":          round(daily_pnl, 2),
            "daily_loss":         round(daily_loss, 2),
            "consecutive_losses": self.consecutive_losses,
            "paused":             self.paused,
        }

    # ── Controls ───────────────────────────────────────────────────────────────

    def unpause(self):
        self.paused             = False
        self.consecutive_losses = 0
        logger.info("✅ Bot di-unpause")

    def reset_daily_limits(self):
        cutoff = date.today() - timedelta(days=7)
        self._daily_trades = [t for t in self._daily_trades if t["date"] >= cutoff]

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _get_today_trades(self) -> List[Dict]:
        return [t for t in self._daily_trades if t["date"] == date.today()]

    def _get_daily_loss(self, today_trades: List[Dict]) -> float:
        return sum(
            abs(t.get("pnl", 0) or 0)
            for t in today_trades
            if t.get("outcome") == "loss"
        )

    def _get_conn(self):
        import pymysql
        return pymysql.connect(
            host=config.DB_HOST, port=config.DB_PORT,
            user=config.DB_USER, password=config.DB_PASSWORD,
            database=config.DB_NAME,
            charset="utf8mb4",
            connect_timeout=5,
        )

    def _load_today_trades(self):
        """Load trade hari ini dari tabel trades saat startup."""
        try:
            conn = self._get_conn()
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT trade_id, market_id, direction, bet_size as amount,
                               outcome, realized_pnl as pnl, executed_at
                        FROM trades
                        WHERE DATE(executed_at) = CURDATE()
                    """)
                    for r in cur.fetchall():
                        self._daily_trades.append({
                            "date":      date.today(),
                            "trade_id":  r[0],
                            "market_id": r[1],
                            "direction": r[2],
                            "amount":    float(r[3] or 0),
                            "outcome":   r[4],
                            "pnl":       float(r[5] or 0) if r[5] else None,
                            "timestamp": r[6],
                        })
            logger.info(f"📂 Loaded {len(self._daily_trades)} trade dari DB")
        except Exception as e:
            logger.warning(f"⚠️  Tidak bisa load trade dari DB: {e}")