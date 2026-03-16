import ccxt
import pandas as pd
import ta
import requests
import time
import pytz
import json
import os
import traceback

from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler


# =========================
# НАСТРОЙКИ
# =========================

BOT_TOKEN = '8698198268:AAFQyjs3vXMtBfuUpib0TQnpyBfrOh0HcBs'

USERS = [
    '489918981', '829614314'
]

symbols = [
'BTC/USDT','ETH/USDT','SOL/USDT','BNB/USDT',
'PEPE/USDT','DOGE/USDT','WIF/USDT','SUI/USDT',
'RENDER/USDT','AVAX/USDT','TIA/USDT','LINK/USDT'
]

exchange = ccxt.binance({
    "enableRateLimit": True
})

kyiv = pytz.timezone("Europe/Kiev")


# =========================
# ХРАНЕНИЕ СИГНАЛОВ
# =========================

signals_file = "signals.json"

if os.path.exists(signals_file):

    with open(signals_file,"r") as f:
        sent_signals=set(json.load(f))

else:

    sent_signals=set()


stats={
    "signals":0
}


# =========================
# TELEGRAM
# =========================

def send_telegram(text):

    for user in USERS:

        url=f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

        try:

            requests.post(url,data={
                "chat_id":user,
                "text":text
            })

        except:
            pass


# =========================
# СТАРТ
# =========================

def send_start_message():

    now=datetime.now(kyiv)

    text=(
        f"🤖 Бот запущен\n"
        f"Время: {now.strftime('%Y-%m-%d %H:%M:%S')} Киев\n"
        f"Монет: {len(symbols)}"
    )

    send_telegram(text)


# =========================
# СТАТИСТИКА
# =========================

def send_stats():

    now=datetime.now(kyiv)

    text=(
        f"📊 Статистика бота\n\n"
        f"Время: {now.strftime('%Y-%m-%d %H:%M')} Киев\n\n"
        f"Найдено сигналов: {stats['signals']}"
    )

    send_telegram(text)

    stats["signals"]=0


# =========================
# ПРОВЕРКА СВЕЖЕСТИ
# =========================

from datetime import datetime, UTC

def is_recent_signal(signal_time):

    now = datetime.now(UTC)

    signal_time = signal_time.to_pydatetime().replace(tzinfo=UTC)

    delta = now - signal_time

    return delta.total_seconds() < 3600


# =========================
# ЗАГРУЗКА ДАННЫХ
# =========================

def get_data(symbol,tf,limit=300):

    for attempt in range(5):

        try:

            time.sleep(0.4)

            ohlcv=exchange.fetch_ohlcv(symbol,timeframe=tf,limit=limit)

            df=pd.DataFrame(
                ohlcv,
                columns=["time","open","high","low","close","volume"]
            )

            df["time"]=pd.to_datetime(df["time"],unit="ms")

            df["rsi"]=ta.momentum.RSIIndicator(df["close"],14).rsi()

            return df

        except Exception as e:

            print(f"Ошибка загрузки {symbol} {tf}")

            time.sleep(5)

    return None


# =========================
# SWING
# =========================

def find_swings(df,threshold=0.005):

    highs=[]
    lows=[]

    last_pivot=0
    last_price=df.close.iloc[0]

    trend=None

    for i in range(1,len(df)):

        price=df.close.iloc[i]

        change=(price-last_price)/last_price

        if trend is None:

            if abs(change)>=threshold:

                if change>0:
                    trend="up"
                    lows.append(last_pivot)

                else:
                    trend="down"
                    highs.append(last_pivot)

                last_pivot=i
                last_price=price

        elif trend=="up":

            if price>last_price:

                last_price=price
                last_pivot=i

            elif (last_price-price)/last_price>=threshold:

                highs.append(last_pivot)

                trend="down"
                last_price=price
                last_pivot=i

        elif trend=="down":

            if price<last_price:

                last_price=price
                last_pivot=i

            elif (price-last_price)/last_price>=threshold:

                lows.append(last_pivot)

                trend="up"
                last_price=price
                last_pivot=i

    return highs,lows


# =========================
# ПОДТВЕРЖДЕНИЕ 15m
# =========================

def confirm_15m(symbol,start_time,level,direction):

    df=get_data(symbol,"15m")

    if df is None:
        return None

    df=df[df.time>start_time]

    if direction=="SHORT":

        for i in range(len(df)):

            if df.low.iloc[i]<level:
                return df.time.iloc[i]

    if direction=="LONG":

        for i in range(len(df)):

            if df.high.iloc[i]>level:
                return df.time.iloc[i]

    return None


# =========================
# TP / SL
# =========================

def trade_levels(entry,direction):

    risk=entry*0.01

    if direction=="LONG":

        sl=entry-risk
        tp1=entry+risk
        tp2=entry+risk*2
        tp3=entry+risk*3

    else:

        sl=entry+risk
        tp1=entry-risk
        tp2=entry-risk*2
        tp3=entry-risk*3

    return sl,tp1,tp2,tp3


# =========================
# ОТПРАВКА СИГНАЛА
# =========================

def send_signal(symbol,direction,entry_time,level):

    if not is_recent_signal(entry_time):
        return

    signal_id=f"{symbol}_{direction}_{entry_time}"

    if signal_id in sent_signals:
        return

    sent_signals.add(signal_id)

    with open(signals_file,"w") as f:
        json.dump(list(sent_signals),f)

    entry=level

    sl,tp1,tp2,tp3=trade_levels(entry,direction)

    time_kiev=entry_time.tz_localize("UTC").tz_convert(kyiv)

    text=(
        f"🚨 Сигнал\n\n"
        f"Монета: {symbol}\n"
        f"Тип: {direction}\n"
        f"Время: {time_kiev.strftime('%Y-%m-%d %H:%M')} Киев\n\n"
        f"Entry: {round(entry,8)}\n"
        f"Stop: {round(sl,8)}\n\n"
        f"TP1: {round(tp1,8)}\n"
        f"TP2: {round(tp2,8)}\n"
        f"TP3: {round(tp3,8)}"
    )

    send_telegram(text)

    stats["signals"]+=1


# =========================
# ПОИСК СЕТАПОВ
# =========================

def detect_setups(symbol):

    df=get_data(symbol,"1h")

    if df is None:
        return

    highs,lows=find_swings(df)

    # SHORT

    for i in range(1,len(highs)):

        h1=highs[i-1]
        h2=highs[i]

        if h2 < len(df)-3:
            continue

        if df.high.iloc[h2] < df.high.iloc[h1] and df.rsi.iloc[h1]>70:

            lows_between=[l for l in lows if h1<l<h2]

            if not lows_between:
                continue

            l1=lows_between[-1]

            level=df.low.iloc[l1]

            entry=confirm_15m(symbol,df.time.iloc[h2],level,"SHORT")

            if entry:

                send_signal(symbol,"SHORT",entry,level)

    # LONG

    for i in range(1,len(lows)):

        l1=lows[i-1]
        l2=lows[i]

        if l2 < len(df)-3:
            continue

        if df.low.iloc[l2] > df.low.iloc[l1] and df.rsi.iloc[l1]<30:

            highs_between=[h for h in highs if l1<h<l2]

            if not highs_between:
                continue

            h1=highs_between[-1]

            level=df.high.iloc[h1]

            entry=confirm_15m(symbol,df.time.iloc[l2],level,"LONG")

            if entry:

                send_signal(symbol,"LONG",entry,level)


# =========================
# ОСНОВНОЙ ЦИКЛ
# =========================

def run_bot():

    while True:

        try:

            for symbol in symbols:

                detect_setups(symbol)

            time.sleep(120)

        except Exception:

            print("Ошибка работы бота")
            print(traceback.format_exc())

            time.sleep(30)


# =========================
# ПЛАНИРОВЩИК
# =========================

scheduler=BackgroundScheduler(timezone=kyiv)

# каждые 3 часа начиная с 23:00
scheduler.add_job(send_stats,"cron",hour="23,8,17",minute=0)

scheduler.start()


# =========================
# СТАРТ
# =========================

send_start_message()

run_bot()
