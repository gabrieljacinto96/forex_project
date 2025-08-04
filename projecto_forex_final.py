import MetaTrader5 as mt5
import time
import logging
import pandas as pd
import argparse
import threading


ACCOUNT = 1009160           # your trading account number
PASSWORD = "I9tqhwal_"   # your account password
SERVER = "JFD-DEMO"     # your broker's server name

if not mt5.initialize(login=ACCOUNT, password=PASSWORD, server=SERVER):
    logging.error("MetaTrader5 initialization failed. Error: %s", mt5.last_error())
    exit(1)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class ForexTradingBot:
    def __init__(self, symbol, lot_size):
        self.symbol = symbol
        self.lot_size = lot_size

    def get_macd(self):
        rates = mt5.copy_rates_from_pos(self.symbol, mt5.TIMEFRAME_M1, 0, 100)
        if rates is None:
            logging.error(f"Failed to get rates for {self.symbol}. Error: {mt5.last_error()}")
            return None
        df = pd.DataFrame(rates)
        df['ema12'] = df['close'].ewm(span=12, adjust=False).mean()
        df['ema26'] = df['close'].ewm(span=26, adjust=False).mean()
        df['macd'] = df['ema12'] - df['ema26']
        df['signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        return df[['macd', 'signal']].iloc[-1]

    def place_order(self, action):
        symbol_info = mt5.symbol_info(self.symbol)
        if symbol_info is None:
            logging.error(f"Symbol {self.symbol} not found.")
            return

        point = symbol_info.point
        price = mt5.symbol_info_tick(self.symbol).ask if action == 'buy' else mt5.symbol_info_tick(self.symbol).bid
        sl = price - 100 * point if action == 'buy' else price + 100 * point
        tp = price + 100 * point if action == 'buy' else price - 100 * point

        order_type = 0 if action == 'buy' else 1 # 0 for buy, 1 for sell
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.symbol,
            "volume": self.lot_size,
            "type": order_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": 10,
            "magic": 234000,
            "comment": f"{action} order",
            "type_time": mt5.ORDER_TIME_GTC,
        }
    
    def run(self):
        logging.info(f"Starting trading bot for {self.symbol} with lot size {self.lot_size}")
        last_macd = None
        last_signal = None
        cooldown = 60 # seconds cooldown to avoid rapid trading
        while True:
            macd_data = self.get_macd()
            if macd_data is not None:
                logging.info(f"MACD: {macd_data['macd']}, Signal: {macd_data['signal']}")
                if last_macd is not None and last_signal is not None:
                    # MACD crosses below Signal -> SELL
                    if last_macd > last_signal and macd_data['macd'] < macd_data['signal']:
                        logging.info("MACD crossed below Signal. Placing SELL order.")
                        self.place_order("sell")
                        time.sleep(cooldown)
                    # MACD crosses above Signal -> BUY
                    elif last_macd < last_signal and macd_data['macd'] > macd_data['signal']:
                        logging.info("MACD crossed above Signal. Placing BUY order.")
                        self.place_order("buy")
                        time.sleep(cooldown)
                last_macd = macd_data['macd']
                last_signal = macd_data['signal']
            time.sleep(10)

def main():
    parser = argparse.ArgumentParser(description='Forex Trading Bot')
    parser.add_argument('--lot_size', type=float, default=0.1, help='Lot size for trades')
    args = parser.parse_args()

    symbols = ["EURUSD", "USDJPY"]

    bots = [ForexTradingBot(symbol=s, lot_size=args.lot_size) for s in symbols]
    threads = []
    for bot in bots:
        t = threading.Thread(target=bot.run)
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

if __name__ == "__main__":
    main()
    mt5.shutdown()