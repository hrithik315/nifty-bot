import os
import time
import json
import threading
from datetime import datetime
import pytz
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests
import yfinance as yf

# Production Config
BOT_TOKEN = "8695074642:AAF44kKVuUiD5x7SMtW5M_nygHMoTIS0H5g"
CHAT_ID = "1152142289"
STATE_FILE = "portfolio_state.json"

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "status": "WAITING_ENTRY",  # WAITING_ENTRY ya HOLDING
        "entry_price": 0.0,
        "target_price": 0.0,
        "support_entry_level": 0.0,
        "last_candle_time": ""
    }

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)

# Keep-Alive Server
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Precision Price Reminder Active!")

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()

def send_telegram_msg(text, keyboard=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": str(text),
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    if keyboard:
        payload["reply_markup"] = json.dumps(keyboard)
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception:
        pass

def fetch_market_prices():
    try:
        ticker = yf.Ticker("NIFTYBEES.NS")
        df_1m = ticker.history(period="1d", interval="1m")
        df_15m = ticker.history(period="5d", interval="15m")
        df_daily = ticker.history(period="1mo", interval="1d")

        if df_1m.empty or df_15m.empty:
            return None

        curr_close = round(float(df_1m['Close'].iloc[-1]), 2)
        candle_time = str(df_1m.index[-1])

        # Key Structural Support (Pichla Swing Low / Demand)
        swing_low = float(df_15m['Low'].min())
        prev_low = float(df_daily['Low'].iloc[-2])
        valid_supports = [s for s in [prev_low, swing_low] if s < (curr_close - 0.15)]
        entry_level = round(max(valid_supports), 2) if valid_supports else round(curr_close * 0.993, 2)

        # Dynamic Resistance Target
        prev_highs = [h for h in df_15m['High'].tail(30) if h > curr_close + 0.30]
        target_level = round(min(prev_highs), 2) if prev_highs else round(curr_close * 1.018, 2)

        return {
            "close": curr_close,
            "candle_time": candle_time,
            "entry_level": entry_level,
            "target_level": target_level
        }
    except Exception:
        return None

def build_status_message(prices):
    state = load_state()
    curr_p = prices["close"]

    # 1. AGAR TRADE HOLDING HAI (Target ka reminder)
    if state.get("status") == "HOLDING":
        entry_p = state.get("entry_price", curr_p)
        target_p = state.get("target_price", round(entry_p * 1.02, 2))
        gap_to_target = round(target_p - curr_p, 2)

        if gap_to_target <= 0:
            status_text = "🎉 **TARGET REACHED / CROSSED!**"
            action = f"🚀 Target touch ho gaya hai! Turant apna munafa book karein."
        else:
            status_text = "🎯 **TARGET STATUS TRACKER**"
            action = f"⏳ **Target Hit Hone Me:** **₹{gap_to_target:.2f} Points** baaki hain."

        msg = (
            f"{status_text}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"💰 *Live Price:* ₹{curr_p:.2f}\n"
            f"📍 *Aapki Buy Price:* ₹{entry_p:.2f}\n"
            f"🏁 *Target Exit Price:* ₹{target_p:.2f}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"{action}"
        )
        kb = {"inline_keyboard": [[{"text": "🏁 Booked / Exit Trade", "callback_data": "exit_done"}]]}
        return msg, kb

    # 2. AGAR ENTRY KA WAIT HAI (Entry ka reminder)
    else:
        entry_p = prices["entry_level"]
        target_p = prices["target_level"]
        gap_to_entry = round(curr_p - entry_p, 2)

        state["support_entry_level"] = entry_p
        state["target_price"] = target_p
        save_state(state)

        if gap_to_entry <= 0.05:
            status_text = "🟢 **ENTRY LEVEL REACHED! BUY NOW!**"
            action = f"👉 **Abhi Buy Order Lagao:** ₹{curr_p:.2f} par position banao!"
            kb = {"inline_keyboard": [[{"text": "✅ Yes, I Bought", "callback_data": "bought_confirm"}]]}
        else:
            status_text = "📍 **ENTRY REMINDER: NIFTYBEES**"
            action = f"⏳ **Entry Aane Me:** **₹{gap_to_entry:.2f} Points (Paise)** girna baaki hai."
            kb = {"inline_keyboard": [
                [{"text": "✅ Maine Abhi Buy Kar Liya", "callback_data": "bought_confirm"}]
            ]}

        msg = (
            f"{status_text}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"💰 *Current Live Price:* ₹{curr_p:.2f}\n"
            f"🟢 *Entry Buy Price:* ₹{entry_p:.2f}\n"
            f"🏁 *Target Exit Price:* ₹{target_p:.2f}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"{action}\n\n"
            f"💡 *Tip:* Terminal me ₹{entry_p:.2f} par Limit Order laga kar rakhein."
        )
        return msg, kb

# Interactive Telegram Listener
def telegram_listener():
    offset = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={offset}&timeout=10"
            res = requests.get(url, timeout=15).json()
            if "result" in res:
                for update in res["result"]:
                    offset = update["update_id"] + 1

                    if "callback_query" in update:
                        cb = update["callback_query"]
                        cb_id = cb["id"]
                        data = cb["data"]
                        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery", json={"callback_query_id": cb_id})

                        state = load_state()
                        prices = fetch_market_prices()
                        curr_p = prices["close"] if prices else 271.50

                        if data == "bought_confirm":
                            state["status"] = "HOLDING"
                            state["entry_price"] = curr_p
                            state["target_price"] = round(curr_p * 1.02, 2)  # 2% standard target
                            save_state(state)
                            send_telegram_msg(
                                f"✅ *Trade Confirmed at ₹{curr_p:.2f}!*\n\n"
                                f"🏁 **Target Set:** ₹{state['target_price']:.2f}\n"
                                f"Ab bot aapko target aane ka live countdown bhejega."
                            )
                        elif data == "exit_done":
                            state["status"] = "WAITING_ENTRY"
                            state["entry_price"] = 0.0
                            state["target_price"] = 0.0
                            save_state(state)
                            send_telegram_msg("🏁 *Position Closed!* Bot agle dip aur entry ka countdown shuru kar raha hai.")

                    elif "message" in update and "text" in update["message"]:
                        prices = fetch_market_prices()
                        if prices:
                            msg, kb = build_status_message(prices)
                            send_telegram_msg(msg, kb)

        except Exception:
            pass
        time.sleep(1)

# Real-Time Price & Alert Monitor
def check_market():
    ist = pytz.timezone("Asia/Kolkata")
    send_telegram_msg("🚀 *Live Price & Target Reminder Online!*\n• Entry me kitna kam hai wo dikhega\n• Target me kitna kam hai uska alert aayega.")

    while True:
        try:
            now = datetime.now(ist)

            if now.weekday() < 5 and (now.hour > 9 or (now.hour == 9 and now.minute >= 15)) and (now.hour < 15 or (now.hour == 15 and now.minute <= 30)):
                prices = fetch_market_prices()
                if prices:
                    state = load_state()
                    last_time = state.get("last_candle_time", "")

                    # 1. Holding status par target touch hone ka instant siren
                    if state.get("status") == "HOLDING":
                        t_price = state.get("target_price", 0.0)
                        if t_price > 0 and prices["close"] >= t_price:
                            kb = {"inline_keyboard": [[{"text": "🏁 Booked / Exit Trade", "callback_data": "exit_done"}]]}
                            send_telegram_msg(
                                f"🚨🚨 *TARGET HIT HO GAYA HAI!* 🚨🚨\n\n"
                                f"📈 Live Bhav: *₹{prices['close']:.2f}*\n"
                                f"🎯 Target Bhav: *₹{t_price:.2f}*\n\n"
                                f"👉 Turant broker app khol kar profit book karein!",
                                kb
                            )

                    # 2. Har 1-minute candle par reminder update
                    if prices["candle_time"] != last_time:
                        state["last_candle_time"] = prices["candle_time"]
                        save_state(state)

                        msg, kb = build_status_message(prices)
                        send_telegram_msg(msg, kb)

            time.sleep(15)
        except Exception:
            time.sleep(15)

if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    threading.Thread(target=telegram_listener, daemon=True).start()
    check_market()

