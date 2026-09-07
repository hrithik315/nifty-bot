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
        "last_alerted_price": 0.0
    }

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)

# --- 1. Render Keep-Alive Web Server ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Professional Price Action Terminal Active!")

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()

# --- 2. Reliable Telegram Messenger ---
def send_telegram_msg(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": str(text), "parse_mode": "Markdown", "disable_web_page_preview": True}
    res = requests.post(url, json=payload, timeout=10)
    if res.status_code != 200:
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

# --- 3. Indicators & Math ---
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

# --- 4. Professional Trader Reversal Setup Engine ---
def analyze_trader_setup(user_query):
    target_sym, asset_name = detect_symbol(user_query)
    try:
        ticker = yf.Ticker(target_sym)
        df_15m = ticker.history(period="5d", interval="15m")
        df_1h = ticker.history(period="1mo", interval="60m")
        df_1d = ticker.history(period="3mo", interval="1d")

        if df_15m.empty or df_1h.empty:
            return f"⚠️ {asset_name} ka market data abhi live nahi hai."

        # Current & Previous Candles (15-min)
        curr_c = df_15m.iloc[-1]
        prev_c = df_15m.iloc[-2]

        curr_p = float(curr_c['Close'])
        day_low = float(df_15m['Low'].tail(25).min())
        day_high = float(df_15m['High'].tail(25).max())
        vwap_val = calculate_vwap(df_15m)
        rsi_15m = calculate_rsi(df_15m['Close'])

        # Structure: 1-Hour Fibonacci Golden Pocket
        h_1h = float(df_1h['High'].max())
        l_1h = float(df_1h['Low'].min())
        diff_1h = h_1h - l_1h
        fib_618 = float(h_1h - (0.618 * diff_1h))
        fib_500 = float(h_1h - (0.500 * diff_1h))

        # Price Action Reversal Rules:
        # 1. Price is in value discount (near day low, below VWAP, or at 61.8% Fibo)
        in_value_zone = (curr_p <= vwap_val) or (curr_p <= fib_618 * 1.005) or (curr_p <= day_low * 1.004)
        
        # 2. Bullish Reversal Trigger (Hammer wick OR Green candle breaking previous candle high)
        lower_wick = min(curr_c['Open'], curr_c['Close']) - curr_c['Low']
        candle_body = abs(curr_c['Close'] - curr_c['Open'])
        is_hammer = lower_wick > (candle_body * 1.5) and (curr_c['Close'] >= curr_c['Open'])
        is_bullish_break = (curr_c['Close'] > prev_c['High']) and (curr_c['Close'] > curr_c['Open'])
        reversal_confirmed = is_hammer or is_bullish_break

        # Setup Verdict Decision Tree
        if in_value_zone and (reversal_confirmed or rsi_15m <= 32):
            pattern_name = "Bullish Hammer Reversal" if is_hammer else "Support Breakout Candle"
            stop_loss = float(day_low * 0.993)
            risk = curr_p - stop_loss
            t1 = float(curr_p + (risk * 1.5))
            t2 = float(curr_p + (risk * 2.5))

            card = (
                f"🔥 *EXECUTION ORDER: {asset_name} BUY SETUP*\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"📍 *Setup Type:* {pattern_name} at Value Support\n"
                f"💰 *Current Price:* ₹{curr_p:.2f}\n"
                f"🛡️ *Confirmed Support Level:* ₹{day_low:.2f}\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"🎯 *EXACT ORDER TICKET (Tranche 1):*\n"
                f"👉 **BUY NOW / LIMIT ORDER:** ₹{curr_p:.2f}\n"
                f"🛑 **STRICT STOP-LOSS:** ₹{stop_loss:.2f} (Risk: ₹{risk:.2f}/share)\n"
                f"🎯 **TARGET 1 (1:1.5 RR):** ₹{t1:.2f}\n"
                f"🎯 **TARGET 2 (1:2.5 RR):** ₹{t2:.2f}\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"💡 *Logic:* Price discount zone me girna band hua hai aur buyers ne wick reject kar diya hai."
            )
        elif curr_p > vwap_val and rsi_15m >= 65:
            card = (
                f"⛔ *NO TRADE ZONE: {asset_name} OVEREXTENDED*\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"💰 *Price:* ₹{curr_p:.2f} | *VWAP:* ₹{vwap_val:.2f}\n"
                f"⚡ *15m RSI:* {rsi_15m:.1f} (Overbought / Resistance)\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"❌ **Yahan Buy Mat Karein** (Top pe buy karke trap hone ka khatra hai).\n"
                f"⏳ **Re-entry Level:** Pullback ka wait karein jab tak price **₹{vwap_val:.2f}** ke pass na aaye."
            )
        else:
            # Reversal pending - Give exact limit orders where to buy
            best_entry = round(max(fib_618, day_low), 2)
            expected_sl = round(best_entry * 0.993, 2)
            expected_target = round(best_entry * 1.025, 2)
            diff_from_entry = round(curr_p - best_entry, 2)

            card = (
                f"⏳ *WAITING FOR REVERSAL SETUP: {asset_name}*\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"💰 *Live Price:* ₹{curr_p:.2f} | *Day Low:* ₹{day_low:.2f}\n"
                f"📐 *VWAP:* ₹{vwap_val:.2f} | *61.8% Fibo Pocket:* ₹{fib_618:.2f}\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"🔍 **TRADER'S ACTION PLAN:**\n"
                f"Abhi price beech me float ho rahi hai (No edge).\n\n"
                f"👉 **SETUP ENTRY LEVEL:** **₹{best_entry:.2f}**\n"
                f"• Current price se dip required: **₹{diff_from_entry:.2f}**\n"
                f"• Us level par aane ke baad Target: **₹{expected_target:.2f} (+2.5%)**\n"
                f"• Invalidation / SL: **₹{expected_sl:.2f}**\n\n"
                f"💡 Broker terminal me **₹{best_entry:.2f}** ka GTT ya Limit Order laga kar chod dein."
            )

        return card

    except Exception as e:
        return f"⚠️ Setup calculation error: {str(e)}"

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

                            send_telegram_msg(f"✅ *Tranche {t_num} Logged at ₹{p:.2f}!*\n\n👉 Quantity reply karein (e.g. `25`).")
                        elif data == "skip_entry":
                            state["status"] = "WAITING_STRONG"
                            save_state(state)
                            send_telegram_msg("👌 *Entry Skipped.* Sniper scanner waiting for optimal price.")
                        elif data == "exit_trade":
                            state = {"tranche_level": 0, "entry_price": 0.0, "qty": 0, "status": "IDLE", "awaiting_qty": False, "trailing_sl": 0.0, "max_price_seen": 0.0, "last_alerted_price": 0.0}
                            save_state(state)
                            send_telegram_msg("🏁 *Position Closed.* Capital 100% Free.")

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
                                    f"📦 Units: *{total_qty}*\n"
                                    f"💰 Avg Buy: *₹{avg_price:.2f}*\n"
                                    f"🎯 Profit Target (+2.5%): *₹{target_p:.2f}*\n"
                                    f"━━━━━━━━━━━━━━━━━━━"
                                )
                                continue

                        # Real-time Trade Ticket
                        response_card = analyze_trader_setup(msg_text)
                        send_telegram_msg(response_card)

        except Exception:
            pass
        time.sleep(1)

# --- 6. Live Auto-Dip & Price Tracker ---
def check_market():
    last_reported_drop = 0
    ist = pytz.timezone("Asia/Kolkata")

    send_telegram_msg("🚀 *Professional Quantitative Terminal Active!*\n• Price Action Reversal Detector Online\n• Exact Buy, SL & Target Tickets ready.")

    while True:
        try:
            now = datetime.now(ist)

            if now.weekday() < 5 and (now.hour > 9 or (now.hour == 9 and now.minute >= 15)) and (now.hour < 15 or (now.hour == 15 and now.minute <= 30)):
                etf = yf.Ticker("NIFTYBEES.NS")
                df_1m = etf.history(period="1d", interval="1m")
                df_15m = etf.history(period="5d", interval="15m")

                curr_price = float(df_1m['Close'].iloc[-1])
                day_high = float(df_15m['High'].max())
                day_low = float(df_1m['Low'].min())
                drop_pct = ((day_high - curr_price) / day_high) * 100
                vwap_val = calculate_vwap(df_15m)
                rsi_15m = calculate_rsi(df_15m['Close'])

                state = load_state()
                last_price = state.get("last_alerted_price", 0.0)

                # Real-Time Price Movement Alerts (₹1.0 threshold)
                if last_price == 0.0:
                    state["last_alerted_price"] = curr_price
                    save_state(state)
                elif abs(curr_price - last_price) >= 1.0:
                    diff = curr_price - last_price
                    icon = "📈" if diff > 0 else "📉"
                    direction = "UP" if diff > 0 else "DOWN"

                    pos_msg = "Cash Free"
                    if state.get("status") == "HOLDING" and state.get("qty", 0) > 0:
                        e = state["entry_price"]
                        pnl = ((curr_price - e) * state["qty"]) - BROKERAGE_FEE
                        pos_msg = f"Holding {state['qty']} @ ₹{e:.2f} | P&L: ₹{pnl:+.2f}"

                    send_telegram_msg(
                        f"{icon} *PRICE MOVEMENT TICK*\n"
                        f"💰 Current: *₹{curr_price:.2f}* (Low: ₹{day_low:.2f})\n"
                        f"🔄 Shift: {direction} from ₹{last_price:.2f} ({diff:+.2f})\n"
                        f"📊 15m RSI: *{rsi_15m:.1f}* | VWAP: *₹{vwap_val:.2f}*\n"
                        f"💼 Position: {pos_msg}"
                    )
                    state["last_alerted_price"] = curr_price
                    save_state(state)

                # Profit Booking Notification (+2.5%)
                if state.get("status") == "HOLDING" and state.get("qty", 0) > 0:
                    entry_p = state["entry_price"]
                    qty = state["qty"]
                    net_pnl = ((curr_price - entry_p) * qty) - BROKERAGE_FEE
                    net_return_pct = (net_pnl / (entry_p * qty)) * 100

                    if net_return_pct >= 2.5:
                        exit_kb = {"inline_keyboard": [[{"text": "🏁 Book Full Profit", "callback_data": "exit_trade"}]]}
                        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={
                            "chat_id": CHAT_ID,
                            "text": f"🎉 *TARGET HIT (+2.5%)*\nSell: ₹{curr_price:.2f} | Net Profit: *₹{net_pnl:+.2f}*",
                            "parse_mode": "Markdown",
                            "reply_markup": json.dumps(exit_kb)
                        })

                # Confluence Reversal Dip Alert
                should_alert = False
                target_tranche = 1
                alloc_text = "Deploy 20% Capital (Tranche 1)"

                if state.get("status") == "IDLE":
                    if drop_pct >= 1.0 and drop_pct >= last_reported_drop + 1.0:
                        should_alert = True
                        target_tranche = 1
                elif state.get("status") == "HOLDING":
                    curr_tranche = state.get("tranche_level", 1)
                    entry_p = state.get("entry_price", curr_price)
                    fall = ((entry_p - curr_price) / entry_p) * 100
                    if curr_tranche == 1 and fall >= 1.5 and (drop_pct >= last_reported_drop + 1.0):
                        should_alert = True
                        target_tranche = 2
                        alloc_text = f"Averaging Tranche 2 (-{fall:.1f}% from entry)"

                if should_alert:
                    last_reported_drop = int(drop_pct)
                    img = generate_chart(df_15m)
                    caption = (
                        f"🚨 *REVERSAL DIP DETECTED*\n"
                        f"━━━━━━━━━━━━━━━━━━━\n"
                        f"💰 *Entry:* ₹{curr_price:.2f}\n"
                        f"🛑 *Stop-Loss:* ₹{(day_low*0.993):.2f}\n"
                        f"🎯 *Target (+2.5%):* ₹{(curr_price*1.025):.2f}\n"
                        f"👉 *Action:* {alloc_text}"
                    )
                    send_alert_with_buttons(img, caption, target_tranche)

            time.sleep(30)
        except Exception:
            time.sleep(15)

if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    threading.Thread(target=telegram_listener, daemon=True).start()
    check_market()
