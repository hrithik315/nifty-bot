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

BOT_TOKEN = "8695074642:AAHGHqaS1q-EkoEL5tY-gv7yvj5GAaF3lJ8"
CHAT_ID = "1152142289"
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

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

# --- 1. Keep-Alive Server ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"AI Quantitative Deep-Terminal Active!")

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()

# --- 2. Telegram Messengers ---
def send_telegram_msg(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": False})

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
            'parse_mode': 'Markdown',
            'reply_markup': json.dumps(keyboard)
        }, files={'photo': photo})

def generate_chart(df):
    chart_path = "chart.png"
    mpf.plot(df.tail(30), type='candle', style='charles', savefig=chart_path, volume=False)
    return chart_path

# --- 3. Deep Math & Technical Indicator Computations ---
def calculate_vwap(df):
    try:
        typical_price = (df['High'] + df['Low'] + df['Close']) / 3
        volume = df['Volume'].replace(0, 1)
        vwap = (typical_price * volume).cumsum() / volume.cumsum()
        return vwap.iloc[-1]
    except Exception:
        return df['Close'].iloc[-1]

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1]

def calculate_bollinger_bands(df, window=20):
    sma = df['Close'].rolling(window=window).mean().iloc[-1]
    std = df['Close'].rolling(window=window).std().iloc[-1]
    return sma + (2 * std), sma, sma - (2 * std)

def calculate_atr(df, period=14):
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(period).mean().iloc[-1]

def calculate_fibonacci(high, low):
    diff = high - low
    return {
        "fib_382": high - 0.382 * diff,
        "fib_500": high - 0.500 * diff,
        "fib_618": high - 0.618 * diff
    }

def get_heavyweights_data():
    bull_count = 0
    hw_stats = []
    for sym, name in [("RELIANCE.NS", "Reliance"), ("HDFCBANK.NS", "HDFC Bank"), ("ICICIBANK.NS", "ICICI Bank")]:
        try:
            h = yf.Ticker(sym).history(period="2d")
            c = h['Close'].iloc[-1]
            p = h['Close'].iloc[-2]
            chg = ((c - p) / p) * 100
            if chg > 0:
                bull_count += 1
            hw_stats.append(f"{name}: ₹{c:.1f} ({chg:+.2f}%)")
        except Exception:
            hw_stats.append(f"{name}: N/A")
    return bull_count, " | ".join(hw_stats)

# --- 4. Deep Data Extraction AI Engine ---
def ask_groq_market_analyst(user_query):
    try:
        if not GROQ_API_KEY:
            return "⚠️ GROQ_API_KEY Render Environment me set nahi hai."
            
        etf = yf.Ticker("NIFTYBEES.NS")
        df_1m = etf.history(period="1d", interval="1m")
        df_15m = etf.history(period="5d", interval="15m")
        df_1h = etf.history(period="1mo", interval="60m")
        df_daily = etf.history(period="6mo", interval="1d")
        
        curr_price = df_1m['Close'].iloc[-1]
        day_open = df_15m['Open'].iloc[0]
        day_high = df_15m['High'].max()
        day_low = df_15m['Low'].min()
        day_change = ((curr_price - day_open) / day_open) * 100
        drop_from_high = ((day_high - curr_price) / day_high) * 100
        
        vwap_val = calculate_vwap(df_15m)
        vwap_deviation = ((curr_price - vwap_val) / vwap_val) * 100
        
        rsi_15m = calculate_rsi(df_15m['Close'])
        rsi_1h = calculate_rsi(df_1h['Close'])
        rsi_daily = calculate_rsi(df_daily['Close'])
        
        bb_upper, bb_mid, bb_lower = calculate_bollinger_bands(df_15m)
        atr_val = calculate_atr(df_15m)
        fibs = calculate_fibonacci(df_1h['High'].max(), df_1h['Low'].min())
        bull_heavy, hw_line = get_heavyweights_data()
        
        vol_now = df_15m['Volume'].iloc[-1]
        vol_avg = df_15m['Volume'].tail(20).mean()
        vol_ratio = vol_now / vol_avg if vol_avg > 0 else 1.0
        
        sma_20_daily = df_daily['Close'].tail(20).mean()
        sma_50_daily = df_daily['Close'].tail(50).mean()
        
        state = load_state()
        portfolio_info = "Status: 100% Cash Free (No active trades)"
        if state.get("status") == "HOLDING" and state.get("qty", 0) > 0:
            e = state["entry_price"]
            q = state["qty"]
            net_pnl = ((curr_price - e) * q) - BROKERAGE_FEE
            ret = (net_pnl / (e * q)) * 100
            portfolio_info = (
                f"Position: Holding {q} units | Avg Entry: ₹{e:.2f} | "
                f"Net P&L: ₹{net_pnl:+.2f} ({ret:+.2f}%) | "
                f"Trailing SL: ₹{state.get('trailing_sl', 0):.2f}"
            )

        prompt = f"""
You are the Chief Quantitative Strategist and Technical Auditor for NIFTYBEES ETF.
The user wants a deep, precise, and highly detailed data-driven answer to this question:
"{user_query}"

LIVE EXTRACTED TERMINAL METRICS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Live Tick Price: ₹{curr_price:.2f} (Day Open: ₹{day_open:.2f} | Day Chg: {day_change:+.2f}%)
- Intraday Range: Low: ₹{day_low:.2f} | High: ₹{day_high:.2f} | Drop from High: -{drop_from_high:.2f}%
- VWAP: ₹{vwap_val:.2f} (Price vs VWAP Deviation: {vwap_deviation:+.2f}%)
- Multi-Timeframe RSI: [15m: {rsi_15m:.1f}] | [1h: {rsi_1h:.1f}] | [Daily: {rsi_daily:.1f}]
- Bollinger Bands (15m): Upper ₹{bb_upper:.2f} | Middle ₹{bb_mid:.2f} | Lower ₹{bb_lower:.2f}
- Intraday Volatility (ATR-14): ₹{atr_val:.2f}
- Volume Surge: {vol_ratio:.2f}x of 20-candle average
- Fibonacci Levels (1h Range): 38.2%: ₹{fibs['fib_382']:.2f} | 50.0%: ₹{fibs['fib_500']:.2f} | 61.8% (Pocket): ₹{fibs['fib_618']:.2f}
- Institutional Heavyweights (Top 3): {bull_heavy}/3 Bullish ({hw_line})
- Trend Filters: Daily 20 SMA: ₹{sma_20_daily:.2f} | Daily 50 SMA: ₹{sma_50_daily:.2f}
- User's Live Portfolio: {portfolio_info}

ANALYSIS INSTRUCTIONS:
- Give a comprehensive, crystal-clear breakdown answering every detail requested.
- Explain what the combination of VWAP deviation, RSI across timeframes, and Heavyweight institutional activity implies.
- Provide clear mathematical levels: Exact Entry zones, Support/Resistance lines, and Stop-loss/Target figures.
- Use natural professional Hindi/Hinglish. Format with clear Markdown bullet points and bold section tags for high readability.
"""

        endpoint = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2
        }
        
        res = requests.post(endpoint, headers=headers, json=payload, timeout=15)
        if res.status_code == 200:
            return res.json()["choices"][0]["message"]["content"]
        else:
            return f"⚠️ Live extracted price: ₹{curr_price:.2f}, 15m RSI: {rsi_15m:.1f}. Groq API Error: {res.status_code}"
    except Exception as err:
        return f"⚠️ Live data extraction issue: {err}"

# --- 5. Telegram Listener ---
def telegram_listener():
    offset = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={offset}&timeout=20"
            res = requests.get(url, timeout=25).json()
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
                            
                            send_telegram_msg(
                                f"✅ *Tranche {t_num} Logged at ₹{p:.2f}!*\n\n"
                                f"👉 Reply me apni Quantity bhejein (e.g., `/qty 25` ya direct `25`)."
                            )
                        elif data == "skip_entry":
                            state["status"] = "WAITING_STRONG"
                            save_state(state)
                            send_telegram_msg("👌 *Entry Skipped.* Quantitative scanner waiting for higher confluence.")
                        elif data == "exit_trade":
                            state = {"tranche_level": 0, "entry_price": 0.0, "qty": 0, "status": "IDLE", "awaiting_qty": False, "trailing_sl": 0.0, "max_price_seen": 0.0, "last_alerted_price": 0.0}
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
                                    f"💼 *PORTFOLIO POSITION UPDATED*\n"
                                    f"━━━━━━━━━━━━━━━━━━━\n"
                                    f"📦 Total Units: *{total_qty}*\n"
                                    f"💰 Net Avg Buy: *₹{avg_price:.2f}*\n"
                                    f"🎯 Target (+2.5%): *₹{target_p:.2f}*\n"
                                    f"━━━━━━━━━━━━━━━━━━━"
                                )
                                continue

                        send_telegram_msg("🔬 *Extracting full quantitative metrics & generating deep analysis...*")
                        ai_verdict = ask_groq_market_analyst(msg_text)
                        send_telegram_msg(ai_verdict)

        except Exception:
            pass
        time.sleep(2)

# --- 6. Live Price Movement Tracker & Confluence Scanner ---
def check_market():
    last_reported_drop = 0
    ist = pytz.timezone("Asia/Kolkata")
    
    send_telegram_msg("🚀 *Deep Quantitative AI Terminal Online!*\n• News scanner turned off\n• Instant ₹1.0 price move alerts active\n• Ask any in-depth data questions anytime!")

    while True:
        try:
            now = datetime.now(ist)
            
            # Market Hours (9:15 AM - 3:30 PM, Monday-Friday)
            if now.weekday() < 5 and (now.hour > 9 or (now.hour == 9 and now.minute >= 15)) and (now.hour < 15 or (now.hour == 15 and now.minute <= 30)):
                etf = yf.Ticker("NIFTYBEES.NS")
                df_1m = etf.history(period="1d", interval="1m")
                df_15m = etf.history(period="5d", interval="15m")
                df_1h = etf.history(period="1mo", interval="60m")
                
                curr_price = df_1m['Close'].iloc[-1]
                day_high = df_15m['High'].max()
                drop_pct = ((day_high - curr_price) / day_high) * 100
                vwap_val = calculate_vwap(df_15m)
                rsi_15m = calculate_rsi(df_15m['Close'])
                fibs = calculate_fibonacci(df_1h['High'].max(), df_1h['Low'].min())

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
                    
                    pos_msg = "Cash Free (100% Capital Safe)"
                    if state.get("status") == "HOLDING" and state.get("qty", 0) > 0:
                        e = state["entry_price"]
                        pnl = ((curr_price - e) * state["qty"]) - BROKERAGE_FEE
                        pos_msg = f"Holding {state['qty']} units @ ₹{e:.2f} | P&L: ₹{pnl:+.2f}"

                    send_telegram_msg(
                        f"{icon} *PRICE MOVEMENT TICK*\n"
                        f"━━━━━━━━━━━━━━━━━━━\n"
                        f"💰 Current Price: *₹{curr_price:.2f}*\n"
                        f"🔄 Shift: {direction} from ₹{last_price:.2f} ({diff:+.2f})\n"
                        f"📊 15m RSI: *{rsi_15m:.1f}* | VWAP: *₹{vwap_val:.2f}*\n"
                        f"💼 Position: {pos_msg}\n"
                        f"━━━━━━━━━━━━━━━━━━━"
                    )
                    state["last_alerted_price"] = curr_price
                    save_state(state)

                # Trailing SL & Targets for open trade
                if state.get("status") == "HOLDING" and state.get("qty", 0) > 0:
                    entry_p = state["entry_price"]
                    qty = state["qty"]
                    net_pnl = ((curr_price - entry_p) * qty) - BROKERAGE_FEE
                    net_return_pct = (net_pnl / (entry_p * qty)) * 100

                    if net_return_pct >= 2.5:
                        exit_kb = {"inline_keyboard": [[{"text": "🏁 Book Full Profit", "callback_data": "exit_trade"}]]}
                        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={
                            "chat_id": CHAT_ID,
                            "text": f"🎉 *TARGET REACHED (+2.5%)*\nSell Price: ₹{curr_price:.2f} | Net Realized: *₹{net_pnl:+.2f}*",
                            "parse_mode": "Markdown",
                            "reply_markup": json.dumps(exit_kb)
                        })

                # Tranche Dip Alerts
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
                        f"🚨 *NIFTYBEES DIP SIGNAL*\n"
                        f"━━━━━━━━━━━━━━━━━━━\n"
                        f"💰 *Price:* ₹{curr_price:.2f} (-{drop_pct:.2f}% from High)\n"
                        f"📊 *VWAP:* ₹{vwap_val:.2f} | *RSI:* {rsi_15m:.1f}\n"
                        f"👉 *Plan:* {alloc_text}"
                    )
                    send_alert_with_buttons(img, caption, target_tranche)

            time.sleep(30)
        except Exception:
            time.sleep(15)

if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    threading.Thread(target=telegram_listener, daemon=True).start()
    check_market()
