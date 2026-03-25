"""
telegram_handler.py
====================
Background thread yang polling Telegram getUpdates dan handle:

  Callbacks (inline buttons):
    execute:{signal_id}  → tanya berapa bet, lalu eksekusi
    skip:{signal_id}     → update status = 'skipped'

  Commands:
    /status   → status bot, trades hari ini, P&L
    /pause    → pause bot
    /unpause  → resume bot
    /signals  → 5 signal terbaru
    /scan     → trigger scan manual
    /balance  → saldo USDC wallet

  Conversation state:
    Setelah user klik EXECUTE → bot tunggu input jumlah ($)
    User ketik angka → eksekusi trade

Jalankan sebagai daemon thread dari app.py:
    from notifications.telegram_handler import TelegramHandler
    handler = TelegramHandler(risk_manager, trader, scanner_func)
    handler.start()
"""

import json
import logging
import threading
import time
from datetime import date, datetime, timezone
from typing import Callable, Dict, Optional

import requests
import urllib3
urllib3.disable_warnings()

import config

logger = logging.getLogger(__name__)


class TelegramHandler:
    """
    Long-polling Telegram bot handler.
    Thread-safe — akses DB dengan connection baru tiap request.
    """

    POLL_TIMEOUT = 30    # long-polling timeout (detik)
    RETRY_SLEEP  = 10    # sleep saat error sebelum retry

    def __init__(self, risk_manager, trader, scanner_func: Callable = None):
        self.risk_manager  = risk_manager
        self.trader        = trader
        self.scanner_func  = scanner_func   # fungsi scan_for_opportunities dari app.py
        self.token         = config.TELEGRAM_BOT_TOKEN
        self.chat_id       = config.TELEGRAM_CHAT_ID
        self.base_url      = f"https://api.telegram.org/bot{self.token}"
        self._offset       = 0
        self._running      = False
        self._thread       = None
        # Conversation state: {chat_id: {"action": "awaiting_bet", "signal_id": X}}
        self._conv_state: Dict[str, Dict] = {}

    # ── Public ────────────────────────────────────────────────────────────────

    def start(self):
        """Start background polling thread."""
        if not self.token or not self.chat_id:
            logger.warning("⚠️  Telegram tidak dikonfigurasi — handler tidak dijalankan")
            return
        self._running = True
        self._thread  = threading.Thread(target=self._poll_loop, daemon=True, name="TelegramHandler")
        self._thread.start()
        logger.info("✅ Telegram handler started")

    def stop(self):
        self._running = False

    # ── Polling loop ──────────────────────────────────────────────────────────

    def _poll_loop(self):
        logger.info("📡 Telegram polling started")
        while self._running:
            try:
                updates = self._get_updates()
                for update in updates:
                    self._process_update(update)
            except Exception as e:
                logger.error(f"Polling error: {e}")
                time.sleep(self.RETRY_SLEEP)

    def _get_updates(self) -> list:
        try:
            r = requests.get(
                f"{self.base_url}/getUpdates",
                params={"offset": self._offset, "timeout": self.POLL_TIMEOUT, "allowed_updates": '["message","callback_query"]'},
                timeout=self.POLL_TIMEOUT + 5,
            )
            data = r.json()
            if not data.get("ok"):
                return []
            updates = data.get("result", [])
            if updates:
                self._offset = updates[-1]["update_id"] + 1
            return updates
        except Exception as e:
            logger.error(f"getUpdates error: {e}")
            return []

    # ── Process update ────────────────────────────────────────────────────────

    def _process_update(self, update: dict):
        # Callback query (button click)
        if "callback_query" in update:
            self._handle_callback(update["callback_query"])
        # Text message (command atau reply)
        elif "message" in update:
            msg = update["message"]
            text = msg.get("text", "").strip()
            chat_id = str(msg["chat"]["id"])

            # Cek conversation state dulu
            if chat_id in self._conv_state:
                self._handle_conversation(chat_id, text, msg)
            elif text.startswith("/"):
                self._handle_command(chat_id, text)

    # ── Callback handler ──────────────────────────────────────────────────────

    def _handle_callback(self, cb: dict):
        cb_id   = cb["id"]
        data    = cb.get("data", "")
        chat_id = str(cb["message"]["chat"]["id"])
        msg_id  = cb["message"]["message_id"]

        try:
            action, signal_id_str = data.split(":", 1)
            signal_id = int(signal_id_str)
        except Exception:
            self._answer_callback(cb_id, "❌ Invalid callback")
            return

        if action == "execute":
            self._answer_callback(cb_id, "💰 Berapa yang mau di-bet?")
            # Set conversation state — tunggu input jumlah
            self._conv_state[chat_id] = {
                "action":    "awaiting_bet",
                "signal_id": signal_id,
                "msg_id":    msg_id,
            }
            self._send(chat_id,
                f"💰 <b>Berapa yang mau di-bet?</b>\n\n"
                f"Ketik jumlah dalam USD (contoh: <code>10</code>)\n"
                f"Min: $1 | Max: ${config.MAX_BET_PCT() * config.get('bankroll', float) / 100:.0f}\n\n"
                f"Ketik <code>cancel</code> untuk batal."
            )

        elif action == "skip":
            self._update_signal_status(signal_id, "skipped")
            self._answer_callback(cb_id, "❌ Signal skipped")
            self._edit_message(chat_id, msg_id,
                cb["message"]["text"] + "\n\n<i>❌ SKIPPED</i>"
            )

    # ── Conversation handler ──────────────────────────────────────────────────

    def _handle_conversation(self, chat_id: str, text: str, msg: dict):
        state = self._conv_state.get(chat_id, {})

        if state.get("action") == "awaiting_bet":
            if text.lower() == "cancel":
                del self._conv_state[chat_id]
                self._send(chat_id, "❌ Dibatalkan.")
                return

            try:
                bet_size = float(text.replace("$", "").strip())
                if bet_size < 1:
                    self._send(chat_id, "⚠️  Minimum bet $1. Coba lagi:")
                    return

                max_bet = config.MAX_BET_PCT() * config.get("bankroll", float) / 100
                if bet_size > max_bet:
                    self._send(chat_id, f"⚠️  Maksimum ${max_bet:.2f}. Coba lagi:")
                    return

            except ValueError:
                self._send(chat_id, "⚠️  Format salah. Ketik angka saja, contoh: <code>10</code>")
                return

            signal_id = state["signal_id"]
            del self._conv_state[chat_id]

            self._send(chat_id, f"⏳ Mengeksekusi trade ${bet_size:.2f}...")
            self._execute_from_signal(chat_id, signal_id, bet_size)

    # ── Command handler ───────────────────────────────────────────────────────

    def _handle_command(self, chat_id: str, text: str):
        cmd = text.split()[0].lower().replace("@", " ").split()[0]

        if cmd == "/status":
            self._cmd_status(chat_id)
        elif cmd == "/pause":
            self._cmd_pause(chat_id)
        elif cmd == "/unpause":
            self._cmd_unpause(chat_id)
        elif cmd == "/signals":
            self._cmd_signals(chat_id)
        elif cmd == "/scan":
            self._cmd_scan(chat_id)
        elif cmd == "/balance":
            self._cmd_balance(chat_id)
        elif cmd == "/help":
            self._cmd_help(chat_id)

    def _cmd_status(self, chat_id):
        try:
            import pymysql
            conn = self._get_conn()
            with conn:
                with conn.cursor() as cur:
                    today = date.today()
                    cur.execute("SELECT COUNT(*) as cnt FROM trades WHERE DATE(executed_at)=%s", (today,))
                    trades_today = cur.fetchone()["cnt"]
                    cur.execute("SELECT COALESCE(SUM(realized_pnl),0) as pnl FROM trades WHERE DATE(executed_at)=%s", (today,))
                    pnl_today = float(cur.fetchone()["pnl"] or 0)
                    cur.execute("SELECT COUNT(*) as cnt FROM signals WHERE DATE(created_at)=%s", (today,))
                    signals_today = cur.fetchone()["cnt"]
                    cur.execute("SELECT COUNT(*) as cnt FROM trades WHERE status='open'", ())
                    open_positions = cur.fetchone()["cnt"]

            trader_status = self.trader.get_status()
            balance = trader_status.get("balance_usdc", 0)
            paused  = self.risk_manager.paused if hasattr(self.risk_manager, 'paused') else False

            msg = f"""📊 <b>BOT STATUS</b>

⚙️ Mode: <b>{config.AUTOMATION_MODE()}</b>
{'🔴 PAUSED' if paused else '🟢 RUNNING'}

📅 <b>Today ({today})</b>
Signals    : {signals_today}
Trades     : {trades_today}
P&L        : ${pnl_today:+.2f}
Open pos   : {open_positions}

💰 Balance : ${balance:.2f} USDC
🔑 CLOB    : {'✅ Ready' if config.CLOB_IS_READY() else '❌ Not configured'}

⏱️ Interval: {config.CHECK_INTERVAL_MINUTES()} menit
🎯 Min edge: {config.MIN_EDGE_PCT()}%
🔥 Min conf: {config.MIN_CONFIDENCE_PCT()}%
⚡ Auto-trade ≥ {config.AUTO_TRADE_THRESHOLD():.0f}% conf → ${config.AUTO_TRADE_AMOUNT():.0f}"""
            self._send(chat_id, msg)
        except Exception as e:
            self._send(chat_id, f"❌ Error: {e}")

    def _cmd_pause(self, chat_id):
        if hasattr(self.risk_manager, 'paused'):
            self.risk_manager.paused = True
        self._send(chat_id, "🔴 <b>Bot di-PAUSE.</b>\nKetik /unpause untuk lanjutkan.")

    def _cmd_unpause(self, chat_id):
        if hasattr(self.risk_manager, 'paused'):
            self.risk_manager.paused = False
            self.risk_manager.consecutive_losses = 0
        self._send(chat_id, "🟢 <b>Bot di-RESUME.</b>\nScanning aktif kembali.")

    def _cmd_signals(self, chat_id):
        try:
            conn = self._get_conn()
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT location, direction, edge, confidence, status, created_at
                        FROM signals ORDER BY created_at DESC LIMIT 5
                    """)
                    rows = cur.fetchall()

            if not rows:
                self._send(chat_id, "📭 Belum ada signal.")
                return

            lines = ["🔔 <b>5 SIGNAL TERBARU</b>\n"]
            for r in rows:
                ts = r["created_at"].strftime("%m/%d %H:%M") if r["created_at"] else "—"
                lines.append(
                    f"• {r['location'] or '?'} | {r['direction']} | "
                    f"edge:{r['edge']:.0f}% conf:{r['confidence']:.0f}% | "
                    f"<i>{r['status']}</i> [{ts}]"
                )
            self._send(chat_id, "\n".join(lines))
        except Exception as e:
            self._send(chat_id, f"❌ Error: {e}")

    def _cmd_scan(self, chat_id):
        if not self.scanner_func:
            self._send(chat_id, "❌ Scanner tidak tersedia.")
            return
        self._send(chat_id, "🔄 Memulai scan manual...")
        threading.Thread(target=self._run_scan, args=(chat_id,), daemon=True).start()

    def _run_scan(self, chat_id):
        try:
            self.scanner_func()
            self._send(chat_id, "✅ Scan selesai. Cek /signals untuk hasilnya.")
        except Exception as e:
            self._send(chat_id, f"❌ Scan error: {e}")

    def _cmd_balance(self, chat_id):
        balance = self.trader.get_balance()
        mode    = "🟢 Real" if self.trader.is_ready() else "🟡 Simulation"
        self._send(chat_id,
            f"💰 <b>WALLET BALANCE</b>\n\n"
            f"USDC  : <b>${balance:.2f}</b>\n"
            f"Mode  : {mode}\n"
            f"Wallet: <code>{config.WALLET_ADDRESS[:16]}...</code>"
        )

    def _cmd_help(self, chat_id):
        self._send(chat_id,
            "🤖 <b>WEATHER BOT COMMANDS</b>\n\n"
            "/status   — status bot & statistik hari ini\n"
            "/signals  — 5 signal terbaru\n"
            "/balance  — saldo USDC wallet\n"
            "/scan     — trigger scan manual\n"
            "/pause    — pause bot\n"
            "/unpause  — resume bot\n"
            "/help     — daftar commands"
        )

    # ── Execute from signal ───────────────────────────────────────────────────

    def _execute_from_signal(self, chat_id: str, signal_id: int, bet_size: float):
        """Ambil signal dari DB lalu eksekusi trade."""
        try:
            conn = self._get_conn()
            signal = None
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT s.*, m.question as market_question, m.url as market_url
                        FROM signals s
                        LEFT JOIN markets m ON s.market_id = m.id
                        WHERE s.id = %s
                    """, (signal_id,))
                    signal = cur.fetchone()

            if not signal:
                self._send(chat_id, f"❌ Signal #{signal_id} tidak ditemukan.")
                return

            # Validasi via risk manager
            ok, reason = self.risk_manager.validate_signal(signal, self.trader.get_balance())
            if not ok:
                self._send(chat_id, f"❌ Validasi gagal: {reason}")
                return

            # Eksekusi
            result = self.trader.execute_trade(signal, signal_id, bet_size)
            if not result:
                self._send(chat_id, "❌ Trade gagal dieksekusi.")
                return

            # Simpan ke DB
            self.risk_manager.record_trade(result)
            self._update_signal_status(signal_id, "executed")

            mode_label = "🟡 SIMULATED" if result.get("simulation") else "✅ EXECUTED"
            self._send(chat_id,
                f"{mode_label} <b>TRADE</b>\n\n"
                f"📊 {(signal.get('market_question',''))[:60]}\n"
                f"Direction : {result['direction']}\n"
                f"Amount    : <b>${result['bet_size']:.2f}</b>\n"
                f"Entry     : {result['entry_price']:.4f}\n"
                f"Shares    : {result['shares']:.2f}\n"
                f"{'Order ID  : ' + result['trade_id'][:20] if not result.get('simulation') else 'Mode: Simulation'}"
            )

        except Exception as e:
            logger.error(f"_execute_from_signal error: {e}")
            self._send(chat_id, f"❌ Error saat eksekusi: {e}")

    # ── Auto-trade (dipanggil dari scanner) ───────────────────────────────────

    def auto_execute(self, signal: dict, signal_id: int):
        """
        Dipanggil dari scan_for_opportunities jika confidence >= auto_trade_threshold.
        Eksekusi langsung dengan auto_trade_amount, kirim notif ke Telegram.
        """
        bet_size = config.AUTO_TRADE_AMOUNT()
        logger.info(f"⚡ Auto-trade: signal #{signal_id} confidence={signal.get('confidence')}% bet=${bet_size}")

        result = self.trader.execute_trade(signal, signal_id, bet_size)
        if not result:
            self._send(self.chat_id, f"❌ Auto-trade gagal untuk signal #{signal_id}")
            return

        self.risk_manager.record_trade(result)
        self._update_signal_status(signal_id, "executed")

        mode_label = "🟡 AUTO SIMULATED" if result.get("simulation") else "⚡ AUTO EXECUTED"
        self._send(self.chat_id,
            f"{mode_label}\n\n"
            f"📊 {(signal.get('market_question',''))[:60]}\n"
            f"Direction  : {result['direction']}\n"
            f"Amount     : <b>${result['bet_size']:.2f}</b>\n"
            f"Entry      : {result['entry_price']:.4f}\n"
            f"Confidence : {signal.get('confidence',0):.0f}% (≥ {config.AUTO_TRADE_THRESHOLD():.0f}% → auto)\n"
            f"Edge       : +{signal.get('edge',0):.0f}%"
        )

    # ── DB helpers ────────────────────────────────────────────────────────────

    def _get_conn(self):
        import pymysql
        return pymysql.connect(
            host=config.DB_HOST, port=config.DB_PORT,
            user=config.DB_USER, password=config.DB_PASSWORD,
            database=config.DB_NAME, charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor, connect_timeout=5,
        )

    def _update_signal_status(self, signal_id: int, status: str):
        try:
            conn = self._get_conn()
            with conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE signals SET status=%s WHERE id=%s", (status, signal_id))
                conn.commit()
        except Exception as e:
            logger.error(f"_update_signal_status error: {e}")

    # ── Telegram API helpers ──────────────────────────────────────────────────

    def _send(self, chat_id: str, text: str) -> bool:
        try:
            r = requests.post(f"{self.base_url}/sendMessage", json={
                "chat_id": chat_id, "text": text,
                "parse_mode": "HTML", "disable_web_page_preview": True,
            }, timeout=10)
            return r.json().get("ok", False)
        except Exception as e:
            logger.error(f"_send error: {e}")
            return False

    def _edit_message(self, chat_id: str, msg_id: int, text: str):
        try:
            requests.post(f"{self.base_url}/editMessageText", json={
                "chat_id": chat_id, "message_id": msg_id,
                "text": text, "parse_mode": "HTML",
            }, timeout=10)
        except Exception as e:
            logger.error(f"_edit_message error: {e}")

    def _answer_callback(self, callback_id: str, text: str = ""):
        try:
            requests.post(f"{self.base_url}/answerCallbackQuery", json={
                "callback_query_id": callback_id, "text": text, "show_alert": False,
            }, timeout=5)
        except Exception as e:
            logger.error(f"_answer_callback error: {e}")