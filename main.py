from flask import Flask, request
import json

app = Flask(__name__)

GRID = 33

orders = []

@app.route("/")
def home():
    return "BOT RUNNING"

@app.route("/webhook", methods=["POST"])
def webhook():
    global orders

    data = request.json

    action = data.get("action")
    price = float(data.get("price"))
    lot = float(data.get("lot"))

    if action == "BUY":
        orders.append({
            "entry": price,
            "lot": lot
        })

        print(f"BUY at {price}")

    if len(orders) > 0:
        last_order = orders[-1]

        if price >= last_order["entry"] + GRID:
            closed = orders.pop()

            print(f"SELL at {price}")

    if len(orders) == 0:
        orders.append({
            "entry": price,
            "lot": lot
        })

        print(f"REBUY at {price}")

    return {"status": "success"}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
