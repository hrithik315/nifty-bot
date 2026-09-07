import os
import time
import json
import threading
from datetime import datetime
import pytz
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests
import numpy as np
import pandas as pd
import yfinance as yf
import mplfinance as mpf

# Production Config
BOT_TOKEN = "8695074642:AAF44kKVuUiD5x7SMtW5M_nygHMoTIS0H5g"
CHAT_ID = "1152142289"

STATE_FILE = "portfolio_state.json"
BROKERAGE_FEE = 40.0

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "tranche_level": 0,
        "entry_price": 0.0,
        "qty": 0,
        "status": "IDLE",
        "awaiting_qty": False,
        "trailing_sl": 0.0,
        "max_price_seen": 0.0,
        "last_alerted_price": 0.0,
        "tracked_entry_level": 0.0,
        "last_stage_alerted": ""
    }

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)

# --- 1. Web Server for Render 24/7 Keep-Alive ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Professional Quantitative Trading Terminal Live!")

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()

# --- 2. Reliable Telegram Messenger (Safe Delivery) ---
def send_telegram_msg(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": str(text), "parse_mode": "Markdown", "disable_web_page_preview": True}
    res = requests.post(url, json=payload, timeout=10)
    if res.status_code != 200:
        # Fallback to plain text if markdown formatting encounters issues
        payload_plain = {"chat_id": CHAT_ID, "text": str(text), "disable_web_page_preview": True}
        requests.post(url, json=payload_plain, timeout=10)

def send_alert_with_buttons(img_path, caption_text, tranche_next):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    keyboard = {
        "inline_keyboard": [
            [
                {"text": f"✅ Yes, Bought (Tranche {tranche_next})", "callback_data": f"bought_{tranche_next}"},
                {"text": "❌ Skip / Wait", "callback_data": "skip_entry"}
            ]
        ]
    }
    with open(img_path, 'rb') as photo:
        requests.post(url, data={
            'chat_id': CHAT_ID,
            'caption': caption_text,
            'reply_markup': json.dumps(keyboard)
        }, files={'photo': photo})

def generate_chart(df):
    chart_path = "chart.png"
    mpf.plot(df.tail(30), type='candle', style='charles', savefig=chart_path, volume=False)
    return chart_path

# --- 3. Mathematical Calculations ---
def calculate_vwap(df):
    try:
        typical_price = (df['High'] + df['Low'] + df['Close']) / 3
        volume = df['Volume'].replace(0, 1)
        vwap = (typical_price * volume).cumsum() / volume.cumsum()
        return float(vwap.iloc[-1])
    except Exception:
        return float(df['Close'].iloc[-1])

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1])

def detect_symbol(query):
    q = query.upper()
    common = {
        "WIPRO": ("WIPRO.NS", "WIPRO"),
        "RELIANCE": ("RELIANCE.NS", "RELIANCE"),
        "TCS": ("TCS.NS", "TCS"),
        "INFY": ("INFY.NS", "INFOSYS"),
        "HDFC": ("HDFCBANK.NS", "HDFC BANK"),
        "ICICI": ("ICICIBANK.NS", "ICICI BANK"),
        "SBIN": ("SBIN.NS", "SBI"),
        "NIFTY": ("NIFTYBEES.NS", "NIFTYBEES"),
        "NIFTYBEES": ("NIFTYBEES.NS", "NIFTYBEES")
    }
    for word, (sym, name) in common.items():
        if word in q:
            return sym, name
    return "NIFTYBEES.NS", "NIFTYBEES"

# --- 4. Institutional Demand Zone Engine ---
def calculate_trade_setup(symbol):
    ticker = yf.Ticker(symbol)
    df_1m = ticker.history(period="1d", interval="1m")
    df_15m = ticker.history(period="5d", interval="15m")
    df_1h = ticker.history(period="1mo", interval="60m")
    df_daily = ticker.history(period="2mo", interval="1d")

    curr_p = float(df_1m['Close'].iloc[-1])
    day_high = float(df_15m['High'].tail(25).max())
    day_low = float(df_1m['Low'].min())
    vwap_val = calculate_vwap(df_15m)
    rsi_15m = calculate_rsi(df_15m['Close'])

    # Key Support Structures
    prev_day_low = float(df_daily['Low'].iloc[-2]) if len(df_daily) >= 2 else day_low * 0.99
    swing_5d_low = float(df_15m['Low'].min())

    # Fibonacci 61.8% Golden Support
    high_month = float(df_1h['High'].max())
    low_month = float(df_1h['Low'].min())
    fib_618 = float(high_month - (0.618 * (high_month - low_month)))

    # Entry must strictly be below current market price (real discount)
    supports_below = [s for s in [prev_day_low, swing_5d_low, fib_618] if s < (curr_p - 0.25)]

    if supports_below:
        optimal_entry = round(max(supports_below), 2)
    else:
        # If asset is trading at fresh monthly low, calculate demand zone at 0.75% discount
        optimal_entry = round(curr_p * 0.9925, 2)

    diff_to_entry = round(curr_p - optimal_entry, 2)
    sl = round(optimal_entry * 0.992, 2)
    t1 = round(optimal_entry * 1.015, 2)
    t2 = round(optimal_entry * 1.025, 2)

    # Reversal confirmation check on 15m candle
    curr_c = df_15m.iloc[-1]
    prev_c = df_15m.iloc[-2]
    lower_wick = min(curr_c['Open'], curr_c['Close']) - curr_c['Low']
    body = abs(curr_c['Close'] - curr_c['Open'])
    has_wick_rejection = lower_wick > (body * 1.2)
    has_bull_close = curr_c['Close'] > prev_c['High']

    is_confirmed_reversal = (has_wick_rejection or has_bull_close) and (curr_p <= optimal_entry + 0.10)

    return {
        "curr_p": curr_p,
        "day_low": day_low,
        "day_high": day_high,
        "vwap": vwap_val,
        "rsi": rsi_15m,
        "optimal_entry": optimal_entry,
        "diff_to_entry": diff_to_entry,
        "sl": sl,
        "t1": t1,
        "t2": t2,
        "is_confirmed_reversal": is_confirmed_reversal
    }

def get_actionable_setup_card(user_query):
    target_sym, asset_name = detect_symbol(user_query)
    try:
        data = calculate_trade_setup(target_sym)
        state = load_state()
        state["tracked_entry_level"] = data["optimal_entry"]
        state["last_stage_alerted"] = ""
        save_state(state)

        # Action Verdict Logic
        if data["curr_p"] <= data["optimal_entry"] + 0.05:
            if data["is_confirmed_reversal"]:
                status_header = "🟢 **BUY SIGNAL ACTIVATED (REVERSAL CONFIRMED)**"
                action_text = (
                    f"✅ **Market ne support par bounce confirm kiya hai.**\n\n"
                    f"👉 **EXECUTE ORDER:** Buy at **₹{data['curr_p']:.2f}** (Tranche 1)\n"
                    f"🛑 **Stop-Loss:** ₹{data['sl']:.2f}\n"
                    f"🎯 **Target 1 (+1.5%):** ₹{data['t1']:.2f}\n"
                    f"🎯 **Target 2 (+2.5%):** ₹{data['t2']:.2f}"
                )
            else:
                status_header = "🟡 **IN DEMAND ZONE (AWAITING BOUNCE CANDLE)**"
                action_text = (
                    f"Price exact demand level par hai, lekin abhi girna ruka nahi hai.\n"
                    f"👉 Ek 15m green candle close hone ka wait karein ya limit order laga kar rakhein."
                )
        else:
            status_header = "⛔ **NO TRADE AT CURRENT PRICE (WAIT FOR DIP)**"
            action_text = (
                f"❌ **Current market price (₹{data['curr_p']:.2f}) par buy mat karein.**\n"
                f"Running price par buy karne se risk high hota hai.\n\n"
                f"📍 **Actionable Limit Order Level:** **₹{data['optimal_entry']:.2f}**\n"
                f"📏 **Required Dip:** Abhi **₹{data['diff_to_entry']:.2f}** ka dip baaki hai.\n\n"
                f"🎯 **Post-Entry Targets:**\n"
                f"• Target 1 (+1.5%): ₹{data['t1']:.2f}\n"
                f"• Target 2 (+2.5%): ₹{data['t2']:.2f}\n"
                f"• Invalidation SL: ₹{data['sl']:.2f}\n\n"
                f"💡 Broker terminal me **₹{data['optimal_entry']:.2f}** par GTT/Limit order place karein."
            )

        card = (
            f"🎯 *TRADE ORDER TICKET: {asset_name}*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"💰 *Live Price:* ₹{data['curr_p']:.2f}\n"
            f"📉 *Day Low:* ₹{data['day_low']:.2f} | 📈 *Day High:* ₹{data['day_high']:.2f}\n"
            f"📐 *VWAP:* ₹{data['vwap']:.2f} | ⚡ *15m RSI:* {data['rsi']:.1f}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"{status_header}\n\n"
            f"{action_text}\n"
            f"━━━━━━━━━━━━━━━━━━━"
        )
        return card

    except Exception as e:
        return f"⚠️ Calculation error: {str(e)}"

# --- 5. Interactive Telegram Listener ---
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
                        if data.startswith("bought_"):
                            t_num = int(data.split("_")[1])
                            try:
                                p = yf.Ticker("NIFTYBEES.NS").history(period="1d", interval="1m")['Close'].iloc[-1]
                            except Exception:
                                p = 280.0

                            state["tranche_level"] = t_num
                            state["temp_price"] = p
                            state["awaiting_qty"] = True
                            save_state(state)

                            send_telegram_msg(f"✅ *Tranche {t_num} Logged at ₹{p:.2f}!*\n\n👉 Reply me apni Quantity bhejein (e.g. `20`).")
                        elif data == "skip_entry":
                            state["status"] = "WAITING_STRONG"
                            save_state(state)
                            send_telegram_msg("👌 *Entry Skipped.* Bot waiting for next clean setup.")
                        elif data == "exit_trade":
                            state = {"tranche_level": 0, "entry_price": 0.0, "qty": 0, "status": "IDLE", "awaiting_qty": False, "trailing_sl": 0.0, "max_price_seen": 0.0, "last_alerted_price": 0.0, "tracked_entry_level": 0.0, "last_stage_alerted": ""}
                            save_state(state)
                            send_telegram_msg("🏁 *Position Closed.* Portfolio reset to 100% Cash.")

                    elif "message" in update and "text" in update["message"]:
                        msg_text = update["message"]["text"].strip()
                        state = load_state()

                        if state.get("awaiting_qty", False):
                            clean = msg_text.replace("/qty", "").strip()
                            if clean.isdigit() and int(clean) > 0:
                                qty = int(clean)
                                p = state.get("temp_price", 280.0)
                                prev_qty = state.get("qty", 0)
                                prev_price = state.get("entry_price", 0.0)

                                total_qty = prev_qty + qty
                                avg_price = ((prev_qty * prev_price) + (qty * p)) / total_qty if total_qty > 0 else p

                                state["qty"] = total_qty
                                state["entry_price"] = avg_price
                                state["max_price_seen"] = avg_price
                                state["status"] = "HOLDING"
                                state["awaiting_qty"] = False
                                save_state(state)

                                target_p = avg_price * 1.025
                                send_telegram_msg(
                                    f"💼 *POSITION RECORDED*\n"
                                    f"━━━━━━━━━━━━━━━━━━━\n"
                                    f"📦 Total Units: *{total_qty}*\n"
                                    f"💰 Net Avg Buy: *₹{avg_price:.2f}*\n"
                                    f"🎯 Profit Target (+2.5%): *₹{target_p:.2f}*\n"
                                    f"━━━━━━━━━━━━━━━━━━━"
                                )
                                continue

                        # Immediate Real Execution Card
                        card_response = get_actionable_setup_card(msg_text)
                        send_telegram_msg(card_response)

        except Exception:
            pass
        time.sleep(1)

# --- 6. Live Proximity & Autonomous Trade Execution Radar ---
def check_market():
    ist = pytz.timezone("Asia/Kolkata")
    send_telegram_msg("🚀 *Quantitative Order Execution Terminal Active!*\n• Strict Institutional Support Tracking\n• Real-Time Proximity Countdown Live.")

    while True:
        try:
            now = datetime.now(ist)

            # Market Hours: 9:15 AM - 3:30 PM (Mon-Fri)
            if now.weekday() < 5 and (now.hour > 9 or (now.hour == 9 and now.minute >= 15)) and (now.hour < 15 or (now.hour == 15 and now.minute <= 30)):
                etf = yf.Ticker("NIFTYBEES.NS")
                df_1m = etf.history(period="1d", interval="1m")
                df_15m = etf.history(period="5d", interval="15m")

                curr_p = float(df_1m['Close'].iloc[-1])
                vwap_val = calculate_vwap(df_15m)

                state = load_state()
                target_level = state.get("tracked_entry_level", 0.0)

                # Initialize optimal entry level if not tracked yet
                if target_level == 0.0:
                    data = calculate_trade_setup("NIFTYBEES.NS")
                    target_level = data["optimal_entry"]
                    state["tracked_entry_level"] = target_level
                    save_state(state)

                diff = round(curr_p - target_level, 2)
                last_stage = state.get("last_stage_alerted", "")

                # Proximity Countdown Alerts
                if 0.30 < diff <= 0.60 and last_stage != "STAGE_50":
                    state["last_stage_alerted"] = "STAGE_50"
                    save_state(state)
                    send_telegram_msg(
                        f"⚠️ *SUPPORT LEVEL APPROACHING*\n"
                        f"━━━━━━━━━━━━━━━━━━━\n"
                        f"💰 Current Price: *₹{curr_p:.2f}*\n"
                        f"🎯 Target Support: *₹{target_level:.2f}*\n"
                        f"📏 Abhi *₹{diff:.2f}* ka dip baaki hai. Broker terminal khol kar ready rahein."
                    )
                elif 0.05 < diff <= 0.30 and last_stage != "STAGE_20":
                    state["last_stage_alerted"] = "STAGE_20"
                    save_state(state)
                    send_telegram_msg(
                        f"🚨 *HIGH ALERT: VERY CLOSE TO ENTRY LEVEL*\n"
                        f"━━━━━━━━━━━━━━━━━━━\n"
                        f"💰 Current Price: *₹{curr_p:.2f}*\n"
                        f"🎯 Target Support: *₹{target_level:.2f}*\n"
                        f"📏 Sirf *₹{diff:.2f}* bacha hai! Limit order queue me daal sakte hain."
                    )
                elif diff <= 0.05 and last_stage != "TRIGGERED":
                    state["last_stage_alerted"] = "TRIGGERED"
                    save_state(state)
                    img = generate_chart(df_15m)
                    caption = (
                        f"🔥 *EXECUTE ORDER NOW (DEMAND LEVEL REACHED)!*\n"
                        f"━━━━━━━━━━━━━━━━━━━\n"
                        f"💰 Entry Price: *₹{curr_p:.2f}*\n"
                        f"🎯 Target 1 (+1.5%): *₹{(curr_p * 1.015):.2f}*\n"
                        f"🎯 Target 2 (+2.5%): *₹{(curr_p * 1.025):.2f}*\n"
                        f"🛑 Stop-Loss: *₹{(target_level * 0.992):.2f}*\n"
                        f"👉 Action: Buy Tranche 1 (20% Capital)"
                    )
                    send_alert_with_buttons(img, caption, 1)

                # Profit Booking Notification (+2.5%)
                if state.get("status") == "HOLDING" and state.get("qty", 0) > 0:
                    entry_p = state["entry_price"]
                    qty = state["qty"]
                    net_pnl = ((curr_p - entry_p) * qty) - BROKERAGE_FEE
                    net_return_pct = (net_pnl / (entry_p * qty)) * 100

                    if net_return_pct >= 2.5:
                        exit_kb = {"inline_keyboard": [[{"text": "🏁 Book Full Profit", "callback_data": "exit_trade"}]]}
                        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={
                            "chat_id": CHAT_ID,
                            "text": f"🎉 *TARGET HIT (+2.5%)*\nSell Price: ₹{curr_p:.2f} | Net Realized: *₹{net_pnl:+.2f}*",
                            "parse_mode": "Markdown",
                            "reply_markup": json.dumps(exit_kb)
                        })

            time.sleep(20)
        except Exception:
            time.sleep(15)

if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    threading.Thread(target=telegram_listener, daemon=True).start()
    check_market()
