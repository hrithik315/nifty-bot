import os
import time
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

# --- 1. Render Keep-Alive 24/7 Server ---
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

def send_telegram_alert(img_path, caption_text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    with open(img_path, 'rb') as photo:
        requests.post(url, data={'chat_id': CHAT_ID, 'caption': caption_text, 'parse_mode': 'Markdown'}, files={'photo': photo})

def generate_chart(df):
    chart_path = "chart.png"
    mpf.plot(df.tail(30), type='candle', style='charles', savefig=chart_path, volume=False)
    return chart_path

# --- 3. Technical Indicators (RSI & Fibonacci) ---
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
        "fib_236": high - 0.236 * diff,
        "fib_382": high - 0.382 * diff,
        "fib_500": high - 0.500 * diff,
        "fib_618": high - 0.618 * diff,  # Golden Pocket
        "fib_786": high - 0.786 * diff
    }

# --- 4. Breaking News Scanner (30-Sec Thread) ---
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
                            news_msg = (
                                f"⚡ *MARKET BREAKING NEWS*\n"
                                f"━━━━━━━━━━━━━━━━━━━\n"
                                f"📰 *Headline:*\n{title}\n\n"
                                f"🕒 *Time:* `{pub_time}`\n"
                                f"🔗 [Click Here to Read Story]({link})\n"
                                f"━━━━━━━━━━━━━━━━━━━\n"
                                f"📌 *Impact: NIFTY 50 / NIFTYBEES Radar*"
                            )
                            send_telegram_msg(news_msg)

            if len(seen_news_links) > 500:
                seen_news_links = set(list(seen_news_links)[-200:])
        except Exception:
            pass

        time.sleep(30)

# --- 5. Weekly Monday Summary Report ---
def send_weekly_summary():
    try:
        etf = yf.Ticker("NIFTYBEES.NS")
        idx = yf.Ticker("^NSEI")
        
        df_etf = etf.history(period="1mo", interval="1d")
        df_idx = idx.history(period="1mo", interval="1d")
        
        last_week_data = df_etf.iloc[-6:-1]
        week_open = last_week_data['Open'].iloc[0]
        week_close = last_week_data['Close'].iloc[-1]
        week_high = last_week_data['High'].max()
        week_low = last_week_data['Low'].min()
        
        net_change_pct = ((week_close - week_open) / week_open) * 100
        total_swing_pct = ((week_high - week_low) / week_low) * 100
        
        idx_week_data = df_idx.iloc[-6:-1]
        idx_open = idx_week_data['Open'].iloc[0]
        idx_close = idx_week_data['Close'].iloc[-1]
        idx_change_pct = ((idx_close - idx_open) / idx_open) * 100
        
        if net_change_pct < 0:
            trend_badge = f"📉 FALL (-{abs(net_change_pct):.2f}%)"
            target_pct = max(abs(net_change_pct), 2.0)
            target_price = week_close * (1 + (target_pct / 100))
            advice = f"Dip buy hold karein for minimum *+{target_pct:.2f}%* bounce target (₹{target_price:.2f})."
        else:
            trend_badge = f"📈 GAIN (+{net_change_pct:.2f}%)"
            target_pct = 2.0
            target_price = week_close * 1.02
            advice = f"Market bullish. Naye dips par accumulate karein, target standard *+2.00%* (₹{target_price:.2f})."
            
        report_msg = (
            f"📊 *NIFTYBEES WEEKLY STRATEGY REPORT*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🗓️ *Previous Week Performance:*\n"
            f"• Trend: {trend_badge}\n"
            f"• Open Price: ₹{week_open:.2f}\n"
            f"• Close Price: ₹{week_close:.2f}\n"
            f"• Week High: ₹{week_high:.2f}\n"
            f"• Week Low: ₹{week_low:.2f}\n"
            f"• Total Swing: {total_swing_pct:.2f}%\n"
            f"• Nifty 50 Index: {idx_change_pct:+.2f}%\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 *Weekly Target Setup:*\n"
            f"• Holding Target: *+{target_pct:.2f}%*\n"
            f"• Target Price: *₹{target_price:.2f}*\n"
            f"💡 *Action:* {advice}\n"
            f"━━━━━━━━━━━━━━━━━━━"
        )
        send_telegram_msg(report_msg)
    except Exception as e:
        print(f"Weekly report error: {e}")

# --- 6. Core Advanced Engine (Multi-TF + Fibo + VIX + RSI) ---
def check_market():
    last_reported_drop = 0
    weekly_report_sent_date = ""
    ist = pytz.timezone("Asia/Kolkata")
    
    send_telegram_msg("🚀 *NIFTYBEES Institutional Pro Bot Live!*\n• Multi-TF S/R (15m, 1h, Daily, Weekly)\n• Fibonacci Golden Zones\n• RSI + India VIX Risk Meter\n• Tranche Capital Management Active!")

    while True:
        try:
            now = datetime.now(ist)
            today_str = now.strftime("%Y-%m-%d")
            
            # Monday 9:15 AM Weekly Summary
            if now.weekday() == 0 and now.hour == 9 and now.minute >= 15 and weekly_report_sent_date != today_str:
                send_weekly_summary()
                weekly_report_sent_date = today_str

            # Trading Hours: Mon-Fri 9:15 AM - 3:30 PM
            if now.weekday() < 5 and (now.hour > 9 or (now.hour == 9 and now.minute >= 15)) and (now.hour < 15 or (now.hour == 15 and now.minute <= 30)):
                etf = yf.Ticker("NIFTYBEES.NS")
                idx = yf.Ticker("^NSEI")
                vix = yf.Ticker("^INDIAVIX")

                # Multi-Timeframe Data Fetching
                df_15m = etf.history(period="5d", interval="15m")
                df_1h = etf.history(period="1mo", interval="60m")
                df_daily = etf.history(period="3mo", interval="1d")
                df_weekly = etf.history(period="1y", interval="1wk")
                
                curr_price = df_15m['Close'].iloc[-1]
                day_high = df_15m['High'].max()
                drop_pct = ((day_high - curr_price) / day_high) * 100

                # 1. India VIX Sentiment
                try:
                    df_vix = vix.history(period="2d")
                    curr_vix = df_vix['Close'].iloc[-1]
                    if curr_vix < 14:
                        vix_status = f"✅ Low Volatility ({curr_vix:.1f}) - Stable Market"
                    elif curr_vix <= 19:
                        vix_status = f"⚡ Moderate ({curr_vix:.1f}) - Normal Swings"
                    else:
                        vix_status = f"⚠️ HIGH RISK ({curr_vix:.1f}) - Wild Market Movements!"
                except Exception:
                    curr_vix = 15.0
                    vix_status = "Normal"

                # 2. RSI Multi-Timeframe (15m & 1h)
                rsi_15m = calculate_rsi(df_15m['Close'])
                rsi_1h = calculate_rsi(df_1h['Close'])
                rsi_badge = f"15m: {rsi_15m:.1f} | 1h: {rsi_1h:.1f}"
                if rsi_15m < 35 or rsi_1h < 35:
                    rsi_signal = "🟢 Oversold (Reversal / Bounce Zone!)"
                elif rsi_15m > 70:
                    rsi_signal = "🔴 Overbought (Avoid Fresh Entry)"
                else:
                    rsi_signal = "⚪ Neutral Range"

                # 3. Fibonacci Retracement (Calculated on recent 1-month swing)
                swing_high = df_1h['High'].max()
                swing_low = df_1h['Low'].min()
                fibs = calculate_fibonacci(swing_high, swing_low)

                # Check proximity to Fibonacci Golden Pocket
                if abs(curr_price - fibs['fib_618']) / curr_price < 0.004:
                    fibo_tag = f"🔥 Golden 61.8% Fibo Pocket (₹{fibs['fib_618']:.2f})"
                elif abs(curr_price - fibs['fib_500']) / curr_price < 0.004:
                    fibo_tag = f"📍 50% Equilibrium Fibo (₹{fibs['fib_500']:.2f})"
                elif abs(curr_price - fibs['fib_382']) / curr_price < 0.004:
                    fibo_tag = f"📍 38.2% Shallow Fibo (₹{fibs['fib_382']:.2f})"
                else:
                    fibo_tag = f"Between 50% (₹{fibs['fib_500']:.2f}) & 61.8% (₹{fibs['fib_618']:.2f})"

                # 4. Multi-Timeframe S/R Levels
                # 15m Support / Resistance (Recent 20 bars)
                s_15m = df_15m['Low'].tail(20).min()
                r_15m = df_15m['High'].tail(20).max()

                # Daily Classical Pivot
                prev_high = df_daily['High'].iloc[-2]
                prev_low = df_daily['Low'].iloc[-2]
                prev_close = df_daily['Close'].iloc[-2]
                pivot_d = (prev_high + prev_low + prev_close) / 3
                s1_d = (2 * pivot_d) - prev_high
                r1_d = (2 * pivot_d) - prev_low

                # Weekly Major Support
                s_weekly = df_weekly['Low'].iloc[-3:-1].min()

                # 5. Capital Tranche Management
                if drop_pct >= 3.5:
                    tranche_msg = "🔥 Deep Dip: Deploy 50% Capital (Major Reversal expected)"
                    target_pct = max(drop_pct, 3.5)
                elif drop_pct >= 2.0:
                    tranche_msg = "⚡ Moderate Dip: Deploy 30% Capital"
                    target_pct = max(drop_pct, 2.5)
                else:
                    tranche_msg = "🔹 First Dip: Deploy 20% Capital Only (Keep Cash Ready)"
                    target_pct = 2.0

                target_price = curr_price * (1 + (target_pct / 100))

                # Index Stats
                idx_df = idx.history(period="2d")
                idx_curr = idx_df['Close'].iloc[-1]
                idx_prev = idx_df['Close'].iloc[-2]
                idx_change = ((idx_curr - idx_prev) / idx_prev) * 100

                # Trigger: Har 1% high-drop par full confluence alert
                if drop_pct >= last_reported_drop + 1.0:
                    last_reported_drop = int(drop_pct)
                    img = generate_chart(df_15m)
                    
                    caption = (
                        f"🚨 *NIFTYBEES PRO CONFLUENCE ALERT*\n"
                        f"━━━━━━━━━━━━━━━━━━━\n"
                        f"💰 *Current Price:* ₹{curr_price:.2f} (Day Drop: -{drop_pct:.2f}%)\n"
                        f"📊 *Nifty 50:* {idx_curr:.2f} ({idx_change:+.2f}%)\n"
                        f"🌡️ *India VIX:* {vix_status}\n"
                        f"━━━━━━━━━━━━━━━━━━━\n"
                        f"📐 *FIBONACCI STATUS:*\n"
                        f"• {fibo_tag}\n"
                        f"• 61.8% Golden: ₹{fibs['fib_618']:.2f} | 50%: ₹{fibs['fib_500']:.2f}\n\n"
                        f"🧱 *MULTI-TIMEFRAME S/R:*\n"
                        f"• 15-Min: S: ₹{s_15m:.2f} | R: ₹{r_15m:.2f}\n"
                        f"• Daily Pivot S1: ₹{s1_d:.2f} | R1: ₹{r1_d:.2f}\n"
                        f"• Major Weekly Support: ₹{s_weekly:.2f}\n\n"
                        f"📈 *MOMENTUM & RSI:*\n"
                        f"• {rsi_badge}\n"
                        f"• Status: {rsi_signal}\n"
                        f"━━━━━━━━━━━━━━━━━━━\n"
                        f"💼 *CAPITAL POSITION SIZING:*\n"
                        f"👉 {tranche_msg}\n"
                        f"🎯 *Suggested Target:* +{target_pct:.2f}% (₹{target_price:.2f})\n"
                        f"━━━━━━━━━━━━━━━━━━━"
                    )
                    send_telegram_alert(img, caption)

            time.sleep(60)
        except Exception as e:
            time.sleep(15)

if __name__ == "__main__":
    t_web = threading.Thread(target=run_web_server, daemon=True)
    t_web.start()
    
    t_news = threading.Thread(target=scan_market_news, daemon=True)
    t_news.start()
    
    check_market()
