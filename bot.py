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
        "qty": 75,
        "status": "IDLE",
        "awaiting_qty": False,
        "entry_time": "",
        "active_target_1": 0.0,
        "active_target_2": 0.0,
        "active_sl": 0.0,
        "target_1_alerted": False,
        "target_2_alerted": False,
        "last_1m_candle_time": ""
    }

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)

# --- 1. Web Server for Render Keep-Alive ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Market Structure Orderflow Engine Active!")

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()

# --- 2. Telegram Messenger ---
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
                {"text": f"✅ Buy Tranche {tranche_next} (Structure Confirmed)", "callback_data": f"bought_{tranche_next}"},
                {"text": "❌ Skip", "callback_data": "skip_entry"}
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
    mpf.plot(df.tail(30), type='candle', style='charles', savefig=chart_path, volume=True)
    return chart_path

# --- 3. Institutional Heavyweight Engine ---
def fetch_heavyweight_engine():
    drivers = {}
    bull_score = 0
    hw_list = [("HDFCBANK.NS", "HDFC Bank"), ("RELIANCE.NS", "Reliance"), ("ICICIBANK.NS", "ICICI Bank")]
    
    for sym, label in hw_list:
        try:
            h = yf.Ticker(sym).history(period="2d")
            c = float(h['Close'].iloc[-1])
            p = float(h['Close'].iloc[-2])
            chg = ((c - p) / p) * 100
            if chg >= -0.15:
                bull_score += 1
            drivers[label] = f"₹{c:.1f} ({chg:+.2f}%)"
        except Exception:
            drivers[label] = "N/A"

    vix_val = 14.0
    vix_safe = True
    try:
        vix_df = yf.Ticker("^INDIAVIX").history(period="2d")
        vix_val = float(vix_df['Close'].iloc[-1])
        if vix_val >= 16.5:
            vix_safe = False
    except Exception:
        pass

    return bull_score, drivers, vix_val, vix_safe

# --- 4. Market Structure & Liquidity Sweep Engine ---
def analyze_market_structure(symbol="NIFTYBEES.NS"):
    ticker = yf.Ticker(symbol)
    df_1m = ticker.history(period="1d", interval="1m")
    df_15m = ticker.history(period="5d", interval="15m")
    df_daily = ticker.history(period="1y", interval="1d")

    if df_1m.empty or df_15m.empty:
        return None

    last_bar = df_1m.iloc[-1]
    candle_time = str(df_1m.index[-1])
    curr_close = float(last_bar['Close'])
    bar_high = float(last_bar['High'])
    bar_low = float(last_bar['Low'])
    bar_open = float(last_bar['Open'])
    curr_vol = float(last_bar['Volume'])

    # Trend Gate
    df_daily['EMA200'] = df_daily['Close'].ewm(span=200, adjust=False).mean()
    ema_200 = float(df_daily['EMA200'].iloc[-1])
    is_bull_regime = curr_close >= ema_200

    # Key Structural Support (Pivots + 5D Swing Low)
    swing_low_5d = float(df_15m['Low'].min())
    swing_high_5d = float(df_15m['High'].tail(40).max())
    
    # Structural Resistance (Next Supply Zone)
    prev_swing_highs = [h for h in df_15m['High'].tail(30) if h > curr_close + 0.30]
    next_resistance = round(min(prev_swing_highs), 2) if prev_swing_highs else round(curr_close * 1.018, 2)
    
    prev_day_low = float(df_daily['Low'].iloc[-2])
    valid_supports = [s for s in [prev_day_low, swing_low_5d] if s < (curr_close - 0.15)]
    major_support = round(max(valid_supports), 2) if valid_supports else round(curr_close * 0.993, 2)

    # 1. Price Action: Liquidity Sweep & Rejection Wick
    lower_wick = min(bar_open, curr_close) - bar_low
    candle_body = abs(curr_close - bar_open)
    wick_ratio = lower_wick / (candle_body + 0.001)
    
    # Sweep: Wick penetrates support or bounces within 15 paise and closes green
    has_sweep_wick = (bar_low <= major_support + 0.20) and (wick_ratio >= 1.5) and (curr_close >= bar_open)

    # 2. Volume Absorption Analysis
    avg_vol_20 = float(df_1m['Volume'].tail(20).mean())
    volume_absorption = curr_vol >= (avg_vol_20 * 1.3)

    # Dynamic Structural Targets
    structural_target_1 = next_resistance
    structural_target_2 = round(curr_close + ((next_resistance - curr_close) * 1.5), 2)
    structural_sl = round(bar_low - 0.15, 2)

    state = load_state()
    state["active_target_1"] = structural_target_1
    state["active_target_2"] = structural_target_2
    state["active_sl"] = structural_sl
    save_state(state)

    diff_to_entry = round(curr_close - major_support, 2)

    return {
        "candle_time": candle_time,
        "close": curr_close,
        "open": bar_open,
        "high": bar_high,
        "low": bar_low,
        "curr_vol": curr_vol,
        "avg_vol": avg_vol_20,
        "major_support": major_support,
        "diff_to_entry": diff_to_entry,
        "next_resistance": next_resistance,
        "structural_target_1": structural_target_1,
        "structural_target_2": structural_target_2,
        "structural_sl": structural_sl,
        "has_sweep": has_sweep_wick,
        "volume_absorption": volume_absorption,
        "is_bull_regime": is_bull_regime,
        "ema_200": ema_200,
        "df_1m": df_1m
    }

def format_structure_card(data):
    bull_score, hw_drivers, vix_val, vix_safe = fetch_heavyweight_engine()
    state = load_state()
    qty = state.get("qty", 75)

    potential_pts = round(data["next_resistance"] - data["close"], 2)
    potential_pct = round((potential_pts / data["close"]) * 100, 2)

    net_t1 = (potential_pts * qty) - BROKERAGE_FEE

    # Structure Verification
    if data["has_sweep"] and data["volume_absorption"] and bull_score >= 2 and vix_safe:
        status_header = "🟢 **INSTITUTIONAL LIQUIDITY SWEEP CONFIRMED!**"
        action = (
            f"✅ **Market Absorption Verified:** Sellers exhausted + High Volume Buy Reversal.\n"
            f"👉 **EXECUTE:** Buy at **₹{data['close']:.2f}**\n"
            f"🛑 **Invalidation Stop:** ₹{data['structural_sl']:.2f} (Wick Low ke niche)\n"
            f"🎯 **Structure Exit (Next Supply Zone):** ₹{data['next_resistance']:.2f} (+{potential_pct}%)"
        )
    elif data["diff_to_entry"] <= 0.10:
        status_header = "🟡 **PRICE TESTING DEMAND ZONE (WATCHING CANDLE)**"
        action = "Price major support par hai. Institutional wick + volume confirmation ka wait karein."
    else:
        status_header = "⏳ **NO ENTRY IN VOID (PATIENCE)**"
        action = (
            f"📍 **Key Demand Support:** **₹{data['major_support']:.2f}**\n"
            f"📏 **Distance to Support:** **₹{data['diff_to_entry']:.2f}** baaki.\n"
            f"🎯 **Potential Next Resistance:** **₹{data['next_resistance']:.2f}** (+{potential_pct}%)\n"
            f"💡 Hawa me buy nahi karna. Support par liquidity sweep hone dein."
        )

    card = (
        f"🏛️ *MARKET STRUCTURE RADAR: NIFTYBEES*\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💰 *CMP:* ₹{data['close']:.2f} | 📈 *Trend:* {'🟢 Bullish (>200 EMA)' if data['is_bull_regime'] else '🔴 Weak (<200 EMA)'}\n"
        f"📊 *Volume Absorption:* {'🟢 Strong' if data['volume_absorption'] else '⚪ Normal'}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🏛️ *HEAVYWEIGHT CONFLUENCE ({bull_score}/3):*\n"
        f"• HDFC Bank: {hw_drivers.get('HDFC Bank', 'N/A')}\n"
        f"• Reliance: {hw_drivers.get('Reliance', 'N/A')}\n"
        f"• India VIX: *{vix_val:.2f}* ({'🟢 Safe' if vix_safe else '⚠️ High Panic'})\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"{status_header}\n\n"
        f"{action}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💵 *Dynamic Supply Exit ({qty} Units):*\n"
        f"🎯 **Next Resistance:** ₹{data['next_resistance']:.2f} (+{potential_pct}%)\n"
        f"💰 **Net In-Hand Expected:** *₹{net_t1:+.2f}* (Brokerage Deducted)\n"
        f"━━━━━━━━━━━━━━━━━━━"
    )
    return card

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
                                p = 271.50

                            state["tranche_level"] = t_num
                            state["temp_price"] = p
                            state["awaiting_qty"] = True
                            state["entry_time"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                            save_state(state)

                            send_telegram_msg(f"✅ *Tranche {t_num} Logged at ₹{p:.2f}!*\n\n👉 Reply me Units bhejein (e.g. `75` ya `150`).")
                        elif data == "skip_entry":
                            state["status"] = "WAITING"
                            save_state(state)
                            send_telegram_msg("👌 *Setup Skipped.* Structure sweep ka wait continue.")
                        elif data == "exit_trade":
                            state = {"tranche_level": 0, "entry_price": 0.0, "qty": 75, "status": "IDLE", "awaiting_qty": False, "entry_time": "", "active_target_1": 0.0, "active_target_2": 0.0, "active_sl": 0.0, "target_1_alerted": False, "target_2_alerted": False, "last_1m_candle_time": ""}
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
                                state["status"] = "HOLDING"
                                state["awaiting_qty"] = False
                                save_state(state)

                                send_telegram_msg(
                                    f"💼 *STRUCTURAL POSITION LOGGED*\n"
                                    f"📦 Units: *{total_qty}* | Net Buy Avg: *₹{avg_price:.2f}*\n"
                                    f"🎯 Structure Exit Target: *₹{state.get('active_target_1', avg_price*1.02):.2f}*\n"
                                    f"🛑 Stop-Loss: *₹{state.get('active_sl', avg_price*0.99):.2f}*"
                                )
                                continue

                        m_data = analyze_market_structure("NIFTYBEES.NS")
                        if m_data:
                            report_text = format_structure_card(m_data)
                            send_telegram_msg(report_text)

        except Exception:
            pass
        time.sleep(1)

# --- 6. Live Tick & Structure Monitor ---
def check_market():
    ist = pytz.timezone("Asia/Kolkata")
    send_telegram_msg("🚀 *Market Structure & Orderflow Engine Online!*\n• Institutional Sweep Radar Active\n• Dynamic Resistance Exit Ready.")

    while True:
        try:
            now = datetime.now(ist)

            if now.weekday() < 5 and (now.hour > 9 or (now.hour == 9 and now.minute >= 15)) and (now.hour < 15 or (now.hour == 15 and now.minute <= 30)):
                m_data = analyze_market_structure("NIFTYBEES.NS")
                
                if m_data:
                    state = load_state()
                    last_time = state.get("last_1m_candle_time", "")
                    
                    high_tick = m_data["high"]
                    low_tick = m_data["low"]
                    t1 = state.get("active_target_1", 0.0)
                    sl = state.get("active_sl", 0.0)
                    qty = state.get("qty", 75)

                    # Dynamic Resistance Hit
                    if t1 > 0 and high_tick >= t1 and not state.get("target_1_alerted", False):
                        state["target_1_alerted"] = True
                        save_state(state)
                        net_pnl = ((t1 - (state.get('entry_price') or (t1/1.018))) * qty) - BROKERAGE_FEE
                        exit_kb = {"inline_keyboard": [[{"text": "🏁 Book Full Profit", "callback_data": "exit_trade"}]]}
                        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={
                            "chat_id": CHAT_ID,
                            "text": (
                                f"🎯 *MARKET SUPPLY ZONE REACHED!*\n"
                                f"━━━━━━━━━━━━━━━━━━━\n"
                                f"📈 High Tick: *₹{high_tick:.2f}* (Resistance: ₹{t1:.2f})\n"
                                f"💵 Realized Net In-Hand: *₹{net_pnl:+.2f}*\n"
                                f"👉 Market yahan se reverse ho sakta hai. Profit book karein!"
                            ),
                            "parse_mode": "Markdown",
                            "reply_markup": json.dumps(exit_kb)
                        })

                    # Stop-Loss Invalidation Hit
                    if sl > 0 and low_tick <= sl and state.get("status") == "HOLDING":
                        loss_amt = ((sl - state.get('entry_price', sl)) * qty) - BROKERAGE_FEE
                        send_telegram_msg(
                            f"🛑 *STRUCTURE INVALIDATED (SL HIT)*\n"
                            f"📉 Low Tick: *₹{low_tick:.2f}* (SL: ₹{sl:.2f})\n"
                            f"🔴 Support toot chuka hai. Capital safety exit (Loss: ₹{loss_amt:.2f})"
                        )
                        state["status"] = "IDLE"
                        save_state(state)

                    # 1-Minute Candle Pulse
                    if m_data["candle_time"] != last_time:
                        state["last_1m_candle_time"] = m_data["candle_time"]
                        save_state(state)

                        card_text = format_structure_card(m_data)

                        if m_data["has_sweep"] and m_data["volume_absorption"]:
                            img = generate_chart(m_data["df_1m"])
                            send_alert_with_buttons(img, card_text, 1)
                        else:
                            send_telegram_msg(card_text)

            time.sleep(10)
        except Exception:
            time.sleep(10)

if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    threading.Thread(target=telegram_listener, daemon=True).start()
    check_market()
