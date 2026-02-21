# get_btc.py
import requests
import json
from datetime import datetime, timedelta, timezone
import io
from contextlib import redirect_stdout

# Base API URLs
MARKET_API_BASE = "https://gamma-api.polymarket.com/markets/slug/"
PRICE_API_BASE = "https://clob.polymarket.com/price"

def get_current_15m_unix():
    now = datetime.now(timezone.utc)
    minutes_past_hour = now.minute
    quarter_offset = minutes_past_hour % 15
    if quarter_offset == 0:
        start = now.replace(second=0, microsecond=0)
    else:
        start = now.replace(minute=(minutes_past_hour // 15) * 15, second=0, microsecond=0)
    return int(start.timestamp())

def fetch_market(slug):
    try:
        response = requests.get(f"{MARKET_API_BASE}{slug}")
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        if response.status_code == 404:
            return None
        raise e

def get_token_price(token_id, side="buy"):
    try:
        response = requests.get(f"{PRICE_API_BASE}?token_id={token_id}&side={side.upper()}")
        response.raise_for_status()
        data = response.json()
        return float(data.get("price", 0.0))
    except Exception:
        return 0.0

def get_btc_prediction_text():
    """Returns HTML-formatted string for Telegram (parse_mode='HTML')"""
    output = io.StringIO()
    with redirect_stdout(output):
        unix = get_current_15m_unix()
        attempts = 0
        market = None
        
        while attempts < 3:
            slug = f"btc-updown-15m-{unix}"
            market = fetch_market(slug)
            if market:
                break
            next_start = datetime.fromtimestamp(unix, tz=timezone.utc) + timedelta(minutes=15)
            unix = int(next_start.timestamp())
            attempts += 1
        
        if not market:
            print("No active 15-min BTC up/down market found right now.\n\nTry again in a few minutes.")
            return output.getvalue().strip()
        
        question = market.get("question", "Unknown")
        end_date_str = market.get("endDate", "N/A")
        
        clob_ids = []
        if "clobTokenIds" in market:
            try:
                clob_ids = json.loads(market["clobTokenIds"])
            except Exception:
                pass
        
        if len(clob_ids) < 2:
            print("Invalid market data.")
            return output.getvalue().strip()
        
        yes_token = clob_ids[0]
        no_token  = clob_ids[1]
        
        up_price   = get_token_price(yes_token, "buy")
        down_price = get_token_price(no_token, "buy")
        
        if up_price == 0.0 and "outcomePrices" in market:
            try:
                prices = json.loads(market["outcomePrices"])
                if len(prices) >= 2:
                    up_price   = float(prices[0])
                    down_price = float(prices[1])
            except:
                pass
        
        market_url = f"https://polymarket.com/event/{market.get('slug', slug)}"
        
        # HTML output - no escaping needed for dashes, dots, colons, etc.
        print("\n\nCurrent BTC 15-min Market\n")
        print(f"Question: {question}\n")
        print(f"Ends: {end_date_str}\n")
        print(f'{market_url}\n')
        print(f"Up (YES): \n{up_price:.2%}\n")
        print(f"Down (NO): \n{down_price:.2%}\n")
        
        if up_price > down_price:
            print("Prediction: BTC will go UP🚀")
        elif down_price > up_price:
            print("Prediction: BTC will go DOWN 📉")
        else:
            print("Prediction: Neutral (50/50) ⚖️")
    
    return output.getvalue().strip()