import MetaTrader5 as mt5
import time
import logging
import pandas as pd
import argparse
import threading

mt5.initialize(path="C:\\Program Files\\MetaTrader 5\\terminal64.exe")

account=1009160
authorized=mt5.login(account, password="I9tqhwal_", server="JFD-DEMO")
if authorized:
    
    print(mt5.account_info())
    
    print("Show account_info()._asdict():")
    account_info_dict = mt5.account_info()._asdict()
    for prop in account_info_dict:
        print("  {}={}".format(prop, account_info_dict[prop]))
else:
    print("failed to connect at account #{}, error code: {}".format(account, mt5.last_error()))

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

    def order_send(self, action):
        symbol_info = mt5.symbol_info(self.symbol)
        if symbol_info is None:
            logging.error(f"Symbol {self.symbol} not found.")
            return

        point = symbol_info.point
        price = mt5.symbol_info_tick(self.symbol).ask if action == 'buy' else mt5.symbol_info_tick(self.symbol).bid
        sl = price - 100 * point if action == 'buy' else price + 100 * point
        tp = price + 100 * point if action == 'buy' else price - 100 * point

        order_send = 0 if action == 'buy' else 1 # 0 para comprar, 1 para vender
        if action == 'buy':
            logging.info(f"Placing BUY order for {self.symbol} at price {price}")
        else:
            logging.info(f"Placing SELL order for {self.symbol} at price {price}")
            
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.symbol,
            "volume": self.lot_size,
            "type": mt5.ORDER_TYPE_BUY if action == 'buy' else mt5.ORDER_TYPE_SELL,
            "type_filling": mt5.ORDER_FILLING_IOC,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": 10,
            "magic": 234000,
            "comment": f"{action} order",
        }
    
        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logging.error(f"Order failed: {result.retcode}, {result}")
        else:
            logging.info(f"Order placed successfully: {result}")
            
    def run(self):
        logging.info(f"Starting trading bot for {self.symbol} with lot size {self.lot_size}")
        last_macd = None
        last_signal = None
        cooldown = 60 # segundos de cooldown entre ordens
        while True:
            macd_data = self.get_macd()
            if macd_data is not None:
                logging.info(f"MACD: {macd_data['macd']}, Signal: {macd_data['signal']}")
                if last_macd is not None and last_signal is not None:
                    # MACD cruza abaixo da linha se sinal -> VENDER
                    if last_macd > last_signal and macd_data['macd'] < macd_data['signal']:
                        logging.info("MACD crossed below Signal. Placing SELL order.")
                        self.order_send("sell")
                        time.sleep(cooldown)
                    # MACD cruza acima da linha de sinal -> COMPRAR
                    elif last_macd < last_signal and macd_data['macd'] > macd_data['signal']:
                        logging.info("MACD crossed above Signal. Placing BUY order.")
                        self.order_send("buy")
                        time.sleep(cooldown)
                last_macd = macd_data['macd']
                last_signal = macd_data['signal']
            time.sleep(10)

def main():
    parser = argparse.ArgumentParser(description='Forex Trading Bot')
    parser.add_argument('--lot_size', type=float, default=0.2, help='Lot size for trades')
    args = parser.parse_args()

    symbols = ["EURUSD", "USDJPY"]

    bots = [ForexTradingBot(symbol=s, lot_size = args.lot_size) for s in symbols]
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