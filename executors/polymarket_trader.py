"""
polymarket_trader.py
=====================
Places trades on Polymarket via py-clob-client SDK.

Modes:
  manual    → tidak eksekusi, hanya alert
  semi-auto → alert + tunggu konfirmasi Telegram
  full-auto → eksekusi langsung

Real trading memerlukan CLOB credentials di .env:
  PRIVATE_KEY, CLOB_API_KEY, CLOB_SECRET, CLOB_PASSPHRASE, WALLET_ADDRESS
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Optional

import config

logger = logging.getLogger(__name__)

CLOB_HOST = "https://clob.polymarket.com"
CHAIN_ID  = 137  # Polygon mainnet


class PolymarketTrader:

    def __init__(self):
        self._client = None
        self._init_client()

    def _init_client(self):
        """Inisialisasi CLOB client dari credentials di .env."""
        if not config.PRIVATE_KEY or config.PRIVATE_KEY == "-":
            logger.warning("⚠️  PRIVATE_KEY tidak diset — simulation mode")
            return
        if not config.CLOB_IS_READY():
            logger.warning("⚠️  CLOB credentials belum lengkap — simulation mode")
            return
        try:
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import ApiCreds

            creds = ApiCreds(
                api_key        = config.CLOB_API_KEY,
                api_secret     = config.CLOB_SECRET,
                api_passphrase = config.CLOB_PASSPHRASE,
            )
            self._client = ClobClient(
                CLOB_HOST,
                key            = config.PRIVATE_KEY,
                chain_id       = CHAIN_ID,
                creds          = creds,
                signature_type = 2,
                funder         = config.WALLET_ADDRESS,
            )
            logger.info(f"✅ CLOB client ready — funder: {config.WALLET_ADDRESS[:10]}...")

            # Test balance saat init untuk verifikasi koneksi
            bal = self.get_balance()
            logger.info(f"💰 Initial balance: ${bal:.4f} USDC")

        except ImportError:
            logger.error("❌ py-clob-client tidak terinstall")
        except Exception as e:
            logger.error(f"❌ Gagal init CLOB client: {e}")

    # ── Main execute ──────────────────────────────────────────────────────────

    def execute_trade(
        self,
        signal:    Dict,
        signal_id: int,
        bet_size:  float,
    ) -> Optional[Dict]:
        """
        Eksekusi trade. Returns trade_result dict atau None jika gagal.
        """
        mode = config.AUTOMATION_MODE()
        if mode == "manual":
            logger.info("ℹ️  Mode manual — tidak ada eksekusi")
            return None

        market_id       = signal.get("market_id", "")
        market_question = signal.get("market_question", "")
        direction       = signal.get("direction", "YES")
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
        if balance < bet_size and self._client:
            logger.error(f"❌ Balance tidak cukup: ${balance:.2f} < ${bet_size:.2f}")
            return None

        # Real trading jika client ready
        if self._client:
            return self._execute_real(signal, signal_id, bet_size, direction, current_price, market_id, market_question)
        else:
            return self._execute_simulation(signal, signal_id, bet_size, direction, current_price, market_id, market_question)

    def _execute_real(self, signal, signal_id, bet_size, direction, price, market_id, market_question):
        """Eksekusi real via CLOB API."""
        try:
            from py_clob_client.clob_types import OrderArgs, OrderType
            from py_clob_client.order_builder.constants import BUY, SELL

            # Ambil token_id YES atau NO dari signal
            token_id  = signal.get("asset_id") or signal.get("token_id", "")
            if not token_id:
                logger.error("❌ token_id tidak ada di signal")
                return None

            # YES → BUY YES token, NO → BUY NO token
            side       = BUY
            tick_size  = self._client.get_tick_size(token_id) or "0.01"
            neg_risk   = self._client.get_neg_risk(token_id) or False

            # Harga: pakai market price dengan sedikit slippage
            order_price = round(min(price + 0.01, 0.99), 4)
            shares      = round(bet_size / order_price, 4)

            logger.info(f"📤 Placing order: {shares:.2f} shares @ {order_price:.4f}")

            response = self._client.create_and_post_order(
                OrderArgs(
                    token_id = token_id,
                    price    = order_price,
                    size     = shares,
                    side     = side,
                ),
                options    = {"tick_size": str(tick_size), "neg_risk": neg_risk},
                order_type = OrderType.GTC,
            )

            order_id = response.get("orderID", "")
            status   = response.get("status", "unknown")
            logger.info(f"✅ Order placed: {order_id} | status: {status}")

            return {
                "trade_id":       order_id,
                "signal_id":      signal_id,
                "market_id":      market_id,
                "direction":      direction,
                "bet_size":       round(bet_size, 2),
                "entry_price":    order_price,
                "shares":         shares,
                "executed_at":    datetime.now(timezone.utc),
                "status":         "open",
                "tx_hash":        order_id,
                "market_question": market_question,
                "simulation":     False,
                "order_status":   status,
            }

        except Exception as e:
            logger.error(f"❌ Execute real error: {e}")
            return None

    def _execute_simulation(self, signal, signal_id, bet_size, direction, price, market_id, market_question):
        """Simulation mode — tidak ada trade sungguhan."""
        logger.warning("⚠️  SIMULATION MODE — tidak ada trade sungguhan")
        shares = round(bet_size / price, 4) if price > 0 else 0
        return {
            "trade_id":       f"SIM_{datetime.now(timezone.utc).timestamp():.0f}",
            "signal_id":      signal_id,
            "market_id":      market_id,
            "direction":      direction,
            "bet_size":       round(bet_size, 2),
            "entry_price":    price,
            "shares":         shares,
            "executed_at":    datetime.now(timezone.utc),
            "status":         "open",
            "tx_hash":        None,
            "market_question": market_question,
            "simulation":     True,
        }

    # ── Balance ───────────────────────────────────────────────────────────────

    def get_balance(self) -> float:
        """
        Ambil saldo USDC.e dari proxy wallet via on-chain.
        CLOB get_balance_allowance skip — ada bug di SDK (NoneType signature_type).
        On-chain via public Polygon RPC — terbukti return $0.7889.
        """
        # Method 1: On-chain via public Polygon RPC (terbukti bekerja)
        PUBLIC_RPCS = [
            "https://rpc-mainnet.matic.quiknode.pro",
            "https://polygon.llamarpc.com",
            "https://rpc.ankr.com/polygon",
        ]
        wallet = config.WALLET_ADDRESS or ""
        if not wallet:
            return 0.0

        try:
            from web3 import Web3
            USDC_E = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
            abi    = [{"constant":True,"inputs":[{"name":"_owner","type":"address"}],
                       "name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],
                       "type":"function"}]

            for rpc in PUBLIC_RPCS:
                try:
                    w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 5}))
                    if not w3.is_connected():
                        continue
                    usdc = w3.eth.contract(address=Web3.to_checksum_address(USDC_E), abi=abi)
                    raw  = usdc.functions.balanceOf(Web3.to_checksum_address(wallet)).call()
                    bal  = raw / 1e6
                    logger.debug(f"Balance on-chain ({rpc[:30]}): ${bal:.4f}")
                    return bal
                except Exception:
                    continue
        except ImportError:
            logger.warning("web3 tidak terinstall — balance tidak bisa dibaca")
        except Exception as e:
            logger.error(f"get_balance error: {e}")

        return 0.0

    def is_ready(self) -> bool:
        return self._client is not None

    def get_status(self) -> Dict:
        balance = self.get_balance() if self.is_ready() else 0.0
        return {
            "wallet_configured": self.is_ready(),
            "wallet_address":    (config.WALLET_ADDRESS[:10] + "...") if config.WALLET_ADDRESS else None,
            "balance_usdc":      balance,
            "mode":              config.AUTOMATION_MODE(),
            "simulation":        not self.is_ready(),
        }