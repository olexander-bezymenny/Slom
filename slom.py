import ccxt
import pandas as pd
import ta
import requests
import time
from datetime import datetime, timedelta

# TELEGRAM
BOT_TOKEN = '8605521122:AAHuywxOWTc31YovOo2-JV2su6Cb5K7KgIw'

CHAT_IDS = [
    '489918981', '829614314'
]

# Биржа
exchange = ccxt.binance()

# Монеты
symbols = [
    'BTC/USDT','ETH/USDT','SOL/USDT','BNB/USDT',
    'PEPE/USDT','DOGE/USDT','WIF/USDT','SUI/USDT',
    'RENDER/USDT','AVAX/USDT','TIA/USDT','LINK/USDT'
]

# уже отправленные сигналы
sent_signals = {}


# -----------------------------------
# TELEGRAM SEND
# -----------------------------------

def send_telegram(text):

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    for chat in CHAT_IDS:

        data = {
            "chat_id": chat,
            "text": text
        }

        try:
            requests.post(url, data=data)
        except:
            pass


# -----------------------------------
# DATA
# -----------------------------------

def get_data(symbol, tf, limit=500):

    data = exchange.fetch_ohlcv(symbol, timeframe=tf, limit=limit)

    df = pd.DataFrame(
        data,
        columns=["time","open","high","low","close","volume"]
    )

    df["time"] = (
        pd.to_datetime(df["time"], unit="ms")
        .dt.tz_localize("UTC")
        .dt.tz_convert("Europe/Kyiv")
        .dt.tz_localize(None)
    )

    df["rsi"] = ta.momentum.RSIIndicator(df["close"], 14).rsi()

    return df


# -----------------------------------
# SWINGS (по тренду)
# -----------------------------------

def find_swings_trend(df):

    highs = []
    lows = []

    trend = None
    last_high = None
    last_low = None

    for i in range(2, len(df)-2):

        if df.high.iloc[i] > df.high.iloc[i-1] and df.high.iloc[i] > df.high.iloc[i+1]:

            if last_high is None or df.high.iloc[i] > df.high.iloc[last_high]:

                last_high = i
                highs.append(i)
                trend = "up"

        if df.low.iloc[i] < df.low.iloc[i-1] and df.low.iloc[i] < df.low.iloc[i+1]:

            if last_low is None or df.low.iloc[i] < df.low.iloc[last_low]:

                last_low = i
                lows.append(i)
                trend = "down"

    return highs, lows


# -----------------------------------
# CONFIRM 15m (пробой телом)
# -----------------------------------

def confirm_15m(symbol, level, direction, start_time):

    df = get_data(symbol, "15m", 200)

    # только после второй вершины
    df = df[df.time > start_time].reset_index(drop=True)

    if direction == "SHORT":

        for i in range(len(df)):

            # пробой телом
            if df.close.iloc[i] < level:

                return df.time.iloc[i]

    if direction == "LONG":

        for i in range(len(df)):

            if df.close.iloc[i] > level:

                return df.time.iloc[i]

    return None


# -----------------------------------
# DETECT SETUPS
# -----------------------------------

def detect_setups(symbol):

    df = get_data(symbol, "1h", 500)

    highs, lows = find_swings_trend(df)

    setups = []

    # SHORT
    for i in range(1, len(highs)):

        h1 = highs[i-1]
        h2 = highs[i]

        if df.high.iloc[h2] < df.high.iloc[h1] and df.rsi.iloc[h1] > 70:

            lows_between = [l for l in lows if h1 < l < h2]

            if not lows_between:
                continue

            l1 = lows_between[-1]

            level = df.low.iloc[l1]

            entry = confirm_15m(
                symbol,
                level,
                "SHORT",
                df.time.iloc[h2]
            )

            if entry:

                setups.append({
                    "symbol": symbol,
                    "type": "SHORT",
                    "time": entry,
                    "level": level
                })

    # LONG
    for i in range(1, len(lows)):

        l1 = lows[i-1]
        l2 = lows[i]

        if df.low.iloc[l2] > df.low.iloc[l1] and df.rsi.iloc[l1] < 30:

            highs_between = [h for h in highs if l1 < h < l2]

            if not highs_between:
                continue

            h1 = highs_between[-1]

            level = df.high.iloc[h1]

            entry = confirm_15m(
                symbol,
                level,
                "LONG",
                df.time.iloc[l2]
            )

            if entry:

                setups.append({
                    "symbol": symbol,
                    "type": "LONG",
                    "time": entry,
                    "level": level
                })

    return setups

# =========================
# ЕЖЕДНЕВНАЯ СТАТИСТИКА
# =========================

def send_daily_stats():

    global stats

    msg = (
        "📊 Статистика за сутки\n\n"
        f"Всего сигналов: {stats['total']}\n"
        f"LONG: {stats['LONG']}\n"
        f"SHORT: {stats['SHORT']}"
    )

    send_telegram(msg)

    stats = {
        "total": 0,
        "LONG": 0,
        "SHORT": 0
    }


# -----------------------------------
# CHECK SIGNALS
# -----------------------------------

def check_signals():

    global sent_signals

    for symbol in symbols:

        try:

            now = datetime.now()

            # ежедневная статистика в 08:00
            if now.hour == 8 and (last_stats_day != now.date()):

                send_daily_stats()
                last_stats_day = now.date()
            setups = detect_setups(symbol)

            for setup in setups:

                key = f"{setup['symbol']}_{setup['time']}"

                if key in sent_signals:
                    continue

                text = (
                    "🚨 SIGNAL\n"
                    f"{setup['symbol']}\n"
                    f"{setup['type']}\n"
                    f"Entry: {setup['time']}\n"
                    f"Level: {setup['level']}"
                )

                send_telegram(text)

                sent_signals[key] = True

                print("Отправлен сигнал:", text)

        except Exception as e:

            print("Ошибка:", symbol, e)


# -----------------------------------
# MAIN LOOP
# -----------------------------------

print("Бот запущен")

while True:

    check_signals()

    # проверка каждые 3 минуты
    time.sleep(180)
