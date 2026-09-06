import os
import time
import threading
import xml.etree.ElementTree as ET
from datetime import datetime
import pytz
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests
import yfinance as yf
import mplfinance as mpf

BOT_TOKEN = "8695074642:AAHGHqaS1q-EkoEL5tY-gv7yvj5GAaF3lJ8"
CHAT_ID = "1152142289"

# Render keep-alive server
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is Running 24/7!")

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()

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

# --- Real-Time Market News Scanner ---
def scan_market_news():
    seen_news_links = set()
    feed_url = "https://news.google.com/rss/search?q=NIFTY+OR+NIFTYBEES+OR+%22Indian+Stock+Market%22+when:1h&hl=en-IN&gl=IN&ceid=IN:en"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    # Pehli baar me current feed ke links yaad rakh lo taaki shuru me purani news ka spam na ho
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
                                f"🔗 [Click Here to Read Full Story]({link})\n"
                                f"━━━━━━━━━━━━━━━━━━━\n"
                                f"📌 *Impact: NIFTY 50 / NIFTYBEES Radar*"
                            )
                            send_telegram_msg(news_msg)

            # Memory clean-up (cache 500 links se bada na ho)
            if len(seen_news_links) > 500:
                seen_news_links = set(list(seen_news_links)[-200:])
        except Exception:
            pass

        time.sleep(30)  # Har 30 second me breaking news check hogi

# --- Weekly Monday Strategy Report ---
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

# --- Market Monitoring Loop ---
def check_market():
    last_reported_drop = 0
    weekly_report_sent_date = ""
    ist = pytz.timezone("Asia/Kolkata")
    
    send_telegram_msg("🚀 *NIFTYBEES Super Bot Active: 24/7 Server + Weekly Setup + Realtime News Live!*")

    while True:
        try:
            now = datetime.now(ist)
            today_str = now.strftime("%Y-%m-%d")
            
            # Monday 9:15 AM Weekly Report
            if now.weekday() == 0 and now.hour == 9 and now.minute >= 15 and weekly_report_sent_date != today_str:
                send_weekly_summary()
                weekly_report_sent_date = today_str

            # Intraday scanning (Trading days Monday-Friday, 9:15 AM - 3:30 PM)
            if now.weekday() < 5 and (now.hour > 9 or (now.hour == 9 and now.minute >= 15)) and (now.hour < 15 or (now.hour == 15 and now.minute <= 30)):
                etf = yf.Ticker("NIFTYBEES.NS")
                idx = yf.Ticker("^NSEI")

                df_etf = etf.history(period="5d", interval="5m")
                df_daily = etf.history(period="1mo", interval="1d")
                df_idx = idx.history(period="2d")

                curr_price = df_etf['Close'].iloc[-1]
                day_high = df_etf['High'].max()

                week_open_price = df_daily['Open'].iloc[-5]
                running_weekly_change = ((curr_price - week_open_price) / week_open_price) * 100
                
                if running_weekly_change < 0:
                    current_target_pct = max(abs(running_weekly_change), 2.0)
                else:
                    current_target_pct = 2.0
                target_price = curr_price * (1 + (current_target_pct / 100))

                prev_high = df_etf['High'].iloc[-2]
                prev_low = df_etf['Low'].iloc[-2]
                prev_close = df_etf['Close'].iloc[-2]
                pivot = (prev_high + prev_low + prev_close) / 3
                s1 = (2 * pivot) - prev_high
                r1 = (2 * pivot) - prev_low

                idx_curr = df_idx['Close'].iloc[-1]
                idx_prev = df_idx['Close'].iloc[-2]
                idx_change = ((idx_curr - idx_prev) / idx_prev) * 100

                drop_pct = ((day_high - curr_price) / day_high) * 100

                if curr_price <= s1:
                    level_status = f"Support 1 ke paas (₹{s1:.2f})"
                elif curr_price >= r1:
                    level_status = f"Resistance 1 ke paas (₹{r1:.2f})"
                else:
                    level_status = f"Consolidating (Pivot: ₹{pivot:.2f})"

                if drop_pct >= last_reported_drop + 1.0:
                    last_reported_drop = int(drop_pct)
                    img = generate_chart(df_etf)
                    caption = (
                        f"🚨 *NIFTYBEES ACCUMULATION ALERT*\n"
                        f"━━━━━━━━━━━━━━━━━━━\n"
                        f"💰 *Current Price:* ₹{curr_price:.2f}\n"
                        f"📉 *Day Fall:* -{drop_pct:.2f}% (High: ₹{day_high:.2f})\n"
                        f"🗓️ *Weekly Net Move:* {running_weekly_change:+.2f}%\n"
                        f"🎯 *Suggested Target:* +{current_target_pct:.2f}% (₹{target_price:.2f})\n"
                        f"🎯 *Level:* {level_status}\n"
                        f"📊 *Nifty 50:* {idx_curr:.2f} ({idx_change:+.2f}%)\n"
                        f"━━━━━━━━━━━━━━━━━━━\n"
                        f"⚡ *Entry Level Check Karein!*"
                    )
                    send_telegram_alert(img, caption)

            time.sleep(60)
        except Exception:
            time.sleep(15)

if __name__ == "__main__":
    # Web server background thread
    t_web = threading.Thread(target=run_web_server, daemon=True)
    t_web.start()
    
    # Realtime News scanner background thread
    t_news = threading.Thread(target=scan_market_news, daemon=True)
    t_news.start()
    
    # Main price & weekly scanner
    check_market()
