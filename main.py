from flask import Flask, request

app = Flask(__name__)

GRID = 33
LOT = 1

positions = []

last_price = None


@app.route("/")
def home():
    return "GRID BOT ACTIVE"


@app.route("/webhook", methods=["POST"])
def webhook():
    global last_price, positions

    data = request.json
    price = float(data.get("price"))

    # first time setup
    if last_price is None:
        last_price = price
        positions.append(price)
        return {"status": "first buy"}

    # BUY condition (down move)
    if price <= last_price - GRID:
        positions.append(price)
        last_price = price
        print("BUY at", price)

    # SELL condition (up move from last buy)
    if len(positions) > 0:
        last_buy = positions[-1]

        if price >= last_buy + GRID:
            positions.pop()
            print("SELL at", price)

    # restart condition
    if len(positions) == 0:
        positions.append(price)
        last_price = price
        print("RESTART BUY at", price)

    return {"status": "ok", "positions": len(positions)}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
