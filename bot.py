import os
import time
import json
import hmac
import hashlib
import requests
import traceback

BASE_URL = "https://api.india.delta.exchange"
SYMBOL = "PAXGUSD"

GRID = 33
LOT_SIZE = int(os.getenv("LOT_SIZE", "1"))
SLEEP_SECONDS = 5

API_KEY = os.getenv("DELTA_API_KEY")
API_SECRET = os.getenv("DELTA_API_SECRET")

USER_AGENT = "python-grid-bot"

print("BOT STARTED...")
print("API KEY LOADED:", API_KEY is not None)
print("API SECRET LOADED:", API_SECRET is not None)
print("SYMBOL:", SYMBOL)
print("GRID:", GRID)
print("LOT_SIZE:", LOT_SIZE)


def generate_signature(message: str) -> str:
    return hmac.new(
        API_SECRET.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()


def private_get(endpoint: str, params=None):
    if params is None:
        params = {}

    query_string = ""
    if params:
        query_string = "?" + "&".join([f"{k}={v}" for k, v in params.items()])

    full_endpoint = endpoint + query_string
    url = BASE_URL + full_endpoint

    timestamp = str(int(time.time()))
    signature_data = "GET" + timestamp + full_endpoint
    signature = generate_signature(signature_data)

    headers = {
        "Accept": "application/json",
        "api-key": API_KEY,
        "timestamp": timestamp,
        "signature": signature,
        "User-Agent": USER_AGENT
    }

    r = requests.get(url, headers=headers, timeout=10)
    return r.json()


def private_post(endpoint: str, payload: dict):
    url = BASE_URL + endpoint
    timestamp = str(int(time.time()))
    body = json.dumps(payload)

    signature_data = "POST" + timestamp + endpoint + body
    signature = generate_signature(signature_data)

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "api-key": API_KEY,
        "timestamp": timestamp,
        "signature": signature,
        "User-Agent": USER_AGENT
    }

    r = requests.post(url, headers=headers, data=body, timeout=10)
    return r.json()


def get_live_price():
    url = f"{BASE_URL}/v2/tickers/{SYMBOL}"
    r = requests.get(url, timeout=10)
    data = r.json()

    if data.get("success") is not True:
        raise Exception("Ticker API failed: " + str(data))

    return float(data["result"]["close"])


def get_open_position_size():
    data = private_get("/v2/positions/margined")

    if data.get("success") is not True:
        raise Exception("Positions API failed: " + str(data))

    for p in data.get("result", []):
        if p.get("product_symbol") == SYMBOL:
            return float(p.get("size", 0))

    return 0.0


def get_last_buy_fill_price():
    data = private_get("/v2/fills", params={"page_size": 200})

    if data.get("success") is not True:
        raise Exception("Fills API failed: " + str(data))

    fills = data.get("result", [])

    for f in fills:
        if f.get("product_symbol") == SYMBOL and f.get("side") == "buy":
            return float(f.get("price"))

    return None


def place_market_order(side: str):
    payload = {
        "product_symbol": SYMBOL,
        "size": LOT_SIZE,
        "side": side,
        "order_type": "market_order"
    }

    res = private_post("/v2/orders", payload)
    print("ORDER RESPONSE:", res)
    return res


# =========================
# RECOVERY ON RESTART
# =========================

last_trade_price = None
position = 0

try:
    position = get_open_position_size()
    print("EXCHANGE POSITION SIZE:", position)

    if position > 0:
        last_trade_price = get_last_buy_fill_price()
        print("RECOVERED LAST BUY PRICE:", last_trade_price)

    else:
        print("NO POSITION FOUND -> WILL AUTO BUY")

except Exception as e:
    print("STARTUP RECOVERY ERROR:", str(e))
    traceback.print_exc()


# =========================
# MAIN LOOP
# =========================

while True:
    try:
        price = get_live_price()
        print("LIVE PRICE:", price, "| LAST:", last_trade_price, "| POS:", position)

        # ALWAYS KEEP 1 LOT IN MARKET
        if position == 0:
            print("NO POSITION -> AUTO BUY")
            resp = place_market_order("buy")

            if resp.get("success") is True:
                last_trade_price = price
                position += LOT_SIZE

        # GRID BUY
        elif price <= last_trade_price - GRID:
            print("GRID BUY EXECUTING...")
            resp = place_market_order("buy")

            if resp.get("success") is True:
                last_trade_price = price
                position += LOT_SIZE

        # GRID SELL
        elif position > 0 and price >= last_trade_price + GRID:
            print("GRID SELL EXECUTING...")
            resp = place_market_order("sell")

            if resp.get("success") is True:
                last_trade_price = price
                position -= LOT_SIZE
                if position < 0:
                    position = 0

    except Exception as e:
        print("RUNTIME ERROR:", str(e))
        traceback.print_exc()

    time.sleep(SLEEP_SECONDS)
