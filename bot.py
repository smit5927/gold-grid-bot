print("BOT FILE RUNNING...")
import os
import time
import json
import hmac
import hashlib
import requests
import traceback

# =========================
# CONFIG
# =========================

BASE_URL = "https://api.india.delta.exchange"
SYMBOL = "PAXGUSD"

GRID = 33
LOT_SIZE = int(os.getenv("LOT_SIZE", "1"))
SLEEP_SECONDS = 5

API_KEY = os.getenv("DELTA_API_KEY")
API_SECRET = os.getenv("DELTA_API_SECRET")

STATE_FILE = "state.json"
USER_AGENT = "python-grid-bot"

print("BOT STARTED...")
print("API KEY LOADED:", API_KEY is not None)
print("API SECRET LOADED:", API_SECRET is not None)
print("SYMBOL:", SYMBOL)
print("GRID:", GRID)
print("LOT_SIZE:", LOT_SIZE)

if not API_KEY or not API_SECRET:
    raise Exception("DELTA_API_KEY / DELTA_API_SECRET missing!")

# =========================
# STATE
# =========================

def load_state():
    if not os.path.exists(STATE_FILE):
        return {"last_trade_price": None}

    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except:
        return {"last_trade_price": None}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# =========================
# SIGNATURE
# =========================

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

    r = requests.get(url, headers=headers, timeout=15)
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

    r = requests.post(url, headers=headers, data=body, timeout=15)
    return r.json()


# =========================
# EXCHANGE HELPERS
# =========================

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
    """
    Only last BUY fill price (ignore sell fills)
    """
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
# SAFE RECOVERY LOGIC
# =========================

def safe_recover_last_price(state_last, exchange_last_buy, live_price):
    """
    Choose best last_trade_price:
    Priority:
    1) If state exists and close to market -> use state
    2) Else use exchange last buy fill
    3) Else fallback to live price
    """

    if state_last is not None:
        # if state_last not crazy far (within 10 grids)
        if abs(state_last - live_price) <= GRID * 10:
            return state_last

    if exchange_last_buy is not None:
        return exchange_last_buy

    return live_price


# =========================
# STARTUP
# =========================

state = load_state()
last_trade_price = state.get("last_trade_price")

try:
    price = get_live_price()
    pos_size = get_open_position_size()

    print("STARTUP LIVE PRICE:", price)
    print("STARTUP POS SIZE:", pos_size)
    print("STATE LAST PRICE:", last_trade_price)

    if pos_size > 0:
        exchange_last_buy = get_last_buy_fill_price()
        print("EXCHANGE LAST BUY FILL:", exchange_last_buy)

        last_trade_price = safe_recover_last_price(last_trade_price, exchange_last_buy, price)
        state["last_trade_price"] = last_trade_price
        save_state(state)

        print("FINAL RECOVERED LAST PRICE:", last_trade_price)

    else:
        print("NO POSITION FOUND -> BOT WILL WAIT FOR MANUAL BUY")
        last_trade_price = None
        state["last_trade_price"] = None
        save_state(state)

except Exception as e:
    print("STARTUP ERROR:", str(e))
    traceback.print_exc()


# =========================
# MAIN LOOP
# =========================

while True:
    try:
        price = get_live_price()
        pos_size = get_open_position_size()

        print("LIVE PRICE:", price, "| LAST:", last_trade_price, "| POS:", pos_size)

        # if no position -> pause
        if pos_size == 0:
            last_trade_price = None
            state["last_trade_price"] = None
            save_state(state)
            time.sleep(SLEEP_SECONDS)
            continue

        # if last_trade_price missing -> recover from fills
        if last_trade_price is None:
            exchange_last_buy = get_last_buy_fill_price()
            if exchange_last_buy is not None:
                last_trade_price = exchange_last_buy
                state["last_trade_price"] = last_trade_price
                save_state(state)
                print("RECOVERED LAST PRICE DURING RUN:", last_trade_price)
            time.sleep(SLEEP_SECONDS)
            continue

        # BUY GRID
        if price <= last_trade_price - GRID:
            print("GRID BUY EXECUTING...")
            resp = place_market_order("buy")

            if resp.get("success") is True:
                # use real executed fill price from exchange
                new_fill = get_last_buy_fill_price()
                if new_fill:
                    last_trade_price = new_fill
                else:
                    last_trade_price = price

                state["last_trade_price"] = last_trade_price
                save_state(state)
                print("UPDATED LAST AFTER BUY:", last_trade_price)

        # SELL GRID
        elif price >= last_trade_price + GRID:
            print("GRID SELL EXECUTING...")
            resp = place_market_order("sell")

            if resp.get("success") is True:
                # after sell, keep last_trade_price as sell execution level
                last_trade_price = price
                state["last_trade_price"] = last_trade_price
                save_state(state)
                print("UPDATED LAST AFTER SELL:", last_trade_price)

    except Exception as e:
        print("RUNTIME ERROR:", str(e))
        traceback.print_exc()

    time.sleep(SLEEP_SECONDS)
