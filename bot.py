import os
import time
import json
import threading
import xml.etree.ElementTree as ET
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

STATE_FILE = "portfolio_state.json"
BROKERAGE_FEE = 40.0  # Buy + Sell flat brokerage

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {"tranche_level": 0, "entry_price": 0.0, "qty": 0, "status": "IDLE", "awaiting_qty": False}

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)

# --- 1. Keep-Alive Server ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is Running 24/7!")

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

# --- 3. Interactive Telegram Listener (Qty Input + Buttons) ---
def telegram_listener():
    offset = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={offset}&timeout=20"
            res = requests.get(url, timeout=25).json()
            if "result" in res:
                for update in res["result"]:
                    offset = update["update_id"] + 1
                    
                    # Handle Button Clicks
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
                                f"👉 *Ab reply me apni Quantity send karein:*\n"
                                f"Example: `/qty 20` ya direct number `20` likh kar bhejein."
                            )
                            
                        elif data == "skip_entry":
                            state["status"] = "WAITING_STRONG"
                            save_state(state)
                            send_telegram_msg("👌 *Skipped!* Bot high-conviction setup par dubara alert karega.")
                            
                        elif data == "exit_trade":
                            state = {"tranche_level": 0, "entry_price": 0.0, "qty": 0, "status": "IDLE", "awaiting_qty": False}
                            save_state(state)
                            send_telegram_msg("🏁 *Trade Successfully Closed!* Portfolio reset ho gaya hai.")

                    # Handle Text Messages (Quantity reply)
                    elif "message" in update and "text" in update["message"]:
                        msg_text = update["message"]["text"].strip()
                        state = load_state()
                        
                        if state.get("awaiting_qty", False):
                            clean_text = msg_text.replace("/qty", "").strip()
                            if clean_text.isdigit() and int(clean_text) > 0:
                                qty = int(clean_text)
                                p = state.get("temp_price", 280.0)
                                prev_qty = state.get("qty", 0)
                                prev_price = state.get("entry_price", 0.0)
                                
                                # Weighted average if adding more shares
                                total_qty = prev_qty + qty
                                avg_price = ((prev_qty * prev_price) + (qty * p)) / total_qty if total_qty > 0 else p
                                
                                state["qty"] = total_qty
                                state["entry_price"] = avg_price
                                state["status"] = "HOLDING"
                                state["awaiting_qty"] = False
                                save_state(state)
                                
                                invested = total_qty * avg_price
                                target_p = avg_price * 1.025
                                
                                send_telegram_msg(
                                    f"💼 *PORTFOLIO POSITION ACTIVATED*\n"
                                    f"━━━━━━━━━━━━━━━━━━━\n"
                                    f"📦 Total Shares: *{total_qty} units*\n"
                                    f"💰 Avg Buy Price: *₹{avg_price:.2f}*\n"
                                    f"💵 Total Capital: *₹{invested:.2f}*\n"
                                    f"🎯 Profit Target (+2.5%): *₹{target_p:.2f}*\n"
                                    f"━━━━━━━━━━━━━━━━━━━\n"
                                    f"🤖 Bot ab live P&L track karega (brokerage deduct karke)!"
                                )

        except Exception:
            pass
        time.sleep(2)

# --- 4. Technical Indicators ---
def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1]

def calculate_fibonacci(high, low):
    diff = high - low
    return {"fib_618": high - 0.618 * diff}

# --- 5. Breaking News Scanner ---
def scan_market_news():
    seen_news_links = set()
    feed_url = "https://news.google.com/rss/search?q=NIFTY+OR+NIFTYBEES+OR+%22Indian+Stock+Market%22+when:1h&hl=en-IN&gl=IN&ceid=IN:en"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(feed_url, headers=headers, timeout=10)
        if res.status_code == 200:
            root = ET.fromstring(res.content)
            for item in root.findall(".//item"):
                link = item.find("link")
                if link is not None and link.text:
                    seen_news_links.add(link.text.strip())
    except Exception:
        pass

    while True:
        try:
            res = requests.get(feed_url, headers=headers, timeout=10)
            if res.status_code == 200:
                root = ET.fromstring(res.content)
                for item in root.findall(".//item"):
                    link_elem = item.find("link")
                    title_elem = item.find("title")
                    pub_elem = item.find("pubDate")
                    if link_elem is not None and title_elem is not None:
                        link = link_elem.text.strip()
                        title = title_elem.text.strip()
                        pub_time = pub_elem.text.strip() if pub_elem is not None else "Just Now"

                        if link not in seen_news_links:
                            seen_news_links.add(link)
                            send_telegram_msg(
                                f"⚡ *MARKET BREAKING NEWS*\n━━━━━━━━━━━━━━━━━━━\n📰 {title}\n🕒 `{pub_time}`\n🔗 [Read Story]({link})"
                            )
            if len(seen_news_links) > 500:
                seen_news_links = set(list(seen_news_links)[-200:])
        except Exception:
            pass
        time.sleep(30)

# --- 6. Weekly Monday Summary ---
def send_weekly_summary():
    try:
        etf = yf.Ticker("NIFTYBEES.NS")
        df_etf = etf.history(period="1mo", interval="1d")
        last_week = df_etf.iloc[-6:-1]
        w_open, w_close = last_week['Open'].iloc[0], last_week['Close'].iloc[-1]
        w_change = ((w_close - w_open) / w_open) * 100
        send_telegram_msg(f"📊 *NIFTYBEES WEEKLY SUMMARY*\nNet Movement: *{w_change:+.2f}%*\nClose: ₹{w_close:.2f}")
    except Exception as e:
        print(f"Weekly report error: {e}")

# --- 7. Main Market Engine ---
def check_market():
    last_reported_drop = 0
    weekly_report_sent_date = ""
    ist = pytz.timezone("Asia/Kolkata")
    
    send_telegram_msg("🚀 *NIFTYBEES Live Trader Bot Online!*\n• Auto P&L Calculation with ₹40 Brokerage\n• Custom Share Quantity Support Active!")

    while True:
        try:
            now = datetime.now(ist)
            today_str = now.strftime("%Y-%m-%d")
            
            if now.weekday() == 0 and now.hour == 9 and now.minute >= 15 and weekly_report_sent_date != today_str:
                send_weekly_summary()
                weekly_report_sent_date = today_str

            if now.weekday() < 5 and (now.hour > 9 or (now.hour == 9 and now.minute >= 15)) and (now.hour < 15 or (now.hour == 15 and now.minute <= 30)):
                etf = yf.Ticker("NIFTYBEES.NS")
                idx = yf.Ticker("^NSEI")
                
                df_15m = etf.history(period="5d", interval="15m")
                df_1h = etf.history(period="1mo", interval="60m")
                
                curr_price = df_15m['Close'].iloc[-1]
                day_high = df_15m['High'].max()
                drop_pct = ((day_high - curr_price) / day_high) * 100
                rsi_15m = calculate_rsi(df_15m['Close'])
                fibs = calculate_fibonacci(df_1h['High'].max(), df_1h['Low'].min())

                state = load_state()

                # --- 1. LIVE P&L & TARGET MONITORING ---
                if state.get("status") == "HOLDING" and state.get("qty", 0) > 0:
                    entry_p = state["entry_price"]
                    qty = state["qty"]
                    invested = entry_p * qty
                    current_value = curr_price * qty
                    gross_pnl = current_value - invested
                    net_pnl = gross_pnl - BROKERAGE_FEE
                    net_return_pct = (net_pnl / invested) * 100

                    # Target Hit (+2.3% or higher)
                    if net_return_pct >= 2.3:
                        exit_keyboard = {
                            "inline_keyboard": [[{"text": "🏁 Book Profit / Exit Trade", "callback_data": "exit_trade"}]]
                        }
                        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
                        requests.post(url, json={
                            "chat_id": CHAT_ID,
                            "text": (
                                f"🎉 *PROFIT TARGET HIT!*\n"
                                f"━━━━━━━━━━━━━━━━━━━\n"
                                f"📦 Holding: *{qty} shares*\n"
                                f"💰 Current Price: *₹{curr_price:.2f}* (Bought at ₹{entry_p:.2f})\n"
                                f"💵 Gross Profit: *₹{gross_pnl:+.2f}*\n"
                                f"🧾 Brokerage Less: *-₹{BROKERAGE_FEE:.2f}*\n"
                                f"🤑 *NET PROFIT (IN-HAND): ₹{net_pnl:+.2f} ({net_return_pct:+.2f}%)*\n"
                                f"━━━━━━━━━━━━━━━━━━━\n"
                                f"👉 *Recommendation: Profit book karein!*"
                            ),
                            "parse_mode": "Markdown",
                            "reply_markup": json.dumps(exit_keyboard)
                        })

                # --- 2. DIP ALERTS & P&L CARDS ---
                should_alert = False
                target_tranche = 1
                alloc_text = "Deploy 20% Capital"

                if state.get("status") == "IDLE":
                    if drop_pct >= 1.0 and drop_pct >= last_reported_drop + 1.0:
                        should_alert = True
                        target_tranche = 1
                        alloc_text = "Deploy 20% Capital (Tranche 1)"
                        
                elif state.get("status") == "WAITING_STRONG":
                    if (rsi_15m < 32 or curr_price <= fibs['fib_618'] or drop_pct >= 2.5) and (drop_pct >= last_reported_drop + 1.0):
                        should_alert = True
                        target_tranche = 1
                        alloc_text = "High Accuracy Setup - Deploy 25% Capital"
                        
                elif state.get("status") == "HOLDING":
                    curr_tranche = state.get("tranche_level", 1)
                    entry_p = state.get("entry_price", curr_price)
                    fall = ((entry_p - curr_price) / entry_p) * 100
                    
                    if curr_tranche == 1 and fall >= 1.5 and (drop_pct >= last_reported_drop + 1.0):
                        should_alert = True
                        target_tranche = 2
                        alloc_text = f"Averaging: Deploy 30% Capital (Down {fall:.1f}% from entry)"
                    elif curr_tranche == 2 and fall >= 3.0 and (drop_pct >= last_reported_drop + 1.0):
                        should_alert = True
                        target_tranche = 3
                        alloc_text = "Final Tranche: Deploy 50% Capital"

                if should_alert:
                    last_reported_drop = int(drop_pct)
                    img = generate_chart(df_15m)
                    
                    # Live P&L card if holding
                    pnl_section = ""
                    if state.get("status") == "HOLDING" and state.get("qty", 0) > 0:
                        g_pnl = (curr_price - state["entry_price"]) * state["qty"]
                        n_pnl = g_pnl - BROKERAGE_FEE
                        pnl_badge = "🟢" if n_pnl >= 0 else "🔴"
                        pnl_section = (
                            f"\n💼 *YOUR LIVE POSITION:*\n"
                            f"• Holdings: {state['qty']} units (Avg: ₹{state['entry_price']:.2f})\n"
                            f"• {pnl_badge} Net P&L: *₹{n_pnl:+.2f}* (after ₹40 brokerage)\n"
                        )
                    
                    caption = (
                        f"🚨 *NIFTYBEES TRADING ALERT*\n"
                        f"━━━━━━━━━━━━━━━━━━━\n"
                        f"💰 *Current Price:* ₹{curr_price:.2f} (-{drop_pct:.2f}% from High)\n"
                        f"📐 *61.8% Fibo:* ₹{fibs['fib_618']:.2f} | *RSI:* {rsi_15m:.1f}\n"
                        f"{pnl_section}"
                        f"━━━━━━━━━━━━━━━━━━━\n"
                        f"👉 *Action:* {alloc_text}\n"
                        f"Trade update record karein:"
                    )
                    send_alert_with_buttons(img, caption, target_tranche)

            time.sleep(60)
        except Exception:
            time.sleep(15)

if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    threading.Thread(target=scan_market_news, daemon=True).start()
    threading.Thread(target=telegram_listener, daemon=True).start()
    check_market()
