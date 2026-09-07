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

# --- 1. Web Server for Render 24/7 ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"AI Quantitative Deep-Terminal Active!")

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()

# --- 2. Reliable Telegram Sender ---
def send_telegram_msg(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": str(text), "disable_web_page_preview": True}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

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

def calculate_fibonacci(high, low):
    diff = high - low
    return {
        "fib_382": high - 0.382 * diff,
        "fib_500": high - 0.500 * diff,
        "fib_618": high - 0.618 * diff
    }

# --- 4. Dynamic Symbol Mapping ---
def detect_symbol(query):
    q = query.upper()
    common = {
        "WIPRO": "WIPRO.NS", "RELIANCE": "RELIANCE.NS", "TCS": "TCS.NS",
        "INFY": "INFY.NS", "INFOSYS": "INFY.NS", "HDFC": "HDFCBANK.NS",
        "HDFCBANK": "HDFCBANK.NS", "ICICI": "ICICIBANK.NS", "ICICIBANK": "ICICIBANK.NS",
        "SBIN": "SBIN.NS", "SBI": "SBIN.NS", "ITC": "ITC.NS", "TATAMOTORS": "TATAMOTORS.NS",
        "TATA MOTORS": "TATAMOTORS.NS", "NIFTY": "NIFTYBEES.NS", "NIFTYBEES": "NIFTYBEES.NS"
    }
    for word, sym in common.items():
        if word in q:
            return sym, word
    return "NIFTYBEES.NS", "NIFTYBEES"

# --- 5. Async Worker for AI Analysis ---
def process_ai_query(user_query):
    if not GROQ_API_KEY:
        send_telegram_msg("⚠️ GROQ_API_KEY Render Environment Variables me missing hai.")
        return

    try:
        target_symbol, asset_name = detect_symbol(user_query)
        ticker = yf.Ticker(target_symbol)
        df_hist = ticker.history(period="1mo", interval="1d")
        
        if df_hist.empty:
            df_hist = yf.Ticker("NIFTYBEES.NS").history(period="1mo", interval="1d")
            asset_name = "NIFTYBEES"
            
        curr_price = float(df_hist['Close'].iloc[-1])
        high_1m = float(df_hist['High'].max())
        low_1m = float(df_hist['Low'].min())
        rsi_val = float(calculate_rsi(df_hist['Close']))
        fibs = calculate_fibonacci(high_1m, low_1m)

        prompt = f"""
User Question: "{user_query}"
Asset: {asset_name}
Current Price: ₹{curr_price:.2f}
1-Month Low: ₹{low_1m:.2f} | 1-Month High: ₹{high_1m:.2f}
RSI (Daily): {rsi_val:.1f}
Fibonacci 61.8% Support: ₹{fibs['fib_618']:.2f}

Provide a direct quantitative assessment in clean Hindi/Hinglish:
🎯 VERDICT: (Bottom support / expected move)
🔬 KEY LEVELS:
- Immediate Support: ₹...
- Downside Risk (Agar support toota): ₹...
- Upside Target: ₹...
⚡ ACTION PLAN: (Clear guidance: Buy, Wait, or Hold)
Keep total response under 120 words.
"""
        endpoint = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY.strip()}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2
        }
        
        res = requests.post(endpoint, headers=headers, json=payload, timeout=25)
        if res.status_code == 200:
            data = res.json()
            answer = data["choices"][0]["message"]["content"]
            send_telegram_msg(answer)
        else:
            send_telegram_msg(f"⚠️ Groq API issue: Code {res.status_code}\n{res.text}")
    except Exception as err:
        send_telegram_msg(f"⚠️ Data extraction error: {str(err)}")

# --- 6. Telegram Listener ---
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
                            
                            send_telegram_msg(f"✅ Tranche {t_num} Logged at ₹{p:.2f}!\nReply me Quantity bhejein (e.g. 20).")
                        elif data == "skip_entry":
                            state["status"] = "WAITING_STRONG"
                            save_state(state)
                            send_telegram_msg("👌 Entry Skipped. Scanner waiting for higher confluence.")
                        elif data == "exit_trade":
                            state = {"tranche_level": 0, "entry_price": 0.0, "qty": 0, "status": "IDLE", "awaiting_qty": False, "trailing_sl": 0.0, "max_price_seen": 0.0, "last_alerted_price": 0.0}
                            save_state(state)
                            send_telegram_msg("🏁 Position Closed. Portfolio reset to 100% Cash.")

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
                                    f"💼 PORTFOLIO UPDATED\n"
                                    f"Units: {total_qty} | Avg Buy: ₹{avg_price:.2f} | Target (+2.5%): ₹{target_p:.2f}"
                                )
                                continue

                        send_telegram_msg("🔬 Analyzing market data with AI engine...")
                        # Run analysis in background thread so listener is never blocked
                        threading.Thread(target=process_ai_query, args=(msg_text,), daemon=True).start()

        except Exception:
            pass
        time.sleep(1)

# --- 7. Price Movement Tracker ---
def check_market():
    last_reported_drop = 0
    ist = pytz.timezone("Asia/Kolkata")
    
    send_telegram_msg("🚀 Personal Quantitative AI Terminal Online!\nSend any stock query or NIFTYBEES.")

    while True:
        try:
            now = datetime.now(ist)
            
            if now.weekday() < 5 and (now.hour > 9 or (now.hour == 9 and now.minute >= 15)) and (now.hour < 15 or (now.hour == 15 and now.minute <= 30)):
                etf = yf.Ticker("NIFTYBEES.NS")
                df_1m = etf.history(period="1d", interval="1m")
                df_15m = etf.history(period="5d", interval="15m")
                
                curr_price = df_1m['Close'].iloc[-1]
                day_high = df_15m['High'].max()
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
                        f"{icon} PRICE MOVEMENT\n"
                        f"NIFTYBEES: ₹{curr_price:.2f}\n"
                        f"Shift: {direction} from ₹{last_price:.2f} ({diff:+.2f})\n"
                        f"15m RSI: {rsi_15m:.1f} | VWAP: ₹{vwap_val:.2f}\n"
                        f"Position: {pos_msg}"
                    )
                    state["last_alerted_price"] = curr_price
                    save_state(state)

                # Trailing SL & Targets
                if state.get("status") == "HOLDING" and state.get("qty", 0) > 0:
                    entry_p = state["entry_price"]
                    qty = state["qty"]
                    net_pnl = ((curr_price - entry_p) * qty) - BROKERAGE_FEE
                    net_return_pct = (net_pnl / (entry_p * qty)) * 100

                    if net_return_pct >= 2.5:
                        exit_kb = {"inline_keyboard": [[{"text": "🏁 Book Full Profit", "callback_data": "exit_trade"}]]}
                        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={
                            "chat_id": CHAT_ID,
                            "text": f"🎉 TARGET REACHED (+2.5%)\nSell: ₹{curr_price:.2f} | Net: ₹{net_pnl:+.2f}",
                            "reply_markup": json.dumps(exit_kb)
                        })

                # Tranche Signals
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
                        f"🚨 NIFTYBEES DIP SIGNAL\n"
                        f"Price: ₹{curr_price:.2f} (-{drop_pct:.2f}% from High)\n"
                        f"VWAP: ₹{vwap_val:.2f} | RSI: {rsi_15m:.1f}\n"
                        f"Plan: {alloc_text}"
                    )
                    send_alert_with_buttons(img, caption, target_tranche)

            time.sleep(30)
        except Exception:
            time.sleep(15)

if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    threading.Thread(target=telegram_listener, daemon=True).start()
    check_market()
