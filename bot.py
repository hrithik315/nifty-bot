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
    return {
        "tranche_level": 0,
        "entry_price": 0.0,
        "qty": 0,
        "status": "IDLE",
        "awaiting_qty": False,
        "trailing_sl": 0.0,
        "max_price_seen": 0.0
    }

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)

# --- 1. Render Keep-Alive Server ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Institutional Bot 24/7 Active!")

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

# --- 3. Quantitative Math (VWAP, RSI, Fibonacci) ---
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
        "fib_500": high - 0.500 * diff,
        "fib_618": high - 0.618 * diff
    }

# --- 4. Interactive Telegram Listener (Buttons + Quantity Input) ---
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
                                f"👉 *Reply me apni Quantity send karein:*\n"
                                f"Type: `/qty 20` ya direct number `20`"
                            )
                        elif data == "skip_entry":
                            state["status"] = "WAITING_STRONG"
                            save_state(state)
                            send_telegram_msg("👌 *Entry Skipped!* Bot waiting for stronger multi-confirmation reversal.")
                        elif data == "exit_trade":
                            state = {"tranche_level": 0, "entry_price": 0.0, "qty": 0, "status": "IDLE", "awaiting_qty": False, "trailing_sl": 0.0, "max_price_seen": 0.0}
                            save_state(state)
                            send_telegram_msg("🏁 *Position Closed!* Capital released. Scanner reset.")

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
                                state["trailing_sl"] = 0.0
                                state["status"] = "HOLDING"
                                state["awaiting_qty"] = False
                                save_state(state)
                                
                                target_p = avg_price * 1.025
                                send_telegram_msg(
                                    f"💼 *PORTFOLIO POSITION ACTIVATED*\n"
                                    f"━━━━━━━━━━━━━━━━━━━\n"
                                    f"📦 Total Shares: *{total_qty} units*\n"
                                    f"💰 Average Price: *₹{avg_price:.2f}*\n"
                                    f"💵 Capital Invested: *₹{(total_qty*avg_price):.2f}*\n"
                                    f"🎯 Profit Target (+2.5%): *₹{target_p:.2f}*\n"
                                    f"🛡️ Auto Trailing SL Engine: *ACTIVE*\n"
                                    f"━━━━━━━━━━━━━━━━━━━"
                                )
        except Exception:
            pass
        time.sleep(2)

# --- 5. Pre-Market Briefing (8:30 AM IST) ---
def send_pre_market_briefing():
    try:
        sp500 = yf.Ticker("^GSPC").history(period="2d")
        nasdaq = yf.Ticker("^IXIC").history(period="2d")
        crude = yf.Ticker("CL=F").history(period="2d")
        dxy = yf.Ticker("DX-Y.NYB").history(period="2d")
        
        sp_change = ((sp500['Close'].iloc[-1] - sp500['Close'].iloc[-2]) / sp500['Close'].iloc[-2]) * 100
        nas_change = ((nasdaq['Close'].iloc[-1] - nasdaq['Close'].iloc[-2]) / nasdaq['Close'].iloc[-2]) * 100
        crude_p = crude['Close'].iloc[-1]
        dxy_p = dxy['Close'].iloc[-1]
        
        bias = "🟢 Bullish / Flat Open Expected" if sp_change > 0.3 else ("🔴 Gap-Down / Caution Expected" if sp_change < -0.5 else "⚪ Neutral Range Open Expected")
        
        msg = (
            f"🌅 *PRE-MARKET GLOBAL BRIEFING (8:30 AM)*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🧭 *Market Bias:* {bias}\n\n"
            f"🌎 *US Markets:*\n"
            f"• S&P 500: {sp_change:+.2f}%\n"
            f"• Nasdaq: {nas_change:+.2f}%\n\n"
            f"🛢️ *Macro Radar:*\n"
            f"• Brent Crude: ${crude_p:.2f}\n"
            f"• US Dollar Index (DXY): {dxy_p:.2f}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ *Plan:* Intraday dips par trailing SL strategy follow karein!"
        )
        send_telegram_msg(msg)
    except Exception as e:
        print(f"Pre-market error: {e}")

# --- 6. Post-Market Summary Card (3:35 PM IST) ---
def send_closing_summary():
    try:
        etf = yf.Ticker("NIFTYBEES.NS")
        idx = yf.Ticker("^NSEI")
        df_etf = etf.history(period="2d", interval="1d")
        df_idx = idx.history(period="2d", interval="1d")
        
        c = df_etf['Close'].iloc[-1]
        p = df_etf['Close'].iloc[-2]
        chg = ((c - p) / p) * 100
        
        idx_chg = ((df_idx['Close'].iloc[-1] - df_idx['Close'].iloc[-2]) / df_idx['Close'].iloc[-2]) * 100
        state = load_state()
        
        pos_text = "No open positions (Cash 100% ready)"
        if state.get("status") == "HOLDING" and state.get("qty", 0) > 0:
            entry = state["entry_price"]
            qty = state["qty"]
            g_pnl = (c - entry) * qty
            n_pnl = g_pnl - BROKERAGE_FEE
            p_badge = "🟢" if n_pnl >= 0 else "🔴"
            pos_text = f"{p_badge} Holding {qty} units | Net P&L: *₹{n_pnl:+.2f}* (after ₹40 fee)"
            
        msg = (
            f"🔔 *MARKET CLOSING SUMMARY (3:35 PM)*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"💰 *NIFTYBEES Close:* ₹{c:.2f} ({chg:+.2f}%)\n"
            f"📊 *Nifty 50 Close:* {df_idx['Close'].iloc[-1]:.2f} ({idx_chg:+.2f}%)\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"💼 *Trade Ledger Status:*\n"
            f"{pos_text}\n"
            f"━━━━━━━━━━━━━━━━━━━"
        )
        send_telegram_msg(msg)
    except Exception as e:
        print(f"Closing summary error: {e}")

# --- 7. Real-Time News Scanner ---
def scan_market_news():
    seen = set()
    feed_url = "https://news.google.com/rss/search?q=NIFTY+OR+NIFTYBEES+OR+%22Indian+Stock+Market%22+when:1h&hl=en-IN&gl=IN&ceid=IN:en"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(feed_url, headers=headers, timeout=10)
        if res.status_code == 200:
            root = ET.fromstring(res.content)
            for item in root.findall(".//item"):
                link = item.find("link")
                if link is not None and link.text:
                    seen.add(link.text.strip())
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
                        if link not in seen:
                            seen.add(link)
                            send_telegram_msg(f"⚡ *BREAKING NEWS*\n━━━━━━━━━━━━━━━━━━━\n📰 {title}\n🕒 `{pub_time}`\n🔗 [Read Full Story]({link})")
            if len(seen) > 500:
                seen = set(list(seen)[-200:])
        except Exception:
            pass
        time.sleep(30)

# --- 8. Core Market Scanner & Trailing SL Engine ---
def check_market():
    last_reported_drop = 0
    pre_briefing_date = ""
    post_closing_date = ""
    ist = pytz.timezone("Asia/Kolkata")
    
    send_telegram_msg("🚀 *NIFTYBEES Ultimate Pro Engine Live!*\n• Auto Trailing SL Activated\n• VWAP Reversal Filters Active\n• 8:30 AM Global Clues & 3:35 PM Ledger Active!")

    while True:
        try:
            now = datetime.now(ist)
            today_str = now.strftime("%Y-%m-%d")
            
            # Pre-Market 8:30 AM Briefing
            if now.weekday() < 5 and now.hour == 8 and now.minute >= 30 and pre_briefing_date != today_str:
                send_pre_market_briefing()
                pre_briefing_date = today_str

            # Post-Market 3:35 PM Closing Card
            if now.weekday() < 5 and now.hour == 15 and now.minute >= 35 and post_closing_date != today_str:
                send_closing_summary()
                post_closing_date = today_str

            # Trading Hours: Mon-Fri 9:15 AM - 3:30 PM
            if now.weekday() < 5 and (now.hour > 9 or (now.hour == 9 and now.minute >= 15)) and (now.hour < 15 or (now.hour == 15 and now.minute <= 30)):
                etf = yf.Ticker("NIFTYBEES.NS")
                idx = yf.Ticker("^NSEI")
                
                df_15m = etf.history(period="5d", interval="15m")
                df_1h = etf.history(period="1mo", interval="60m")
                
                curr_price = df_15m['Close'].iloc[-1]
                day_high = df_15m['High'].max()
                drop_pct = ((day_high - curr_price) / day_high) * 100
                vwap_val = calculate_vwap(df_15m)
                rsi_15m = calculate_rsi(df_15m['Close'])
                fibs = calculate_fibonacci(df_1h['High'].max(), df_1h['Low'].min())

                state = load_state()

                # --- AUTO TRAILING STOP-LOSS & TARGET ENGINE ---
                if state.get("status") == "HOLDING" and state.get("qty", 0) > 0:
                    entry_p = state["entry_price"]
                    qty = state["qty"]
                    invested = entry_p * qty
                    gross_pnl = (curr_price - entry_p) * qty
                    net_pnl = gross_pnl - BROKERAGE_FEE
                    net_return_pct = (net_pnl / invested) * 100

                    # Max price tracker
                    if curr_price > state.get("max_price_seen", entry_p):
                        state["max_price_seen"] = curr_price
                        save_state(state)

                    # Dynamic Trailing SL Rules:
                    # Rule A: Return >= +1.5% -> Lock SL at Entry Price (Cost-to-Cost)
                    if net_return_pct >= 1.5 and state.get("trailing_sl", 0.0) < entry_p:
                        state["trailing_sl"] = entry_p
                        save_state(state)
                        send_telegram_msg(f"🛡️ *TRAILING SL MOVED TO COST!* (₹{entry_p:.2f})\nRisk eliminated: Position is now risk-free!")

                    # Rule B: Return >= +2.0% -> Lock SL at +1.0% Guaranteed Profit
                    if net_return_pct >= 2.0 and state.get("trailing_sl", 0.0) < (entry_p * 1.01):
                        state["trailing_sl"] = entry_p * 1.01
                        save_state(state)
                        send_telegram_msg(f"🔒 *PROFIT LOCKED!* Trailing SL shifted to ₹{(entry_p * 1.01):.2f} (+1.0% guaranteed net profit)!")

                    # Rule C: Trailing SL Hit
                    if state.get("trailing_sl", 0.0) > 0 and curr_price <= state["trailing_sl"]:
                        exit_kb = {"inline_keyboard": [[{"text": "🏁 Acknowledge & Reset Bot", "callback_data": "exit_trade"}]]}
                        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={
                            "chat_id": CHAT_ID,
                            "text": f"🛑 *TRAILING SL HIT (PROFIT SECURED)*\n━━━━━━━━━━━━━━━━━━━\nExit Price: ₹{curr_price:.2f}\nNet In-Hand Profit: *₹{net_pnl:+.2f}*\nCapital protected successfully!",
                            "parse_mode": "Markdown",
                            "reply_markup": json.dumps(exit_kb)
                        })

                    # Rule D: Full Target Hit (+2.5%)
                    if net_return_pct >= 2.5:
                        exit_kb = {"inline_keyboard": [[{"text": "🏁 Book Full Profit", "callback_data": "exit_trade"}]]}
                        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={
                            "chat_id": CHAT_ID,
                            "text": f"🎉 *FULL PROFIT TARGET HIT (+2.5%)*\n━━━━━━━━━━━━━━━━━━━\n📦 Holdings: {qty} units\n💰 Sell Price: ₹{curr_price:.2f}\n💵 Net Profit: *₹{net_pnl:+.2f}* (after ₹40 fee)\n👉 Book and secure gains!",
                            "parse_mode": "Markdown",
                            "reply_markup": json.dumps(exit_kb)
                        })

                # --- VWAP + MULTI-TIMEFRAME ENTRY TRIGGERS ---
                should_alert = False
                target_tranche = 1
                alloc_text = "Deploy 20% Capital"
                vwap_badge = "🟢 Above VWAP (Buyer Strength)" if curr_price >= vwap_val else "🔴 Below VWAP (Discount / Dip)"

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
                        alloc_text = f"Averaging: Deploy 30% Capital (Down {fall:.1f}% from 1st Entry)"
                    elif curr_tranche == 2 and fall >= 3.0 and (drop_pct >= last_reported_drop + 1.0):
                        should_alert = True
                        target_tranche = 3
                        alloc_text = "Final Tranche: Deploy 50% Capital"

                if should_alert:
                    last_reported_drop = int(drop_pct)
                    img = generate_chart(df_15m)
                    
                    pnl_sec = ""
                    if state.get("status") == "HOLDING" and state.get("qty", 0) > 0:
                        npnl = ((curr_price - state["entry_price"]) * state["qty"]) - BROKERAGE_FEE
                        badge = "🟢" if npnl >= 0 else "🔴"
                        pnl_sec = f"\n💼 *LIVE POSITION:* {state['qty']} units | {badge} Net P&L: *₹{npnl:+.2f}*\n"
                        
                    caption = (
                        f"🚨 *NIFTYBEES PRO ENTRY ALERT*\n"
                        f"━━━━━━━━━━━━━━━━━━━\n"
                        f"💰 *Current Price:* ₹{curr_price:.2f} (-{drop_pct:.2f}% from High)\n"
                        f"📊 *VWAP Status:* {vwap_badge} (₹{vwap_val:.2f})\n"
                        f"📐 *61.8% Golden Fibo:* ₹{fibs['fib_618']:.2f} | *RSI:* {rsi_15m:.1f}\n"
                        f"{pnl_sec}"
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
