import os
import requests
import hashlib
import hmac
import time
import json
import traceback
import sys
sys.stdout.reconfigure(line_buffering=True)

# =========================
# SETTINGS
# =========================

GRID = 33
LOT_SIZE = 1

BASE_URL = "https://api.india.delta.exchange"
SYMBOL = "PAXGUSD"

API_KEY = os.getenv("DELTA_API_KEY")
API_SECRET = os.getenv("DELTA_API_SECRET")

print("BOT STARTED...")
print("API KEY LOADED:", API_KEY is not None)
print("API SECRET LOADED:", API_SECRET is not None)

# =========================

position = 0
last_trade_price = None


def get_price():
    url = f"{BASE_URL}/v2/tickers/{SYMBOL}"
    r = requests.get(url, timeout=10)
    data = r.json()

    if data.get("success") is not True:
        raise Exception("Ticker API failed: " + str(data))

    if data.get("result") is None:
        raise Exception("Ticker result is None: " + str(data))

    return float(data["result"]["close"])


def generate_signature(message: str) -> str:
    return hmac.new(
        API_SECRET.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()


def place_order(side: str):
    endpoint = "/v2/orders"
    url = BASE_URL + endpoint
    timestamp = str(int(time.time()))

    payload = {
        "product_symbol": SYMBOL,
        "size": LOT_SIZE,
        "side": side,
        "order_type": "market_order"
    }

    body = json.dumps(payload)

    signature_data = "POST" + timestamp + endpoint + body
    signature = generate_signature(signature_data)

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "api-key": API_KEY,
        "timestamp": timestamp,
        "signature": signature
    }

    res = requests.post(url, headers=headers, data=body, timeout=10)
    print("ORDER RESPONSE:", res.text)


# =========================
# MAIN LOOP
# =========================

while True:
    try:
        price = get_price()
        print("LIVE PRICE:", price)

        # FIRST BUY
        if last_trade_price is None:
            last_trade_price = price
            position = 1
            print("FIRST BUY")
            place_order("buy")

        # BUY EVERY 33 DOWN
        elif price <= last_trade_price - GRID:
            position += 1
            last_trade_price = price
            print("GRID BUY:", price, "POSITION:", position)
            place_order("buy")

        # SELL EVERY 33 UP
        elif price >= last_trade_price + GRID and position > 0:
            position -= 1
            last_trade_price = price
            print("GRID SELL:", price, "POSITION:", position)
            place_order("sell")

    except Exception as e:
        print("ERROR:", str(e))
        traceback.print_exc()

    time.sleep(5)
