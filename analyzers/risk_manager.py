"""
risk_manager.py
================
Simplified — hanya validasi trade dan simpan signal ke DB.
Tidak lagi track trades (ada di Polymarket web).
DB hanya: bot_settings + signals
"""

import logging
from datetime import datetime, date, timezone
from typing import Dict, List, Optional, Tuple

import config

logger = logging.getLogger(__name__)


class RiskManager:

    def __init__(self, arbitrage_calculator=None):
        self.paused             = False
        self.consecutive_losses = 0
        self._signals_today     = 0
        self._load_today_count()

    def _load_today_count(self):
        try:
            conn = self._get_conn()
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT COUNT(*) as cnt FROM signals WHERE DATE(created_at) = CURDATE()"
                    )
                    self._signals_today = cur.fetchone()["cnt"]
        except Exception:
            self._signals_today = 0

    # ── Validation ────────────────────────────────────────────────────────────

    def validate_signal(self, signal: Dict, bankroll: float,
                        real_balance: float = None) -> Tuple[bool, str]:
        if self.paused:
            return False, "Bot sedang di-pause"

        if self.consecutive_losses >= 3:
            return False, "3 loss berturut-turut — auto-pause aktif"

        max_trades = config.MAX_DAILY_TRADES()
        if self._signals_today >= max_trades:
            return False, f"Batas signal harian tercapai ({max_trades})"

        # Cek saldo real
        if real_balance is not None:
            signal_type = signal.get("signal_type", "")
            min_bet = (config.FRESH_MARKET_AUTO_BET()
                       if "fresh_market" in signal_type
                       else config.AUTO_TRADE_AMOUNT())
            min_bet = max(min_bet, 1.0)
            if real_balance < min_bet:
                return False, f"Saldo real tidak cukup: ${real_balance:.2f} < ${min_bet:.2f}"

        # Cek duplicate
        if self._is_duplicate_signal(signal.get("market_id", "")):
            return False, "Duplicate signal — market ini sudah ada signal pending hari ini"

        return True, "OK"

    def _is_duplicate_signal(self, market_id: str) -> bool:
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

    # ── Position sizing ───────────────────────────────────────────────────────

    def calculate_position_size(self, signal: Dict, bankroll: float) -> float:
        max_bet_pct = config.MAX_BET_PCT() / 100
        confidence  = signal.get("confidence", 70)
        multiplier  = 1.0 if confidence >= 90 else 0.8 if confidence >= 80 else 0.6
        return round(bankroll * max_bet_pct * multiplier, 2)

    # ── Signal recording ──────────────────────────────────────────────────────

    def record_signal(self, signal: Dict, bet_size: float) -> Optional[int]:
        """Simpan signal ke DB. Returns signal_id atau None."""
        try:
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
                            (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending',%s)
                    """, (
                        signal.get("market_id"),
                        signal.get("location"),
                        signal.get("target_date"),
                        signal.get("signal_type"),
                        signal.get("direction"),
                        signal.get("noaa_probability"),
                        signal.get("market_probability"),
                        signal.get("edge"),
                        signal.get("confidence"),
                        signal.get("fair_value"),
                        signal.get("expected_value"),
                        bet_size,
                        signal.get("reasoning"),
                        datetime.now(timezone.utc),
                    ))
                    signal_id = cur.lastrowid
                conn.commit()
            self._signals_today += 1
            logger.info(f"📝 Signal #{signal_id} disimpan")
            return signal_id
        except Exception as e:
            logger.error(f"record_signal error: {e}")
            return None

    def update_signal_status(self, signal_id: int, status: str):
        """Update status signal: pending → executed/skipped."""
        try:
            conn = self._get_conn()
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE signals SET status=%s WHERE id=%s",
                        (status, signal_id)
                    )
                conn.commit()
        except Exception as e:
            logger.error(f"update_signal_status error: {e}")

    # ── Daily stats ───────────────────────────────────────────────────────────

    def get_daily_stats(self) -> Dict:
        try:
            conn = self._get_conn()
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT
                            COUNT(*) as total,
                            SUM(status='executed') as executed,
                            SUM(status='pending') as pending,
                            SUM(status='skipped') as skipped,
                            AVG(edge) as avg_edge,
                            AVG(confidence) as avg_conf
                        FROM signals WHERE DATE(created_at) = CURDATE()
                    """)
                    return cur.fetchone() or {}
        except Exception:
            return {}

    def reset_daily_limits(self):
        self._signals_today = 0
        self.consecutive_losses = 0
        logger.info("🔄 Daily limits reset")

    # ── DB helper ─────────────────────────────────────────────────────────────

    def _get_conn(self):
        import pymysql
        return pymysql.connect(
            host=config.DB_HOST, port=config.DB_PORT,
            user=config.DB_USER, password=config.DB_PASSWORD,
            database=config.DB_NAME, charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor, connect_timeout=5,
        )