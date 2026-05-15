import os
import sys
import time
import json
import hmac
import hashlib
import requests
import traceback
from datetime import datetime

# =========================
# CONFIG
# =========================

BASE_URL = "https://api.india.delta.exchange"
SYMBOL = "PAXGUSD"

GRID = float(os.getenv("GRID", "15"))
LOT_SIZE = float(os.getenv("LOT_SIZE", "1"))
SLEEP_SECONDS = int(os.getenv("SLEEP_SECONDS", "5"))

API_KEY = os.getenv("DELTA_API_KEY")
API_SECRET = os.getenv("DELTA_API_SECRET")

STATE_FILE = "state.json"
LOCK_FILE = "bot.lock"

USER_AGENT = "gold-grid-bot-ultra-stable-v2"

print("BOT FILE RUNNING...")
sys.stdout.flush()

print("BOT STARTED...")
print("SYMBOL:", SYMBOL)
print("GRID:", GRID)
print("LOT_SIZE:", LOT_SIZE)
print("SLEEP_SECONDS:", SLEEP_SECONDS)
sys.stdout.flush()

if not API_KEY or not API_SECRET:
    raise Exception("DELTA_API_KEY / DELTA_API_SECRET missing!")

# =========================
# LOCK SYSTEM
# =========================

def acquire_lock():
    if os.path.exists(LOCK_FILE):
        print("LOCK FILE EXISTS -> BOT ALREADY RUNNING. EXITING.")
        sys.stdout.flush()
        sys.exit(0)

    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))

    print("LOCK ACQUIRED.")
    sys.stdout.flush()


def release_lock():
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    except:
        pass


acquire_lock()

# =========================
# STATE SYSTEM
# =========================

def default_state():
    return {
        "base_price": None,
        "next_buy": None,
        "next_sell": None,
        "last_action": None,
        "last_action_price": None,
        "last_order_id": None,
        "last_fill_id": None,          # NEW: track exchange fill id
        "last_fill_price": None,
        "last_fill_side": None
    }


def load_state():
    if not os.path.exists(STATE_FILE):
        return default_state()

    try:
        with open(STATE_FILE, "r") as f:
            data = json.load(f)

        d = default_state()
        d.update(data)
        return d
    except:
        return default_state()


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


state = load_state()

# =========================
# SIGNATURE HELPERS
# =========================

def generate_signature(message: str) -> str:
    return hmac.new(
        API_SECRET.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()


def safe_json_response(r):
    try:
        return r.json()
    except:
        return None


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

    r = requests.get(url, headers=headers, timeout=20)
    data = safe_json_response(r)

    if data is None:
        raise Exception("PRIVATE GET JSON ERROR: " + r.text)

    return data


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

    r = requests.post(url, headers=headers, data=body, timeout=20)
    data = safe_json_response(r)

    if data is None:
        raise Exception("PRIVATE POST JSON ERROR: " + r.text)

    return data


# =========================
# EXCHANGE HELPERS
# =========================

def get_live_price():
    url = f"{BASE_URL}/v2/tickers/{SYMBOL}"
    r = requests.get(url, timeout=10)
    data = safe_json_response(r)

    if data is None:
        raise Exception("Ticker JSON error: " + r.text)

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


def get_last_fill():
    data = private_get("/v2/fills", params={"page_size": 50})

    if data.get("success") is not True:
        raise Exception("Fills API failed: " + str(data))

    fills = data.get("result", [])

    for f in fills:
        if f.get("product_symbol") == SYMBOL:
            return f

    return None


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
# GRID LEVELS
# =========================

def build_levels(base_price):
    base_price = float(base_price)
    return {
        "base_price": base_price,
        "next_buy": base_price - GRID,
        "next_sell": base_price + GRID
    }


def update_levels_from_base(base_price):
    levels = build_levels(base_price)
    state["base_price"] = levels["base_price"]
    state["next_buy"] = levels["next_buy"]
    state["next_sell"] = levels["next_sell"]
    save_state(state)


# =========================
# DUPLICATE ACTION GUARD
# =========================

def already_executed_same_price(action, price):
    if state.get("last_action") == action and state.get("last_action_price") is not None:
        if abs(float(state["last_action_price"]) - float(price)) < 0.01:
            return True
    return False


def mark_action(action, price, order_id=None):
    state["last_action"] = action
    state["last_action_price"] = float(price)
    state["last_order_id"] = order_id
    save_state(state)


# =========================
# MANUAL TRADE SYNC (FIX)
# =========================

def sync_with_exchange_fills():
    """
    If manual trade happened, bot will auto update base_price/levels.
    """
    last_fill = get_last_fill()
    if last_fill is None:
        return

    fill_id = last_fill.get("id")
    fill_price = float(last_fill.get("price"))
    fill_side = last_fill.get("side")

    if fill_id is None:
        return

    # If new fill detected
    if state.get("last_fill_id") != fill_id:
        print("NEW EXCHANGE FILL DETECTED -> SYNCING GRID LEVELS...")
        print("FILL SIDE:", fill_side, "PRICE:", fill_price, "ID:", fill_id)
        sys.stdout.flush()

        # update grid base on last fill price
        update_levels_from_base(fill_price)

        state["last_fill_id"] = fill_id
        state["last_fill_price"] = fill_price
        state["last_fill_side"] = fill_side
        save_state(state)

        # reset duplicate action memory (important)
        state["last_action"] = None
        state["last_action_price"] = None
        save_state(state)

        print("GRID LEVELS UPDATED FROM EXCHANGE FILL:", state)
        sys.stdout.flush()


# =========================
# STARTUP RECOVERY
# =========================

print("STATE LOADED:", state)
sys.stdout.flush()

try:
    price = get_live_price()
    pos_size = get_open_position_size()

    print("STARTUP LIVE PRICE:", price)
    print("STARTUP POS SIZE:", pos_size)
    sys.stdout.flush()

    if pos_size > 0 and (state["base_price"] is None or state["next_buy"] is None or state["next_sell"] is None):
        exchange_last_buy = get_last_buy_fill_price()
        print("EXCHANGE LAST BUY FILL:", exchange_last_buy)
        sys.stdout.flush()

        if exchange_last_buy is not None:
            update_levels_from_base(exchange_last_buy)
            print("RECOVERED LEVELS FROM EXCHANGE:", state)
            sys.stdout.flush()

    if pos_size <= 0:
        state = default_state()
        save_state(state)
        print("NO POSITION FOUND -> STATE RESET")
        sys.stdout.flush()

except Exception as e:
    print("STARTUP ERROR:", str(e))
    traceback.print_exc()
    sys.stdout.flush()


# =========================
# MAIN LOOP
# =========================

try:
    while True:
        try:
            LOT_SIZE = float(os.getenv("LOT_SIZE", "1"))

            # Sync manual fills every loop
            sync_with_exchange_fills()

            price = get_live_price()
            pos_size = get_open_position_size()

            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            print(f"{now} LIVE PRICE: {price} | POS: {pos_size} | NEXT_BUY: {state.get('next_buy')} | NEXT_SELL: {state.get('next_sell')} | LOT_SIZE: {LOT_SIZE}")
            sys.stdout.flush()

            if pos_size <= 0:
                state = default_state()
                save_state(state)
                time.sleep(SLEEP_SECONDS)
                continue

            if state["base_price"] is None or state["next_buy"] is None or state["next_sell"] is None:
                exchange_last_buy = get_last_buy_fill_price()
                if exchange_last_buy is not None:
                    update_levels_from_base(exchange_last_buy)
                    print("LEVELS RECOVERED DURING RUN:", state)
                    sys.stdout.flush()
                time.sleep(SLEEP_SECONDS)
                continue

            next_buy = float(state["next_buy"])
            next_sell = float(state["next_sell"])

            # =========================
            # GRID BUY
            # =========================
            if price <= next_buy:

                if already_executed_same_price("buy", next_buy):
                    print("SKIPPING DUPLICATE BUY AT SAME GRID LEVEL.")
                    sys.stdout.flush()
                    time.sleep(SLEEP_SECONDS)
                    continue

                print("GRID BUY TRIGGERED...")
                sys.stdout.flush()

                resp = place_market_order("buy", LOT_SIZE)

                if resp.get("success") is True:
                    order_id = resp.get("result", {}).get("id")

                    time.sleep(1)
                    fill = get_last_buy_fill_price()
                    if fill is None:
                        fill = price

                    update_levels_from_base(fill)
                    mark_action("buy", next_buy, order_id)

                    print("BUY CONFIRMED -> UPDATED LEVELS:", state)
                    sys.stdout.flush()

            # =========================
            # GRID SELL
            # =========================
            elif price >= next_sell:

                if already_executed_same_price("sell", next_sell):
                    print("SKIPPING DUPLICATE SELL AT SAME GRID LEVEL.")
                    sys.stdout.flush()
                    time.sleep(SLEEP_SECONDS)
                    continue

                sell_size = min(LOT_SIZE, pos_size)

                if sell_size <= 0:
                    print("SELL BLOCKED -> POSITION 0 (NO SHORT ALLOWED).")
                    sys.stdout.flush()
                    time.sleep(SLEEP_SECONDS)
                    continue

                print("GRID SELL TRIGGERED... SELL_SIZE:", sell_size)
                sys.stdout.flush()

                resp = place_market_order("sell", sell_size)

                if resp.get("success") is True:
                    order_id = resp.get("result", {}).get("id")

                    update_levels_from_base(price)
                    mark_action("sell", next_sell, order_id)

                    print("SELL CONFIRMED -> UPDATED LEVELS:", state)
                    sys.stdout.flush()

        except Exception as e:
            print("RUNTIME ERROR:", str(e))
            traceback.print_exc()
            sys.stdout.flush()

        time.sleep(SLEEP_SECONDS)

except KeyboardInterrupt:
    print("BOT STOPPED MANUALLY.")
    sys.stdout.flush()

finally:
    release_lock()
