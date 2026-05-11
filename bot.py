import os
import requests
import hashlib
import hmac
import time
import json

# =========================
# SETTINGS
# =========================

GRID = 33

# LOT SIZE
LOT_SIZE = 1

# API KEYS
API_KEY = os.getenv("DELTA_API_KEY")
API_SECRET = os.getenv("DELTA_API_SECRET")

# DELTA INDIA API
BASE_URL = "https://api.india.delta.exchange"

# GOLD SYMBOL
SYMBOL = "PAXGUSD"

# =========================

position = 0
last_trade_price = None


# =========================
# GET LIVE PRICE
# =========================

def get_price():

    url = f"{BASE_URL}/v2/tickers/{SYMBOL}"

    response = requests.get(url)

    data = response.json()

    return float(data["result"]["close"])


# =========================
# GENERATE SIGNATURE
# =========================

def generate_signature(message):

    return hmac.new(
        API_SECRET.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()


# =========================
# PLACE ORDER
# =========================

def place_order(side):

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

    # 🔥 CORRECT SIGNATURE FORMAT
    signature_data = (
        "POST" +
        timestamp +
        endpoint +
        body
    )

    signature = generate_signature(signature_data)

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "api-key": API_KEY,
        "timestamp": timestamp,
        "signature": signature
    }

    response = requests.post(
        url,
        headers=headers,
        data=body
    )

    print("ORDER RESPONSE:", response.text)


# =========================
# GRID BOT
# =========================

print("GRID BOT STARTED...")

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

            print("GRID BUY:", price)

            place_order("buy")

        # SELL EVERY 33 UP
        elif price >= last_trade_price + GRID and position > 0:

            position -= 1

            last_trade_price = price

            print("GRID SELL:", price)

            place_order("sell")

    except Exception as e:

        print("ERROR:", e)

    time.sleep(5)
