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

# --- 1. Web Server for Render 24/7 ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Quantitative Sniper Terminal Active!")

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()

# --- 2. Telegram Messengers ---
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

# --- 3. Indicators ---
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

# --- 4. High-Conviction Quantitative Action Plan ---
def get_actionable_analysis(user_query):
    target_sym, asset_name = detect_symbol(user_query)
    try:
        ticker = yf.Ticker(target_sym)
        df_1m = ticker.history(period="1d", interval="1m")
        df_15m = ticker.history(period="5d", interval="15m")
        df_1h = ticker.history(period="1mo", interval="60m")

        if df_1m.empty or df_15m.empty or df_1h.empty:
            return f"⚠️ {asset_name} ka live data fetch nahi ho raha."

        curr_p = float(df_1m['Close'].iloc[-1])
        day_low = float(df_1m['Low'].min())
        day_high = float(df_1m['High'].max())
        drop_pct = ((day_high - curr_p) / day_high) * 100
        vwap_val = calculate_vwap(df_15m)
        rsi_15m = calculate_rsi(df_15m['Close'])

        # Fibonacci calculation on 1h swing
        h_1h = float(df_1h['High'].max())
        l_1h = float(df_1h['Low'].min())
        fib_618 = h_1h - (0.618 * (h_1h - l_1h))
        fib_500 = h_1h - (0.500 * (h_1h - l_1h))

        # Direct High-Probability Setup Rules
        # Rule 1: Dip Setup Activated (Price near day low or 61.8% Fibo AND RSI <= 35)
        is_buy_ready = (rsi_15m <= 35) or (curr_p <= fib_618) or (curr_p <= day_low * 1.002 and curr_p < vwap_val)

        if is_buy_ready:
            signal_status = "🟢 BUY SETUP ACTIVE (SNIPER ENTRY)"
            exact_buy = f"₹{curr_p:.2f} (Ya Limit Order ₹{day_low:.2f})"
            target_1 = curr_p * 1.015
            target_2 = curr_p * 1.025
            sl_price = day_low * 0.993
            action_direct = (
                f"✅ **ABHI BUY KAREIN (Tranche 1 - 20% Capital)**\n"
                f"• Entry Price: **₹{curr_p:.2f}**\n"
                f"• Target 1 (+1.5%): **₹{target_1:.2f}**\n"
                f"• Target 2 (+2.5%): **₹{target_2:.2f}**\n"
                f"• Strict Stop-Loss: **₹{sl_price:.2f}**"
            )
        elif curr_p > vwap_val and rsi_15m >= 65:
            signal_status = "🔴 OVERBOUGHT ZONE (DO NOT BUY)"
            exact_buy = f"Wait for Pullback near ₹{vwap_val:.2f}"
            action_direct = (
                f"⛔ **ABHI ENTRY MAT LO** (Top pe buy karke fasne ka risk hai).\n"
                f"👉 Pullback aane par **₹{vwap_val:.2f}** ke pass entry banegi."
            )
        else:
            signal_status = "⏳ WAITING FOR HIGH-PROBABILITY DIP"
            # Optimal trigger level jahan buying banti hai
            ideal_entry = min(vwap_val * 0.995, max(fib_618, day_low))
            target_calc = ideal_entry * 1.025
            action_direct = (
                f"⏸️ **MARKET IN-BETWEEN HAI (Wait Karein)**\n"
                f"👉 Setup banne ke liye Limit Order lagayein: **₹{ideal_entry:.2f}**\n"
                f"🎯 Wahan se Expected Target (+2.5%): **₹{target_calc:.2f}**\n"
                f"💡 Current price (₹{curr_p:.2f}) se ₹{abs(curr_p - ideal_entry):.2f} ka dip aane par buy trigger hoga."
            )

        card = (
            f"🎯 *{asset_name} ACTIONABLE SETUP CARD*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"💰 *Current Price:* ₹{curr_p:.2f}\n"
            f"📉 *Day Low:* ₹{day_low:.2f} | 📈 *Day High:* ₹{day_high:.2f}\n"
            f"📊 *VWAP (Discount Benchmark):* ₹{vwap_val:.2f}\n"
            f"⚡ *15m RSI:* {rsi_15m:.1f} | *61.8% Support:* ₹{fib_618:.2f}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🚨 *STATUS:* {signal_status}\n\n"
            f"{action_direct}\n"
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

                        # Direct execution card
                        card_response = get_actionable_analysis(msg_text)
                        send_telegram_msg(card_response)

        except Exception:
            pass
        time.sleep(1)

# --- 6. Live Auto-Dip & Price Tracker ---
def check_market():
    last_reported_drop = 0
    ist = pytz.timezone("Asia/Kolkata")

    send_telegram_msg("🚀 *Sniper Quantitative Terminal Live!*\n• Direct Buy / Target / SL Setup Enabled\n• Send stock name anytime for exact level.")

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

                # Confluence Dip Buy Triggers
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
                        f"🚨 *BUY TRIGGER (CONFLUENCE DIP)*\n"
                        f"━━━━━━━━━━━━━━━━━━━\n"
                        f"💰 *Entry Price:* ₹{curr_price:.2f}\n"
                        f"🎯 *Target (+2.5%):* ₹{(curr_price*1.025):.2f}\n"
                        f"🛡️ *Stop-Loss:* ₹{(day_low*0.993):.2f}\n"
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
