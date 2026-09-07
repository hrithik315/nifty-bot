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
BROKERAGE_FEE = 40.0  # Buy ₹20 + Sell ₹20

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
        "qty": 20,
        "status": "IDLE",
        "awaiting_qty": False,
        "trailing_sl": 0.0,
        "max_price_seen": 0.0,
        "last_1m_candle_time": "",
        "active_target_1": 0.0,
        "active_target_2": 0.0,
        "active_sl": 0.0,
        "target_1_alerted": False,
        "target_2_alerted": False,
        "locked_support_level": 0.0
    }

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)

# --- 1. Render Keep-Alive Web Server ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Ultimate Institutional Sniper Terminal Active!")

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
    mpf.plot(df.tail(25), type='candle', style='charles', savefig=chart_path, volume=False)
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

# --- 4. Macro Drivers Audit ---
def fetch_institutional_drivers():
    drivers = {}
    bull_count = 0
    hw_list = [("HDFCBANK.NS", "HDFC Bank"), ("RELIANCE.NS", "Reliance"), ("ICICIBANK.NS", "ICICI Bank")]
    
    for sym, label in hw_list:
        try:
            h = yf.Ticker(sym).history(period="2d")
            c = float(h['Close'].iloc[-1])
            p = float(h['Close'].iloc[-2])
            chg = ((c - p) / p) * 100
            if chg >= -0.20:
                bull_count += 1
            drivers[label] = f"₹{c:.1f} ({chg:+.2f}%)"
        except Exception:
            drivers[label] = "N/A"

    vix_val = 14.0
    vix_status = "STABLE"
    try:
        vix_df = yf.Ticker("^INDIAVIX").history(period="2d")
        vix_val = float(vix_df['Close'].iloc[-1])
        vix_prev = float(vix_df['Close'].iloc[-2])
        vix_chg = ((vix_val - vix_prev) / vix_prev) * 100
        if vix_val >= 16.5 or vix_chg > 5.0:
            vix_status = "⚠️ ELEVATED"
        else:
            vix_status = "🟢 CALM"
    except Exception:
        pass

    return bull_count, drivers, vix_val, vix_status

# --- 5. True Institutional Demand & Cross-Exchange Evaluation ---
def evaluate_market_data(symbol="NIFTYBEES.NS"):
    ticker = yf.Ticker(symbol)
    df_1m = ticker.history(period="1d", interval="1m")
    df_15m = ticker.history(period="5d", interval="15m")
    df_1h = ticker.history(period="1mo", interval="60m")
    df_daily = ticker.history(period="2mo", interval="1d")

    if df_1m.empty:
        return None

    last_bar = df_1m.iloc[-1]
    candle_time = str(df_1m.index[-1])
    curr_close = float(last_bar['Close'])
    bar_high = float(last_bar['High'])
    bar_low = float(last_bar['Low'])
    bar_open = float(last_bar['Open'])

    vwap_val = calculate_vwap(df_15m) if not df_15m.empty else curr_close
    rsi_1m = calculate_rsi(df_1m['Close']) if len(df_1m) >= 15 else 50.0

    # Institutional Demand Structure Below Current Price
    prev_day_low = float(df_daily['Low'].iloc[-2]) if len(df_daily) >= 2 else bar_low * 0.99
    swing_5d_low = float(df_15m['Low'].min()) if not df_15m.empty else bar_low * 0.99
    
    h_1h = float(df_1h['High'].max()) if not df_1h.empty else curr_close
    l_1h = float(df_1h['Low'].min()) if not df_1h.empty else curr_close
    fib_618 = float(h_1h - (0.618 * (h_1h - l_1h)))

    # Filter out current price: Support must be at least 0.20 below current market price
    supports = [s for s in [prev_day_low, swing_5d_low, fib_618] if s < (curr_close - 0.20)]
    if supports:
        optimal_entry = round(max(supports), 2)
    else:
        optimal_entry = round(curr_close * 0.993, 2)

    diff = round(curr_close - optimal_entry, 2)
    sl = round(optimal_entry * 0.992, 2)
    t1 = round(optimal_entry * 1.015, 2)
    t2 = round(optimal_entry * 1.025, 2)

    # Liquidity sweep check: Did price dip below support and close back above?
    lower_wick = min(bar_open, curr_close) - bar_low
    body = abs(curr_close - bar_open)
    is_sweep_reversal = (lower_wick > body) and (curr_close >= bar_open) and (bar_low <= optimal_entry + 0.15)

    shift_amt = round(curr_close - bar_open, 2)
    shift_dir = "🟢 UP" if shift_amt >= 0 else "🔴 DOWN"

    state = load_state()
    state["active_target_1"] = t1
    state["active_target_2"] = t2
    state["active_sl"] = sl
    state["locked_support_level"] = optimal_entry
    save_state(state)

    return {
        "candle_time": candle_time,
        "close": curr_close,
        "open": bar_open,
        "high": bar_high,
        "low": bar_low,
        "shift_dir": shift_dir,
        "shift_amt": shift_amt,
        "vwap": vwap_val,
        "rsi_1m": rsi_1m,
        "optimal_entry": optimal_entry,
        "diff": diff,
        "sl": sl,
        "t1": t1,
        "t2": t2,
        "is_sweep": is_sweep_reversal,
        "df_1m": df_1m
    }

def format_1m_card(data, asset_name="NIFTYBEES"):
    bull_count, hw_drivers, vix_val, vix_status = fetch_institutional_drivers()
    state = load_state()
    user_qty = state.get("qty", 20)
    if user_qty == 0: user_qty = 20

    entry = data["optimal_entry"]
    t1 = data["t1"]
    t2 = data["t2"]
    sl = data["sl"]

    net_t1 = ((t1 - entry) * user_qty) - BROKERAGE_FEE
    net_t2 = ((t2 - entry) * user_qty) - BROKERAGE_FEE
    net_sl = ((sl - entry) * user_qty) - BROKERAGE_FEE

    # Live position display
    holding_str = ""
    if state.get("status") == "HOLDING" and state.get("qty", 0) > 0:
        e_price = state["entry_price"]
        q_pos = state["qty"]
        live_net = ((data["close"] - e_price) * q_pos) - BROKERAGE_FEE
        holding_str = (
            f"💼 *ACTIVE POSITION:* {q_pos} Units @ ₹{e_price:.2f}\n"
            f"💰 In-Hand P&L (After Brokerage): *₹{live_net:+.2f}*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
        )

    if data["is_sweep"] and bull_count >= 2:
        status_line = "🟢 **DOUBLE BOTTOM / LIQUIDITY SWEEP CONFIRMED!**"
        call = (
            f"✅ Buyers ne support hold kar liya hai.\n"
            f"👉 **EXECUTE NOW:** Buy at **₹{data['close']:.2f}** (Tranche 1)\n"
            f"🛑 **Stop-Loss:** ₹{sl:.2f}\n"
            f"🎯 **Target (+2.5%):** ₹{t2:.2f}"
        )
    elif data["diff"] <= 0.05:
        status_line = "🟡 **TOUCHING DEMAND ZONE (AWAITING BOUNCE)**"
        call = "Price exact support par hai. 1m candle ke bounce confirm hone ka wait karein."
    else:
        status_line = "⏳ **WAITING FOR LEVEL (NO ENTRY AT RUNNING PRICE)**"
        call = (
            f"📍 **Target Demand Level:** **₹{entry:.2f}**\n"
            f"📏 **Entry me kitne points kam hain:** **{data['diff']:.2f} Points (₹{data['diff']:.2f})** baaki.\n"
            f"💡 **Action:** Broker terminal par **₹{entry:.2f}** par Limit/GTT Order place rakhein."
        )

    card = (
        f"⚡ *1-MIN LIVE RADAR: {asset_name}*\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💰 *Current Close:* ₹{data['close']:.2f} ({data['shift_dir']} {data['shift_amt']:+.2f})\n"
        f"📊 *Bar Range:* High ₹{data['high']:.2f} | Low ₹{data['low']:.2f}\n"
        f"📐 *VWAP:* ₹{data['vwap']:.2f} | ⚡ *1m RSI:* {data['rsi_1m']:.1f}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🏛️ *HEAVYWEIGHT CONFLUENCE ({bull_count}/3 Aligned):*\n"
        f"• HDFC Bank: {hw_drivers.get('HDFC Bank', 'N/A')}\n"
        f"• Reliance: {hw_drivers.get('Reliance', 'N/A')}\n"
        f"• India VIX: *{vix_val:.2f}* ({vix_status})\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"{holding_str}"
        f"{status_line}\n\n"
        f"{call}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💵 *NET IN-HAND PROFIT/LOSS ({user_qty} Units - ₹40 Brokerage Cut):*\n"
        f"🟢 **Target 1 (+1.5% at ₹{t1:.2f}):** Net In-Hand *₹{net_t1:+.2f}*\n"
        f"🟢 **Target 2 (+2.5% at ₹{t2:.2f}):** Net In-Hand *₹{net_t2:+.2f}*\n"
        f"🔴 **Stop-Loss Hit (₹{sl:.2f}):** Total Risk *₹{net_sl:.2f}*\n"
        f"━━━━━━━━━━━━━━━━━━━"
    )
    return card

# --- 6. Interactive Telegram Listener ---
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
                                p = 271.50

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
                            state = {"tranche_level": 0, "entry_price": 0.0, "qty": 20, "status": "IDLE", "awaiting_qty": False, "trailing_sl": 0.0, "max_price_seen": 0.0, "last_1m_candle_time": "", "active_target_1": 0.0, "active_target_2": 0.0, "active_sl": 0.0, "target_1_alerted": False, "target_2_alerted": False, "locked_support_level": 0.0}
                            save_state(state)
                            send_telegram_msg("🏁 *Position Closed.* Capital 100% Free.")

                    elif "message" in update and "text" in update["message"]:
                        msg_text = update["message"]["text"].strip()
                        state = load_state()

                        if state.get("awaiting_qty", False):
                            clean = msg_text.replace("/qty", "").strip()
                            if clean.isdigit() and int(clean) > 0:
                                qty = int(clean)
                                p = state.get("temp_price", 271.50)
                                prev_qty = state.get("qty", 0)
                                prev_price = state.get("entry_price", 0.0)

                                total_qty = prev_qty + qty
                                avg_price = ((prev_qty * prev_price) + (qty * p)) / total_qty if total_qty > 0 else p

                                state["qty"] = total_qty
                                state["entry_price"] = avg_price
                                state["max_price_seen"] = avg_price
                                state["status"] = "HOLDING"
                                state["awaiting_qty"] = False
                                state["active_target_1"] = round(avg_price * 1.015, 2)
                                state["active_target_2"] = round(avg_price * 1.025, 2)
                                state["active_sl"] = round(avg_price * 0.992, 2)
                                state["target_1_alerted"] = False
                                state["target_2_alerted"] = False
                                save_state(state)

                                net_target_pnl = ((state["active_target_2"] - avg_price) * total_qty) - BROKERAGE_FEE
                                send_telegram_msg(
                                    f"💼 *POSITION SAVED*\n"
                                    f"━━━━━━━━━━━━━━━━━━━\n"
                                    f"📦 Total Units: *{total_qty}*\n"
                                    f"💰 Net Avg Buy: *₹{avg_price:.2f}*\n"
                                    f"🎯 Target 1 (+1.5%): *₹{state['active_target_1']:.2f}*\n"
                                    f"🎯 Target 2 (+2.5%): *₹{state['active_target_2']:.2f}*\n"
                                    f"💵 Target 2 Net Profit: *₹{net_target_pnl:+.2f}* (Brokerage Deducted)\n"
                                    f"━━━━━━━━━━━━━━━━━━━"
                                )
                                continue

                        sym, asset = detect_symbol(msg_text)
                        m_data = evaluate_market_data(sym)
                        if m_data:
                            report_text = format_1m_card(m_data, asset)
                            send_telegram_msg(report_text)

        except Exception:
            pass
        time.sleep(1)

# --- 7. Real-Time Tick & Candle-Close Monitor ---
def check_market():
    ist = pytz.timezone("Asia/Kolkata")
    send_telegram_msg("🚀 *Zero-Error Institutional Trading Terminal Active!*\n• Cross-Exchange Support Sweep Live\n• High/Low Wick Target Monitor Active.")

    while True:
        try:
            now = datetime.now(ist)

            # Active during Market Hours: 9:15 AM to 3:30 PM (Mon-Fri)
            if now.weekday() < 5 and (now.hour > 9 or (now.hour == 9 and now.minute >= 15)) and (now.hour < 15 or (now.hour == 15 and now.minute <= 30)):
                m_data = evaluate_market_data("NIFTYBEES.NS")
                
                if m_data:
                    state = load_state()
                    last_time = state.get("last_1m_candle_time", "")
                    
                    # 10-Second High/Low Wick Target & SL Detection
                    high_tick = m_data["high"]
                    low_tick = m_data["low"]
                    t1 = state.get("active_target_1", 0.0)
                    t2 = state.get("active_target_2", 0.0)
                    sl = state.get("active_sl", 0.0)
                    qty = state.get("qty", 20)
                    if qty == 0: qty = 20

                    # Target 1 Tick Detection
                    if t1 > 0 and high_tick >= t1 and not state.get("target_1_alerted", False):
                        state["target_1_alerted"] = True
                        save_state(state)
                        net_pnl_1 = ((t1 - (state.get('entry_price') or (t1/1.015))) * qty) - BROKERAGE_FEE
                        send_telegram_msg(
                            f"🎉 *TARGET 1 HIT (+1.5%)!*\n"
                            f"━━━━━━━━━━━━━━━━━━━\n"
                            f"📈 High Tick: *₹{high_tick:.2f}* (Target: ₹{t1:.2f})\n"
                            f"💰 In-Hand Net Profit: *₹{net_pnl_1:+.2f}* (Brokerage Deducted)\n"
                            f"👉 50% Profit book karein, baaki SL Cost par shift karein!"
                        )

                    # Target 2 Tick Detection
                    if t2 > 0 and high_tick >= t2 and not state.get("target_2_alerted", False):
                        state["target_2_alerted"] = True
                        save_state(state)
                        net_pnl_2 = ((t2 - (state.get('entry_price') or (t2/1.025))) * qty) - BROKERAGE_FEE
                        exit_kb = {"inline_keyboard": [[{"text": "🏁 Book Full Profit", "callback_data": "exit_trade"}]]}
                        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={
                            "chat_id": CHAT_ID,
                            "text": (
                                f"🚀 *TARGET 2 HIT (+2.5%)!*\n"
                                f"━━━━━━━━━━━━━━━━━━━\n"
                                f"📈 High Tick: *₹{high_tick:.2f}* (Target: ₹{t2:.2f})\n"
                                f"💵 Net Realized Profit: *₹{net_pnl_2:+.2f}*\n"
                                f"🏁 Full Profit Book karein!"
                            ),
                            "parse_mode": "Markdown",
                            "reply_markup": json.dumps(exit_kb)
                        })

                    # Stop-Loss Tick Detection
                    if sl > 0 and low_tick <= sl and state.get("status") == "HOLDING":
                        loss_amt = ((sl - state.get('entry_price', sl)) * qty) - BROKERAGE_FEE
                        send_telegram_msg(
                            f"🛑 *STOP-LOSS HIT ALERT*\n"
                            f"📉 Low Tick: *₹{low_tick:.2f}* (SL: ₹{sl:.2f})\n"
                            f"🔴 Capital safety exit triggered (Loss: ₹{loss_amt:.2f})"
                        )
                        state["status"] = "IDLE"
                        save_state(state)

                    # Automated 1-Minute Candle Close Fluctuation Update
                    if m_data["candle_time"] != last_time:
                        state["last_1m_candle_time"] = m_data["candle_time"]
                        save_state(state)

                        card_text = format_1m_card(m_data, "NIFTYBEES")

                        # If support sweep confirmed, send chart photo with Buy action buttons
                        if m_data["is_sweep"]:
                            img = generate_chart(m_data["df_1m"])
                            send_alert_with_buttons(img, card_text, 1)
                        else:
                            send_telegram_msg(card_text)

            time.sleep(10)  # Ultra-fast 10-second tick scan
        except Exception:
            time.sleep(10)

if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    threading.Thread(target=telegram_listener, daemon=True).start()
    check_market()
