"""
position_tracker.py
====================
Tracks open positions and calculates P&L.

Fixes dari original:
  - Semua in-memory → data hilang saat restart. Sekarang load dari tabel trades
  - outcome 'WIN'/'LOSS' uppercase → schema pakai 'win'/'loss' lowercase
  - close_position tidak update DB → sekarang update tabel trades
  - datetime.utcnow() deprecated → datetime.now(timezone.utc)
  - trade['x'] tanpa .get() → crash jika field tidak ada
  - Tabel daily_performance tidak pernah diisi → save_daily_performance()
"""

import logging
from datetime import datetime, date, timezone
from typing import Dict, List, Optional

import config

logger = logging.getLogger(__name__)


class PositionTracker:
    """
    Track open trading positions.
    Sumber data utama: tabel trades di database.
    In-memory cache untuk akses cepat, di-sync dengan DB saat startup.
    """

    def __init__(self):
        self.open_positions:   List[Dict] = []
        self.closed_positions: List[Dict] = []
        self.total_invested = 0.0
        self.total_returned = 0.0
        self._load_positions_from_db()

    # ── Add position ───────────────────────────────────────────────────────────

    def add_position(self, trade: Dict):
        """
        Tambah posisi baru dari trade_result.
        trade dict harus berisi field yang sama dengan trade_result
        dari polymarket_trader.execute_trade().
        """
        position = {
            "position_id":     trade.get("trade_id", ""),
            "signal_id":       trade.get("signal_id"),
            "market_id":       trade.get("market_id", ""),
            "market_question": trade.get("market_question", ""),
            "direction":       trade.get("direction", ""),
            "entry_price":     trade.get("entry_price", 0),
            "shares":          trade.get("shares", 0),
            "amount_invested": trade.get("bet_size", 0),
            "opened_at":       trade.get("executed_at", datetime.now(timezone.utc)),
            "status":          "open",
            "current_price":   trade.get("entry_price", 0),
            "unrealized_pnl":  0.0,
        }

        self.open_positions.append(position)
        self.total_invested += position["amount_invested"]

        logger.info(f"📊 Posisi ditambah: {position['position_id'][:20]}")
        logger.info(f"   Market   : {position['market_question'][:50]}")
        logger.info(f"   Invested : ${position['amount_invested']:.2f}")

    # ── Update price ───────────────────────────────────────────────────────────

    def update_position_price(self, position_id: str, current_price: float):
        """Update harga terkini dan hitung unrealized P&L."""
        for pos in self.open_positions:
            if pos["position_id"] == position_id:
                pos["current_price"] = current_price
                current_value        = pos["shares"] * current_price
                pos["unrealized_pnl"] = current_value - pos["amount_invested"]
                logger.debug(
                    f"Updated {position_id[:10]}: "
                    f"price={current_price:.4f} "
                    f"pnl=${pos['unrealized_pnl']:.2f}"
                )
                break

    # ── Close position ─────────────────────────────────────────────────────────

    def close_position(
        self,
        position_id: str,
        outcome: str,           # FIX: pakai 'win'/'loss' lowercase sesuai schema
        final_price: float = None,
    ) -> Optional[Dict]:
        """
        Tutup posisi dan hitung realized P&L.
        Update tabel trades di database.

        Args:
            position_id : trade_id dari posisi
            outcome     : 'win' atau 'loss' (lowercase, sesuai schema)
            final_price : harga final saat settlement
        """
        # FIX: normalize ke lowercase sesuai schema
        outcome = outcome.lower()
        if outcome not in ("win", "loss"):
            logger.error(f"outcome harus 'win' atau 'loss', dapat: '{outcome}'")
            return None

        position = None
        for i, pos in enumerate(self.open_positions):
            if pos["position_id"] == position_id:
                position = self.open_positions.pop(i)
                break

        if not position:
            logger.error(f"Posisi {position_id} tidak ditemukan")
            return None

        # Hitung payout
        # Winning shares pay $1 each, losing shares pay $0
        payout       = position["shares"] * 1.0 if outcome == "win" else 0.0
        realized_pnl = payout - position["amount_invested"]

        # Update position dict
        position.update({
            "status":       "closed",
            "outcome":      outcome,
            "closed_at":    datetime.now(timezone.utc),   # FIX: timezone.utc
            "payout":       payout,
            "realized_pnl": realized_pnl,
            "current_price": final_price or position["current_price"],
        })

        self.closed_positions.append(position)
        self.total_returned += payout

        # Update database
        self._update_trade_in_db(position)

        logger.info("=" * 55)
        logger.info("🔒 POSISI DITUTUP")
        logger.info(f"   Market  : {position['market_question'][:50]}")
        logger.info(f"   Outcome : {outcome.upper()}")
        logger.info(f"   Invested: ${position['amount_invested']:.2f}")
        logger.info(f"   Payout  : ${payout:.2f}")
        logger.info(f"   P&L     : ${realized_pnl:+.2f}")
        logger.info("=" * 55)

        return position

    # ── Getters ────────────────────────────────────────────────────────────────

    def get_open_positions(self) -> List[Dict]:
        return self.open_positions.copy()

    def get_position_by_id(self, position_id: str) -> Optional[Dict]:
        for pos in self.open_positions:
            if pos["position_id"] == position_id:
                return pos.copy()
        return None

    def get_total_exposure(self) -> float:
        return sum(p["amount_invested"] for p in self.open_positions)

    def get_unrealized_pnl(self) -> float:
        return sum(p.get("unrealized_pnl", 0) for p in self.open_positions)

    def get_realized_pnl(self) -> float:
        return sum(p.get("realized_pnl", 0) for p in self.closed_positions)

    def get_total_pnl(self) -> float:
        return self.get_realized_pnl() + self.get_unrealized_pnl()

    # ── Performance stats ──────────────────────────────────────────────────────

    def get_performance_stats(self) -> Dict:
        """Statistik performa keseluruhan (gabungan DB + in-memory)."""
        total_closed = len(self.closed_positions)
        wins         = sum(1 for p in self.closed_positions if p.get("outcome") == "win")
        losses       = total_closed - wins
        win_rate     = (wins / total_closed * 100) if total_closed > 0 else 0.0

        realized_pnl   = self.get_realized_pnl()
        unrealized_pnl = self.get_unrealized_pnl()
        total_pnl      = realized_pnl + unrealized_pnl
        roi            = (total_pnl / self.total_invested * 100) if self.total_invested > 0 else 0.0

        return {
            "total_trades":   total_closed,
            "wins":           wins,
            "losses":         losses,
            "win_rate":       round(win_rate, 1),
            "total_invested": round(self.total_invested, 2),
            "total_returned": round(self.total_returned, 2),
            "realized_pnl":   round(realized_pnl, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "total_pnl":      round(total_pnl, 2),
            "roi":            round(roi, 1),
            "open_positions": len(self.open_positions),
            "total_exposure": round(self.get_total_exposure(), 2),
        }

    def get_summary(self) -> str:
        """Ringkasan performa sebagai teks."""
        s = self.get_performance_stats()
        return f"""
📊 POSITION TRACKER SUMMARY

Open Positions : {s['open_positions']}
Total Exposure : ${s['total_exposure']:.2f}
Unrealized P&L : ${s['unrealized_pnl']:+.2f}

Closed Trades  : {s['total_trades']}
Wins / Losses  : {s['wins']} / {s['losses']}
Win Rate       : {s['win_rate']:.1f}%

Total Invested : ${s['total_invested']:.2f}
Total Returned : ${s['total_returned']:.2f}
Realized P&L   : ${s['realized_pnl']:+.2f}

TOTAL P&L      : ${s['total_pnl']:+.2f}
ROI            : {s['roi']:+.1f}%
""".strip()

    # ── Daily performance ──────────────────────────────────────────────────────

    def save_daily_performance(self, target_date: date = None):
        """
        Simpan/update ringkasan performa harian ke tabel daily_performance.
        Panggil di akhir hari atau saat bot shutdown.
        """
        target_date = target_date or date.today()

        # Ambil trade hari ini dari DB
        try:
            conn = self._get_conn()
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT
                            COUNT(*) as total,
                            SUM(outcome = 'win') as wins,
                            SUM(outcome = 'loss') as losses,
                            SUM(bet_size) as total_invested,
                            SUM(payout) as total_returned,
                            SUM(realized_pnl) as realized_pnl
                        FROM trades
                        WHERE DATE(executed_at) = %s
                          AND status = 'closed'
                    """, (target_date,))
                    row = cur.fetchone()

            if not row or not row[0]:
                logger.info(f"Tidak ada trade closed pada {target_date}")
                return

            total         = int(row[0] or 0)
            wins          = int(row[1] or 0)
            losses        = int(row[2] or 0)
            total_inv     = float(row[3] or 0)
            total_ret     = float(row[4] or 0)
            realized_pnl  = float(row[5] or 0)
            win_rate      = (wins / total * 100) if total > 0 else 0.0
            roi           = (realized_pnl / total_inv * 100) if total_inv > 0 else 0.0

            conn = self._get_conn()
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO daily_performance
                            (date, total_trades, wins, losses, win_rate,
                             total_invested, total_returned, realized_pnl, roi)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            total_trades   = VALUES(total_trades),
                            wins           = VALUES(wins),
                            losses         = VALUES(losses),
                            win_rate       = VALUES(win_rate),
                            total_invested = VALUES(total_invested),
                            total_returned = VALUES(total_returned),
                            realized_pnl   = VALUES(realized_pnl),
                            roi            = VALUES(roi)
                    """, (
                        target_date, total, wins, losses,
                        round(win_rate, 2), round(total_inv, 2),
                        round(total_ret, 2), round(realized_pnl, 2),
                        round(roi, 2),
                    ))
                conn.commit()

            logger.info(f"💾 Daily performance {target_date} disimpan: "
                       f"{total} trades, P&L ${realized_pnl:+.2f}, ROI {roi:+.1f}%")

        except Exception as e:
            logger.error(f"❌ Gagal simpan daily_performance: {e}")

    # ── DB helpers ─────────────────────────────────────────────────────────────

    def _get_conn(self):
        import pymysql
        return pymysql.connect(
            host=config.DB_HOST, port=config.DB_PORT,
            user=config.DB_USER, password=config.DB_PASSWORD,
            database=config.DB_NAME,
            charset="utf8mb4",
            connect_timeout=5,
        )

    def _load_positions_from_db(self):
        """Load posisi open dan closed dari tabel trades saat startup."""
        try:
            conn = self._get_conn()
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT
                            t.trade_id, t.signal_id, t.market_id,
                            t.direction, t.bet_size, t.entry_price,
                            t.shares, t.executed_at, t.status,
                            t.outcome, t.payout, t.realized_pnl,
                            t.closed_at, t.tx_hash,
                            m.question as market_question
                        FROM trades t
                        LEFT JOIN markets m ON t.market_id = m.id
                        ORDER BY t.executed_at DESC
                        LIMIT 200
                    """)
                    rows = cur.fetchall()

            for r in rows:
                pos = {
                    "position_id":     r[0],
                    "signal_id":       r[1],
                    "market_id":       r[2],
                    "direction":       r[3],
                    "amount_invested": float(r[4] or 0),
                    "entry_price":     float(r[5] or 0),
                    "shares":          float(r[6] or 0),
                    "opened_at":       r[7],
                    "status":          r[8],
                    "outcome":         r[9],
                    "payout":          float(r[10] or 0),
                    "realized_pnl":    float(r[11] or 0),
                    "closed_at":       r[12],
                    "tx_hash":         r[13],
                    "market_question": r[14] or "",
                    "current_price":   float(r[5] or 0),
                    "unrealized_pnl":  0.0,
                }

                if r[8] == "open":
                    self.open_positions.append(pos)
                    self.total_invested += pos["amount_invested"]
                else:
                    self.closed_positions.append(pos)
                    self.total_invested += pos["amount_invested"]
                    self.total_returned += pos["payout"]

            logger.info(
                f"📂 Loaded {len(self.open_positions)} open + "
                f"{len(self.closed_positions)} closed positions dari DB"
            )

        except Exception as e:
            logger.warning(f"⚠️  Tidak bisa load positions dari DB: {e}")

    def _update_trade_in_db(self, position: Dict):
        """Update status, outcome, payout, dan realized_pnl di tabel trades."""
        try:
            conn = self._get_conn()
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE trades
                        SET status       = 'closed',
                            outcome      = %s,
                            payout       = %s,
                            realized_pnl = %s,
                            closed_at    = %s
                        WHERE trade_id = %s
                    """, (
                        position["outcome"],
                        position["payout"],
                        position["realized_pnl"],
                        position["closed_at"],
                        position["position_id"],
                    ))
                conn.commit()
            logger.info(f"💾 Trade {position['position_id'][:15]} updated di DB")
        except Exception as e:
            logger.error(f"❌ Gagal update trade di DB: {e}")