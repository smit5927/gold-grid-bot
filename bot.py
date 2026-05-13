import os
import sys
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

GRID = 15   # ✅ CHANGED FROM 33 TO 15
LOT_SIZE = float(os.getenv("LOT_SIZE", "1"))
SLEEP_SECONDS = 5

API_KEY = os.getenv("DELTA_API_KEY")
API_SECRET = os.getenv("DELTA_API_SECRET")

STATE_FILE = "state.json"
USER_AGENT = "python-grid-bot-final"

print("BOT FILE RUNNING...")
sys.stdout.flush()

print("BOT STARTED...")
print("SYMBOL:", SYMBOL)
print("GRID:", GRID)
print("LOT_SIZE:", LOT_SIZE)
sys.stdout.flush()

if not API_KEY or not API_SECRET:
    raise Exception("DELTA_API_KEY / DELTA_API_SECRET missing!")

# =========================
# STATE
# =========================

def load_state():
    if not os.path.exists(STATE_FILE):
        return {
            "base_price": None,
            "next_buy": None,
            "next_sell": None
        }

    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except:
        return {
            "base_price": None,
            "next_buy": None,
            "next_sell": None
        }


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
    data = private_get("/v2/fills", params={"page_size": 200})

    if data.get("success") is not True:
        raise Exception("Fills API failed: " + str(data))

    fills = data.get("result", [])

    for f in fills:
        if f.get("product_symbol") == SYMBOL and f.get("side") == "buy":
            return float(f.get("price"))

    return None


def place_market_order(side: str, size: float):
    payload = {
        "product_symbol": SYMBOL,
        "size": size,
        "side": side,
        "order_type": "market_order"
    }

    res = private_post("/v2/orders", payload)
    print("ORDER RESPONSE:", res)
    sys.stdout.flush()
    return res


# =========================
# GRID LEVEL SYSTEM
# =========================

def build_levels(base_price):
    base_price = float(base_price)
    return {
        "base_price": base_price,
        "next_buy": base_price - GRID,
        "next_sell": base_price + GRID
    }


# =========================
# STARTUP RECOVERY
# =========================

state = load_state()

base_price = state.get("base_price")
next_buy = state.get("next_buy")
next_sell = state.get("next_sell")

print("STATE LOADED:", state)
sys.stdout.flush()

try:
    price = get_live_price()
    pos_size = get_open_position_size()

    print("STARTUP LIVE PRICE:", price)
    print("STARTUP POS SIZE:", pos_size)
    sys.stdout.flush()

    if pos_size > 0:
        exchange_last_buy = get_last_buy_fill_price()
        print("EXCHANGE LAST BUY FILL:", exchange_last_buy)
        sys.stdout.flush()

        if exchange_last_buy is not None:
            levels = build_levels(exchange_last_buy)
            base_price = levels["base_price"]
            next_buy = levels["next_buy"]
            next_sell = levels["next_sell"]

            state["base_price"] = base_price
            state["next_buy"] = next_buy
            state["next_sell"] = next_sell
            save_state(state)

            print("RECOVERED LEVELS:", state)
            sys.stdout.flush()

    else:
        print("NO POSITION FOUND -> BOT WAITING FOR MANUAL BUY")
        state["base_price"] = None
        state["next_buy"] = None
        state["next_sell"] = None
        save_state(state)

except Exception as e:
    print("STARTUP ERROR:", str(e))
    traceback.print_exc()
    sys.stdout.flush()


# =========================
# MAIN LOOP
# =========================

while True:
    try:
        price = get_live_price()
        pos_size = get_open_position_size()

        print(f"LIVE PRICE: {price} | POS: {pos_size} | NEXT_BUY: {next_buy} | NEXT_SELL: {next_sell}")
        sys.stdout.flush()

        # if no position -> reset
        if pos_size <= 0:
            base_price = None
            next_buy = None
            next_sell = None
            state["base_price"] = None
            state["next_buy"] = None
            state["next_sell"] = None
            save_state(state)
            time.sleep(SLEEP_SECONDS)
            continue

        # if missing levels -> recover from exchange fill
        if base_price is None or next_buy is None or next_sell is None:
            exchange_last_buy = get_last_buy_fill_price()
            if exchange_last_buy is not None:
                levels = build_levels(exchange_last_buy)
                base_price = levels["base_price"]
                next_buy = levels["next_buy"]
                next_sell = levels["next_sell"]

                state["base_price"] = base_price
                state["next_buy"] = next_buy
                state["next_sell"] = next_sell
                save_state(state)

                print("LEVELS RECOVERED DURING RUN:", state)
                sys.stdout.flush()

            time.sleep(SLEEP_SECONDS)
            continue

        # =========================
        # GRID BUY
        # =========================
        if price <= next_buy:
            print("GRID BUY EXECUTING...")
            sys.stdout.flush()

            resp = place_market_order("buy", LOT_SIZE)

            if resp.get("success") is True:
                fill = get_last_buy_fill_price()
                if fill is None:
                    fill = price

                base_price = float(fill)
                next_buy = base_price - GRID
                next_sell = base_price + GRID

                state["base_price"] = base_price
                state["next_buy"] = next_buy
                state["next_sell"] = next_sell
                save_state(state)

                print("BUY DONE -> UPDATED LEVELS:", state)
                sys.stdout.flush()

        # =========================
        # GRID SELL (NO SHORT FIX)
        # =========================
        elif price >= next_sell:
            sell_size = min(float(LOT_SIZE), float(pos_size))  # ✅ SHORT PREVENT FIX

            if sell_size <= 0:
                print("SELL BLOCKED -> POSITION IS ZERO")
                sys.stdout.flush()
                time.sleep(SLEEP_SECONDS)
                continue

            print(f"GRID SELL EXECUTING... SELL_SIZE={sell_size} (POS={pos_size})")
            sys.stdout.flush()

            resp = place_market_order("sell", sell_size)

            if resp.get("success") is True:
                base_price = float(price)
                next_buy = base_price - GRID
                next_sell = base_price + GRID

                state["base_price"] = base_price
                state["next_buy"] = next_buy
                state["next_sell"] = next_sell
                save_state(state)

                print("SELL DONE -> UPDATED LEVELS:", state)
                sys.stdout.flush()

    except Exception as e:
        print("RUNTIME ERROR:", str(e))
        traceback.print_exc()
        sys.stdout.flush()

    time.sleep(SLEEP_SECONDS)
