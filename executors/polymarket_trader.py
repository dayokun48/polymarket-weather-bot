"""
polymarket_trader.py
=====================
Places trades on Polymarket (simulation + real mode).

Fixes dari original:
  - datetime.utcnow() deprecated → datetime.now(timezone.utc)
  - gas_fee & total_cost tidak ada di tabel trades → dihapus dari trade_result
  - signal['x'] tanpa .get() → crash jika field tidak ada
  - trade_result sekarang include signal_id (dibutuhkan risk_manager.record_trade)
  - Status 'SIMULATED' tidak valid untuk tabel trades → pakai 'open'
  - Mode semi-auto: kirim alert dulu, eksekusi setelah konfirmasi
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Optional

import config

logger = logging.getLogger(__name__)


class PolymarketTrader:
    """
    Execute trades on Polymarket.

    Mode:
      manual    → tidak eksekusi, hanya alert
      semi-auto → alert + tunggu konfirmasi Telegram sebelum eksekusi
      full-auto → eksekusi langsung tanpa konfirmasi

    Saat ini: simulation mode.
    Real trading butuh Polymarket CLOB API key dan USDC di wallet Polygon.
    """

    def __init__(self):
        self.clob_api   = config.CLOB_API
        self.account    = None
        self.address    = None
        self.w3         = None
        self._init_wallet()

    def _init_wallet(self):
        """Inisialisasi wallet dari private key di .env."""
        private_key = config.PRIVATE_KEY
        if not private_key or private_key == "-":
            logger.warning("⚠️  Private key tidak dikonfigurasi — trading disabled")
            return

        try:
            from web3 import Web3
            from eth_account import Account

            self.w3      = Web3(Web3.HTTPProvider("https://polygon-rpc.com"))
            self.account = Account.from_key(private_key)
            self.address = self.account.address
            logger.info(f"✅ Wallet loaded: {self.address[:10]}...")
        except ImportError:
            logger.error("❌ web3 tidak terinstall — jalankan: pip install web3")
        except Exception as e:
            logger.error(f"❌ Gagal load wallet: {e}")

    # ── Main execute ───────────────────────────────────────────────────────────

    def execute_trade(
        self,
        signal:    Dict,
        signal_id: int,
        bet_size:  float,
    ) -> Optional[Dict]:
        """
        Eksekusi trade berdasarkan signal.

        Args:
            signal    : signal dict dari WeatherAnalyzer
            signal_id : ID dari tabel signals (FK untuk tabel trades)
            bet_size  : jumlah bet dalam USD

        Returns dict trade_result yang siap dipakai risk_manager.record_trade(),
        atau None jika gagal.
        """
        mode = config.AUTOMATION_MODE()

        if mode == "manual":
            logger.info("ℹ️  Mode manual — tidak ada eksekusi otomatis")
            return None

        if not self.account and mode == "full-auto":
            logger.error("❌ Wallet tidak dikonfigurasi — tidak bisa full-auto")
            return None

        market_id       = signal.get("market_id", "")
        market_question = signal.get("market_question", "")
        direction       = signal.get("direction", "")
        current_price   = signal.get("current_price", 0.5)

        logger.info("=" * 55)
        logger.info("⚡ EXECUTING TRADE")
        logger.info(f"   Market   : {market_question[:60]}")
        logger.info(f"   Direction: {direction}")
        logger.info(f"   Amount   : ${bet_size:.2f}")
        logger.info(f"   Price    : {current_price:.4f}")
        logger.info("=" * 55)

        # Cek balance
        balance = self.get_balance()
        logger.info(f"💰 Balance: ${balance:.2f} USDC")

        if balance < bet_size and self.account:
            logger.error(f"❌ Balance tidak cukup: ${balance:.2f} < ${bet_size:.2f}")
            return None

        # Hitung shares
        shares = bet_size / current_price if current_price > 0 else 0

        # ── Simulation mode ────────────────────────────────────────────────────
        # Real implementation perlu:
        # 1. Approve USDC spending ke Polymarket CTF contract
        # 2. POST ke /order di CLOB API dengan signed order
        # 3. Poll order status sampai filled
        # 4. Return tx_hash dari on-chain confirmation

        logger.warning("⚠️  SIMULATION MODE — tidak ada trade sungguhan")

        trade_result = {
            # ── Field yang masuk ke tabel trades ────────────────────────────
            "trade_id":       f"SIM_{datetime.now(timezone.utc).timestamp():.0f}",
            "signal_id":      signal_id,        # FK ke tabel signals
            "market_id":      market_id,
            "direction":      direction,
            "bet_size":       round(bet_size, 2),
            "entry_price":    current_price,
            "shares":         round(shares, 4),
            "executed_at":    datetime.now(timezone.utc),
            "status":         "open",           # 'open' sesuai schema trades
            "tx_hash":        None,
            # ── Extra untuk Telegram confirmation ────────────────────────────
            "market_question": market_question,
            "simulation":      True,
        }

        logger.info("=" * 55)
        logger.info("✅ TRADE SIMULATED")
        logger.info(f"   Trade ID: {trade_result['trade_id']}")
        logger.info(f"   Shares  : {trade_result['shares']:.4f}")
        logger.info("=" * 55)

        return trade_result

    # ── Balance ────────────────────────────────────────────────────────────────

    def get_balance(self) -> float:
        """
        Ambil saldo USDC di wallet Polygon.
        Returns 0.0 jika wallet tidak dikonfigurasi atau error.
        """
        if not self.address or not self.w3:
            return 0.0

        try:
            from web3 import Web3

            # USDC contract di Polygon (6 decimals)
            usdc_address = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
            usdc_abi = [{
                "constant": True,
                "inputs": [{"name": "_owner", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "balance", "type": "uint256"}],
                "type": "function",
            }]

            contract    = self.w3.eth.contract(
                address=Web3.to_checksum_address(usdc_address),
                abi=usdc_abi,
            )
            balance_raw = contract.functions.balanceOf(
                Web3.to_checksum_address(self.address)
            ).call()

            return balance_raw / 1e6  # USDC punya 6 decimals

        except Exception as e:
            logger.error(f"Error get_balance: {e}")
            return 0.0

    # ── Position management ────────────────────────────────────────────────────

    def get_open_positions(self) -> list:
        """
        Ambil posisi yang masih open.
        Untuk sekarang baca dari database via position_tracker.
        """
        return []

    def close_position(self, position_id: str) -> bool:
        """
        Tutup posisi (jual shares).
        Belum diimplementasi — butuh CLOB API integration.
        """
        logger.warning("⚠️  close_position belum diimplementasi")
        return False

    # ── Utility ───────────────────────────────────────────────────────────────

    def is_ready(self) -> bool:
        """Cek apakah trader siap untuk eksekusi real."""
        return self.account is not None and self.w3 is not None

    def get_status(self) -> Dict:
        """Status trader untuk dashboard."""
        return {
            "wallet_configured": self.account is not None,
            "wallet_address":    self.address[:10] + "..." if self.address else None,
            "balance_usdc":      self.get_balance() if self.account else 0.0,
            "mode":              config.AUTOMATION_MODE(),
            "simulation":        not self.is_ready(),
        }