import os
import requests
import hashlib
import hmac
import time
import json
import traceback

# =========================
# SETTINGS
# =========================

GRID = 33
LOT_SIZE = 1

BASE_URL = "https://api.india.delta.exchange"
SYMBOL = "PAXGUSD"

API_KEY = os.getenv("DELTA_API_KEY")
API_SECRET = os.getenv("DELTA_API_SECRET")

STATE_FILE = "state.json"

print("BOT STARTED...")
print("API KEY LOADED:", API_KEY is not None)
print("API SECRET LOADED:", API_SECRET is not None)

# =========================


def load_state():
    if not os.path.exists(STATE_FILE):
        return {"position": 0, "last_trade_price": None}

    try:
        with open(STATE_FILE, "r") as f:
            data = json.load(f)
            return {
                "position": int(data.get("position", 0)),
                "last_trade_price": data.get("last_trade_price", None)
            }
    except:
        return {"position": 0, "last_trade_price": None}


def save_state(position, last_trade_price):
    data = {
        "position": position,
        "last_trade_price": last_trade_price
    }
    with open(STATE_FILE, "w") as f:
        json.dump(data, f)


state = load_state()
position = state["position"]
last_trade_price = state["last_trade_price"]

print("LOADED STATE => position:", position, "last_trade_price:", last_trade_price)


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
    return res.json()


# =========================
# MAIN LOOP
# =========================

while True:
    try:
        price = get_price()
        print("LIVE PRICE:", price, "| POSITION:", position, "| LAST:", last_trade_price)

        # FIRST BUY only if no state saved
        if last_trade_price is None:
            print("FIRST BUY")
            resp = place_order("buy")

            if resp.get("success") is True:
                last_trade_price = price
                position = 1
                save_state(position, last_trade_price)

        # BUY EVERY 33 DOWN
        elif price <= last_trade_price - GRID:
            print("GRID BUY:", price)
            resp = place_order("buy")

            if resp.get("success") is True:
                position += 1
                last_trade_price = price
                save_state(position, last_trade_price)

        # SELL EVERY 33 UP
        elif price >= last_trade_price + GRID and position > 0:
            print("GRID SELL:", price)
            resp = place_order("sell")

            if resp.get("success") is True:
                position -= 1
                last_trade_price = price
                save_state(position, last_trade_price)

        # If position becomes 0, reset state to allow fresh cycle
        if position == 0:
            print("POSITION ZERO -> RESET STATE")
            last_trade_price = None
            save_state(position, last_trade_price)

    except Exception as e:
        print("ERROR:", str(e))
        traceback.print_exc()

    time.sleep(5)
