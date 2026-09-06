import time
import requests
import yfinance as yf
import mplfinance as mpf

BOT_TOKEN = "8695074642:AAHGHqaS1q-EkoEL5tY-gv7yvj5GAaF3lJ8"
CHAT_ID = "1152142289"

def send_telegram_alert(img_path, caption_text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    with open(img_path, 'rb') as photo:
        requests.post(url, data={'chat_id': CHAT_ID, 'caption': caption_text, 'parse_mode': 'Markdown'}, files={'photo': photo})

def generate_chart(df):
    chart_path = "chart.png"
    mpf.plot(df.tail(30), type='candle', style='charles', savefig=chart_path, volume=False)
    return chart_path

def check_market():
    last_reported_drop = 0
    print("Bot active ho chuka hai...")

    # Startup test ping
    test_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(test_url, json={"chat_id": CHAT_ID, "text": "🚀 Cloud Bot 24/7 Active! NIFTYBEES scanning shuru."})

    while True:
        try:
            etf = yf.Ticker("NIFTYBEES.NS")
            idx = yf.Ticker("^NSEI")

            df_etf = etf.history(period="5d", interval="5m")
            df_idx = idx.history(period="2d")

            curr_price = df_etf['Close'].iloc[-1]
            day_high = df_etf['High'].max()
            
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
                    f"🚨 *NIFTYBEES FOCUS*\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"📉 *Fall:* -{drop_pct:.2f}% (From High)\n"
                    f"💰 *Current Price:* ₹{curr_price:.2f}\n"
                    f"🎯 *Level:* {level_status}\n"
                    f"📊 *Nifty 50 Index:* {idx_curr:.2f} ({idx_change:+.2f}%)\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"⚡ *Keep on radar!*"
                )
                send_telegram_alert(img, caption)

            time.sleep(60)
        except Exception:
            time.sleep(15)

if __name__ == "__main__":
    check_market()
