import json
import time
from tradingview_ta import TA_Handler, Interval
import requests
from dotenv import load_dotenv
import os
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
import threading
import asyncio
from telegram.ext import ContextTypes

# Load environment variables
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHANNEL_ID = os.getenv('TELEGRAM_CHAT_ID')  
bot = Bot(token=TELEGRAM_BOT_TOKEN)

def custom_round(value):
    if value >= 1000:
        return round(value)
    elif value >= 100:
        return round(value, 2)
    elif value >= 10:
        return round(value, 3)
    elif value >= 1:
        return round(value, 3)
    elif value >= 0.1:
        return round(value, 5)
    else:
        return round(value, 6)

async def send_telegram_message(payload):
    try:
        message = await bot.send_message(**payload)
        return message.message_id
    except Exception as e:
        print(f"Error sending Telegram message: {e}")
        return None

def get_analysis_with_retry(handler, max_retries=3, delay=5):
    for attempt in range(max_retries):
        try:
            analysis = handler.get_analysis()
            print(f"Successfully retrieved analysis for {handler.symbol}")
            return analysis
        except Exception as e:
            if attempt < max_retries - 1:  # i.e. not on last attempt
                print(f"Attempt {attempt + 1} failed for {handler.symbol}: {str(e)}. Retrying in {delay} seconds...")
                time.sleep(delay)
            else:
                print(f"All {max_retries} attempts failed for {handler.symbol}: {str(e)}")
                raise e  # Re-raise the last exception if all retries fail

def debug_handler_response(handler):
    try:
        response = requests.post(
            "https://scanner.tradingview.com/crypto/scan",
            headers={
                "User-Agent": "tradingview-ta/3.3.0"
            },
            json={
                "symbols": {
                    "tickers": [f"{handler.exchange}:{handler.symbol}"],
                    "query": {
                        "types": []
                    }
                },
                "columns": ["name", "close", "EMA10", "EMA20", "EMA50", "EMA200", "RSI"]
            }
        )
        response.raise_for_status()
        data = response.json()
        print(f"API Response for {handler.symbol}:")
        print(json.dumps(data, indent=2))
        if not data['data']:
            print(f"No data returned for {handler.symbol}")
        elif data['data'][0]['s'] == "no_data":
            print(f"No data for {handler.symbol}")
        else:
            print(f"Data available for {handler.symbol}")
    except requests.RequestException as e:
        print(f"Request failed for {handler.symbol}: {str(e)}")
    except json.JSONDecodeError:
        print(f"Failed to decode JSON response for {handler.symbol}")

def save_to_active_json(coin_pair, direction, entry, stoploss, tps, message_id):
    try:
        with open('active.json', 'r+') as file:
            data = json.load(file)
            data[coin_pair] = {
                "direction": direction,
                "entry": entry,
                "stoploss": stoploss,
                "tps": tps,
                "message_id": message_id
            }
            file.seek(0)
            json.dump(data, file, indent=4)
            file.truncate()
    except Exception as e:
        print(f"Error saving to active.json: {e}")

async def check_position(coin_pair, close_price, indicators):
    # Load coin pairs
    with open('lists.json', 'r') as file:
        data = json.load(file)
        coin_pairs = data['coin_pairs']
    
    if coin_pair not in coin_pairs:
        return
    
    # Check if the coin_pair is already in active.json
    with open('active.json', 'r') as file:
        active_data = json.load(file)
        if coin_pair in active_data:
            print(f"{coin_pair} already in active.json, skipping.")
            return
    
    # Function to validate conditions across multiple timeframes
    def validate_multi_timeframe(symbol, direction):
        timeframes = [
            (Interval.INTERVAL_15_MINUTES, '15m'),
            (Interval.INTERVAL_30_MINUTES, '30m'),
            (Interval.INTERVAL_1_HOUR, '1h'),
            (Interval.INTERVAL_4_HOURS, '4h')
        ]
        
        for interval, timeframe_name in timeframes:
            handler = TA_Handler(
                symbol=symbol,
                screener="crypto",
                exchange="BYBIT",
                interval=interval
            )
            analysis = get_analysis_with_retry(handler)
            if direction == 'long':
                if not (analysis.indicators['close'] > analysis.indicators['EMA5'] > analysis.indicators['EMA200']):
                    print(f"{timeframe_name} validation failed for long")
                    return False
            else:  # short
                if not (analysis.indicators['close'] < analysis.indicators['EMA5'] < analysis.indicators['EMA200']):
                    print(f"{timeframe_name} validation failed for short")
                    return False
        return True

    # Existing 1m timeframe conditions for entry
    long_conditions = (close_price > indicators['EMA20'] and
                       indicators['RSI'] > 65 and 
                       (close_price - indicators['EMA200']) / close_price <= 0.017)
    
    short_conditions = (close_price < indicators['EMA20'] and
                        indicators['RSI'] < 35 and 
                        (indicators['EMA200'] - close_price) / indicators['EMA200'] <= 0.017)
    
    # Add multi-timeframe validation
    if long_conditions:
        if validate_multi_timeframe(coin_pair, 'long'):
            await handle_long_entry(coin_pair, close_price, indicators)
        else:
            print(f"Long entry for {coin_pair} failed multi-timeframe validation")
    elif short_conditions:
        if validate_multi_timeframe(coin_pair, 'short'):
            await handle_short_entry(coin_pair, close_price, indicators)
        else:
            print(f"Short entry for {coin_pair} failed multi-timeframe validation")

async def handle_long_entry(coin_pair, close_price, indicators):
    side = 'long'
    stoploss = custom_round(close_price * 0.98)
    risk = close_price - stoploss
    tp1 = custom_round(close_price + (risk * 1.68))
    tp2 = custom_round(close_price + (risk * 2.68))
    tp3 = custom_round(close_price + (risk * 3.68))
    
    trade_params = {
        "entry": close_price,
        "stop_loss": stoploss,
        "take_profits": {
            "TP1": tp1,
            "TP2": tp2,
            "TP3": tp3
        }
    }
    
    emoji = '🟢' if side == 'long' else '🔴'
    message = f'*{emoji} {side.title()} Entry for {coin_pair}*\n\n*Entry:* `{trade_params["entry"]}`\n*Stop Loss:* `{trade_params["stop_loss"]}`\n*Take Profits:*\n  - TP1: `{trade_params["take_profits"]["TP1"]}`\n  - TP2: `{trade_params["take_profits"]["TP2"]}`\n  - TP3: `{trade_params["take_profits"]["TP3"]}`'
    
    payload = {
        'chat_id': TELEGRAM_CHANNEL_ID,
        'text': message,
        'parse_mode': 'Markdown',
        'reply_markup': InlineKeyboardMarkup([
            [InlineKeyboardButton(text='View Chart on TradingView', url=f'https://www.tradingview.com/chart/?symbol=BYBIT%3A{coin_pair}&interval=5')]
        ])
    }
    
    message_id = await send_telegram_message(payload)
    if message_id:
        save_to_active_json(coin_pair, side, close_price, stoploss, [tp1, tp2, tp3], message_id)
    else:
        print(f"Failed to save entry for {coin_pair} due to Telegram message error.")

async def handle_short_entry(coin_pair, close_price, indicators):
    side = 'short'
    stoploss = custom_round(close_price * 1.02)
    risk = stoploss - close_price
    tp1 = custom_round(close_price - risk * 1.68)
    tp2 = custom_round(close_price - 2.68 * risk)
    tp3 = custom_round(close_price - 3.68 * risk)
    
    trade_params = {
        "entry": close_price,
        "stop_loss": stoploss,
        "take_profits": {
            "TP1": tp1,
            "TP2": tp2,
            "TP3": tp3
        }
    }
    
    emoji = '🟢' if side == 'long' else '🔴'
    message = f'*{emoji} {side.title()} Entry for {coin_pair}*\n\n*Entry:* `{trade_params["entry"]}`\n*Stop Loss:* `{trade_params["stop_loss"]}`\n*Take Profits:*\n  - TP1: `{trade_params["take_profits"]["TP1"]}`\n  - TP2: `{trade_params["take_profits"]["TP2"]}`\n  - TP3: `{trade_params["take_profits"]["TP3"]}`'
    
    payload = {
        'chat_id': TELEGRAM_CHANNEL_ID,
        'text': message,
        'parse_mode': 'Markdown',
        'reply_markup': InlineKeyboardMarkup([
            [InlineKeyboardButton(text='View Chart on TradingView', url=f'https://www.tradingview.com/chart/?symbol=BYBIT%3A{coin_pair}&interval=5')]
        ])
    }
    
    message_id = await send_telegram_message(payload)
    if message_id:
        save_to_active_json(coin_pair, side, close_price, stoploss, [tp1, tp2, tp3], message_id)
    else:
        print(f"Failed to save entry for {coin_pair} due to Telegram message error.")

async def monitor_positions():
    while True:
        try:
            with open('active.json', 'r') as file:
                active_positions = json.load(file)
            
            for coin_pair, position in active_positions.items():
                try:
                    handler = TA_Handler(
                        symbol=coin_pair,
                        screener="crypto",
                        exchange="BYBIT",
                        interval=Interval.INTERVAL_5_MINUTES
                    )
                    analysis = get_analysis_with_retry(handler)
                    current_price = analysis.indicators["close"]
                    
                    if position['direction'] == 'long':
                        if current_price >= position['tps'][0]:
                            await handle_tp1_long(coin_pair, position, current_price)
                        elif current_price <= position['stoploss']:
                            await handle_stoploss(coin_pair, position, current_price)
                    else:  # short
                        if current_price <= position['tps'][0]:
                            await handle_tp1_short(coin_pair, position, current_price)
                        elif current_price >= position['stoploss']:
                            await handle_stoploss(coin_pair, position, current_price)
                except Exception as e:
                    print(f"Error monitoring position for {coin_pair}: {e}")
                    debug_handler_response(handler)  # Debug the response when an error occurs
                
            await asyncio.sleep(300)  # Check every minute
        except Exception as e:
            print(f"General error in monitor_positions: {e}")

async def handle_tp1_long(coin_pair, position, current_price):
    profit = (current_price - position['entry']) / position['entry'] * 100
    message = f"💸 *{coin_pair} TP1 Hit!* ({profit:.2f}% from entry)\n\n" \
              f"*Entry:* `{position['entry']}`\n" \
              f"*TP1:* `{position['tps'][0]}`\n" \
              f"*Current Price:* `{current_price}`\n" \
              f"Consider moving *Stop Loss* to *Break Even* Point to minimize potential loss.\n\n" \
              f"*Next TP Targets:*\n" \
              f"  - *TP2:* `{position['tps'][1]}`\n" \
              f"  - *TP3:* `{position['tps'][2]}`"
    
    # Reply to the original message with Markdown formatting
    await bot.send_message(chat_id=TELEGRAM_CHANNEL_ID, text=message, parse_mode='Markdown', reply_to_message_id=position['message_id'])

    # Move to suspended.json
    move_to_suspended(coin_pair, position, position['message_id'])

async def handle_tp1_short(coin_pair, position, current_price):
    profit = (position['entry'] - current_price) / position['entry'] * 100
    message = f"💸 *{coin_pair} TP1 Hit!* ({profit:.2f}% from entry)\n\n" \
              f"*Entry:* `{position['entry']}`\n" \
              f"*TP1:* `{position['tps'][0]}`\n" \
              f"*Current Price:* `{current_price}`\n" \
              f"Consider moving *Stop Loss* to *Break Even* Point to minimize potential loss.\n\n" \
              f"*Next TP Targets:*\n" \
              f"  - *TP2:* `{position['tps'][1]}`\n" \
              f"  - *TP3:* `{position['tps'][2]}`"
    
    # Reply to the original message with Markdown formatting
    await bot.send_message(chat_id=TELEGRAM_CHANNEL_ID, text=message, parse_mode='Markdown', reply_to_message_id=position['message_id'])

    # Move to suspended.json
    move_to_suspended(coin_pair, position, position['message_id'])

async def handle_stoploss(coin_pair, position, current_price):
    message = f"🚨 *{coin_pair} Stop Loss Hit!* 🚨\n\n" \
              f"*Entry:* `{position['entry']}`\n" \
              f"*Stop Loss:* `{position['stoploss']}`\n" \
              f"*Current Price:* `{current_price}`"
    
    # Reply to the original message with Markdown formatting
    await bot.send_message(chat_id=TELEGRAM_CHANNEL_ID, text=message, parse_mode='Markdown', reply_to_message_id=position['message_id'])

    # Move directly to history.json since SL is final
    move_to_history(coin_pair, position, position['message_id'])

def move_to_suspended(coin_pair, position, message_id):
    try:
        with open('suspended.json', 'r+') as file:
            data = json.load(file)
            data[coin_pair] = position
            file.seek(0)
            json.dump(data, file, indent=4)
            file.truncate()
        
        with open('active.json', 'r+') as file:
            data = json.load(file)
            if coin_pair in data:
                del data[coin_pair]
            file.seek(0)
            json.dump(data, file, indent=4)
            file.truncate()
        
        # Suspend for 2 hours before moving to history
        asyncio.create_task(check_suspended(coin_pair))
    except Exception as e:
        print(f"Error moving {coin_pair} to suspended: {e}")

async def check_suspended(coin_pair):
    await asyncio.sleep(7200)  # 2 hours
    try:
        with open('suspended.json', 'r+') as file:
            data = json.load(file)
            if coin_pair in data:
                # Move to history.json after suspension
                move_to_history(coin_pair, data[coin_pair], data[coin_pair]['message_id'])
                del data[coin_pair]
                file.seek(0)
                json.dump(data, file, indent=4)
                file.truncate()
    except Exception as e:
        print(f"Error checking suspended for {coin_pair}: {e}")

def move_to_history(coin_pair, position, message_id):
    try:
        with open('history.json', 'r+') as file:
            data = json.load(file)
            
            # Determine if it was a win or lose based on whether TP1 or SL was hit
            handler = TA_Handler(
                symbol=coin_pair,
                screener="crypto",
                exchange="BYBIT",
                interval=Interval.INTERVAL_5_MINUTES
            )
            analysis = get_analysis_with_retry(handler)
            current_price = analysis.indicators["close"]
            
            if position['direction'] == 'long':
                if current_price <= position['stoploss']:
                    result = 'Lose'
                elif current_price >= position['tps'][0]:  # TP1 hit
                    result = 'Win'
                else:
                    result = 'Unknown'  # Fallback, though this should not happen
            else:  # short
                if current_price >= position['stoploss']:
                    result = 'Lose'
                elif current_price <= position['tps'][0]:  # TP1 hit
                    result = 'Win'
                else:
                    result = 'Unknown'  # Fallback, though this should not happen
            
            data.append({
                coin_pair: {
                    **position, 
                    "message_id": message_id,
                    "result": result  # 'Win' if TP1 was hit, 'Lose' if SL was hit
                }
            })
            file.seek(0)
            json.dump(data, file, indent=4)
            file.truncate()
        
        with open('active.json', 'r+') as file:
            data = json.load(file)
            if coin_pair in data:
                del data[coin_pair]
            file.seek(0)
            json.dump(data, file, indent=4)
            file.truncate()
    except Exception as e:
        print(f"Error moving {coin_pair} to history: {e}")

async def main_loop():
    while True:
        try:
            with open('lists.json', 'r') as file:
                data = json.load(file)
                for coin_pair in data['coin_pairs']:
                    try:
                        handler = TA_Handler(
                            symbol=coin_pair,
                            screener="crypto",
                            exchange="BYBIT",
                            interval=Interval.INTERVAL_1_MINUTE
                        )
                        analysis = get_analysis_with_retry(handler)
                        await check_position(coin_pair, analysis.indicators["close"], analysis.indicators)
                    except Exception as e:
                        print(f"Error checking position for {coin_pair}: {e}")
                        debug_handler_response(handler)  # Debug the response when an error occurs
        except Exception as e:
            print(f"General error in main loop: {e}")
        await asyncio.sleep(60)  # Check every minute

if __name__ == "__main__":
    # Initialize active, history, and suspended json files if they don't exist
    for filename in ['active.json', 'history.json', 'suspended.json']:
        if not os.path.exists(filename):
            with open(filename, 'w') as outfile:
                json.dump({} if filename != 'history.json' else [], outfile)
    
    # Start monitoring positions in a separate async task
async def run_all():
    monitor_task = asyncio.create_task(monitor_positions())
    await main_loop()
    await monitor_task  # This line ensures that monitor_positions task is awaited if main_loop ends

asyncio.run(run_all())
