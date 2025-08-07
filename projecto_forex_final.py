import MetaTrader5 as mt5
import time
import logging
import pandas as pd
import argparse
import threading
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import os 

mt5.initialize(path="C:\\Program Files\\MetaTrader 5\\terminal64.exe")


account = 1009160
authorized = mt5.login(account, password="I9tqhwal_", server="JFD-DEMO")
if authorized:
    print("Connected to MT5")
else:
    print(f"Failed to connect: {mt5.last_error()}")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class HedgingManager:
    def __init__(self, symbol, max_hedge_ratio=2.0):
        self.symbol = symbol
        self.max_hedge_ratio = max_hedge_ratio
        self.open_positions = {}
        self.hedge_positions = {}
        
    def get_open_positions(self):
        """Get all open positions for this symbol"""
        positions = mt5.positions_get(symbol=self.symbol)
        if positions is None:
            return []
        return list(positions)
    
    def calculate_net_exposure(self):
        """Calculate net exposure (buy volume - sell volume)"""
        positions = self.get_open_positions()
        buy_volume = sum(pos.volume for pos in positions if pos.type == mt5.ORDER_TYPE_BUY)
        sell_volume = sum(pos.volume for pos in positions if pos.type == mt5.ORDER_TYPE_SELL)
        return buy_volume - sell_volume
    
    def should_hedge(self, new_order_type, new_volume):
        """Determine if hedging is needed"""
        net_exposure = self.calculate_net_exposure()
        
        # ADICIONA O VOLUME DA NOVA ORDEM À EXPOSIÇÃO ATUAL
        if new_order_type == "buy":
            potential_exposure = net_exposure + new_volume
        else:
            potential_exposure = net_exposure - new_volume
            
        # CERTIFICA SE A EXPOSIÇÃO POTENCIAL EXCEDE O LIMITE DE HEDGE
        max_allowed_exposure = new_volume * self.max_hedge_ratio
        return abs(potential_exposure) > max_allowed_exposure
    
    def create_hedge_order(self, original_order_type, volume):
        """Create hedge order opposite to the original"""
        hedge_type = "sell" if original_order_type == "buy" else "buy"
        hedge_volume = volume * 0.5  # DEFINE O VOLUME DE HEDGE COMO 50% DO VOLUME ORIGINAL
        
        return {
            "type": hedge_type,
            "volume": hedge_volume,
            "reason": f"Hedge for {original_order_type} order"
        }

class ForexTradingBot:
    def __init__(self, symbol, lot_size):
        self.symbol = symbol
        self.lot_size = lot_size
        self.min_history = 50
        self.divergence_lookback = 50
        self.chart_enabled = False
        self.divergence_detected = None
        self.divergence_timestamp = 0
        self.hedging_manager = HedgingManager(symbol)  # ADICIONA GERENCIADOR DE HEDGING
        self.hedging_enabled = True  # ATIVA OU DESTIVA O HEDGING

    def get_macd(self, periods=250):
        rates = mt5.copy_rates_from_pos(self.symbol, mt5.TIMEFRAME_M1, 0, periods)
        if rates is None:
            return None
        
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        df['ema12'] = df['close'].ewm(span=12, adjust=False).mean()
        df['ema26'] = df['close'].ewm(span=26, adjust=False).mean()
        df['macd'] = df['ema12'] - df['ema26']
        df['signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        df['histogram'] = df['macd'] - df['signal']
        return df[['time', 'close', 'macd', 'signal', 'histogram']]

    def find_peaks_troughs(self, data, lookback=5):
        peaks = []
        troughs = []
        
        for i in range(lookback, len(data) - lookback):
            is_peak = all(data.iloc[i] > data.iloc[i-j] for j in range(1, lookback+1)) and \
                     all(data.iloc[i] > data.iloc[i+j] for j in range(1, lookback+1))
            
            is_trough = all(data.iloc[i] < data.iloc[i-j] for j in range(1, lookback+1)) and \
                       all(data.iloc[i] < data.iloc[i+j] for j in range(1, lookback+1))
            
            if is_peak:
                peaks.append((i, data.iloc[i]))
            elif is_trough:
                troughs.append((i, data.iloc[i]))
                
        return peaks, troughs

    def detect_bullish_divergence(self, df):
        if len(df) < self.divergence_lookback:
            return False
            
        analysis_df = df.tail(self.divergence_lookback)
        price_peaks, price_troughs = self.find_peaks_troughs(analysis_df['close'], lookback=3)
        macd_peaks, macd_troughs = self.find_peaks_troughs(analysis_df['macd'], lookback=3)
        
        if len(price_troughs) < 2 or len(macd_troughs) < 2:
            return False
            
        for i in range(len(price_troughs)-1):
            for j in range(len(macd_troughs)-1):
                if i < len(price_troughs)-1 and j < len(macd_troughs)-1:
                    price_trough1 = price_troughs[i]
                    price_trough2 = price_troughs[i+1]
                    macd_trough1 = macd_troughs[j]
                    macd_trough2 = macd_troughs[j+1]
                    
                    price_lower_low = price_trough2[1] < price_trough1[1]
                    macd_higher_low = macd_trough2[1] > macd_trough1[1]
                    
                    if price_lower_low and macd_higher_low:
                        return True
        return False

    def detect_bearish_divergence(self, df):
        if len(df) < self.divergence_lookback:
            return False
            
        analysis_df = df.tail(self.divergence_lookback)
        price_peaks, price_troughs = self.find_peaks_troughs(analysis_df['close'], lookback=3)
        macd_peaks, macd_troughs = self.find_peaks_troughs(analysis_df['macd'], lookback=3)
        
        if len(price_peaks) < 2 or len(macd_peaks) < 2:
            return False
            
        for i in range(len(price_peaks)-1):
            for j in range(len(macd_peaks)-1):
                if i < len(price_peaks)-1 and j < len(macd_peaks)-1:
                    price_peak1 = price_peaks[i]
                    price_peak2 = price_peaks[i+1]
                    macd_peak1 = macd_peaks[j]
                    macd_peak2 = macd_peaks[j+1]
                    
                    price_higher_high = price_peak2[1] > price_peak1[1]
                    macd_lower_high = macd_peak2[1] < macd_peak1[1]
                    
                    if price_higher_high and macd_lower_high:
                        return True
        return False

    def detect_macd_convergence(self, df):
        if len(df) < 50:
            return None
            
        macd_values = df['macd'].tail(50)
        signal_values = df['signal'].tail(50)
        diff = abs(macd_values - signal_values)
        
        recent_diff = diff.tail(10).mean()
        older_diff = diff.head(10).mean()
        
        if recent_diff < older_diff * 0.5:
            current_histogram = df['histogram'].iloc[-1]
            if current_histogram > 0:
                return "convergence_from_above"
            else:
                return "convergence_from_below"
        return None

    def order_send_with_hedging(self, action, reason=""):
        """Enhanced order sending with hedging logic"""
        
        # VERIFICA SE HEDGING ESTÁ ATIVADO E SE É NECESSÁRIO ANTES DE COLOCAR A ORDEM
        if self.hedging_enabled and self.hedging_manager.should_hedge(action, self.lot_size):
            logging.info(f"🛡️ Hedging required for {self.symbol} - {action} order")
            
            # CRIA ORDEM DE HEDGE
            hedge_order = self.hedging_manager.create_hedge_order(action, self.lot_size)
            
            # COLOCA A ORDEM DE HEDGE
            hedge_success = self.order_send(hedge_order["type"], hedge_order["reason"])
            if hedge_success:
                logging.info(f"🛡️ Hedge order placed: {hedge_order['type']} {hedge_order['volume']} {self.symbol}")
        
        # COLOCA A ORDEM PRINCIPAL
        return self.order_send(action, reason)

    def order_send(self, action, reason=""):
        mt5.symbol_select(self.symbol, True)
        
        tick = mt5.symbol_info_tick(self.symbol)
        if tick is None:
            return False
            
        symbol_info = mt5.symbol_info(self.symbol)
        if symbol_info is None:
            return False
        
        # DEFINE VALORES DE PREÇO, STOP LOSS E TAKE PROFIT    
        price = tick.ask if action == 'buy' else tick.bid
        point = symbol_info.point
        sl = price - 100 * point if action == 'buy' else price + 100 * point
        tp = price + 100 * point if action == 'buy' else price - 100 * point

        comment = "BOT_TRADE"

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.symbol,
            "volume": self.lot_size,
            "type": mt5.ORDER_TYPE_BUY if action == 'buy' else mt5.ORDER_TYPE_SELL,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": 20,
            "magic": 234000,
            "comment": comment,  
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        
        if result is None:
            logging.error(f"Order failed: {mt5.last_error()}")
            return False
            
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logging.error(f"Order failed: {result.retcode} - {result.comment}")
            return False
        else:
            logging.info(f"Order successful: {action} {self.symbol} - {reason}")
            return True

    def save_divergence_chart(self, df, divergence_type, reason):
        """Save chart when divergence is detected"""
        if not self.chart_enabled:
            return
            
        try:
            # CRIA DIRETÓRIO PARA GRÁFICOS SE NÃO EXISTIR
            chart_dir = "charts"
            if not os.path.exists(chart_dir):
                os.makedirs(chart_dir)
            
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(15, 8), sharex=True)

            # TÍTULO DO GRÁFICO DE PREÇO
            ax1.plot(df['time'], df['close'], 'b-', linewidth=1, label='Price')
            
            # ENCONTRA PONTOS DE MÁXIMOS E MÍNIMOS NO PREÇO E MACD
            analysis_df = df.tail(200)  # DEFINE A QUANTIDADE DE VELAS PARA ANÁLISE
            price_peaks, price_troughs = self.find_peaks_troughs(analysis_df['close'])
            macd_peaks, macd_troughs = self.find_peaks_troughs(analysis_df['macd'])
            
            # MARKA TRENDLINES NO PREÇO
            if price_peaks:
                peak_times = [analysis_df['time'].iloc[p[0]] for p in price_peaks]
                peak_values = [p[1] for p in price_peaks]
                ax1.scatter(peak_times, peak_values, color='red', s=30, marker='^')
                
                # DESENHA LINHA DE TENDÊNCIA CONECTANDO OS ÚLTIMOS DOIS VALORES MAXIMOS
                if len(price_peaks) >= 2:
                    last_two = price_peaks[-2:]
                    x_coords = [analysis_df['time'].iloc[p[0]] for p in last_two]
                    y_coords = [p[1] for p in last_two]
                    ax1.plot(x_coords, y_coords, 'r--', linewidth=2, alpha=0.8)
                    
            if price_troughs:
                trough_times = [analysis_df['time'].iloc[t[0]] for t in price_troughs]
                trough_values = [t[1] for t in price_troughs]
                ax1.scatter(trough_times, trough_values, color='green', s=30, marker='v')
                
                # DESENHA LINHA DE TENDÊNCIA CONECTANDO OS ÚLTIMOS DOIS VALORES MINIMOS
                if len(price_troughs) >= 2:
                    last_two = price_troughs[-2:]
                    x_coords = [analysis_df['time'].iloc[t[0]] for t in last_two]
                    y_coords = [t[1] for t in last_two]
                    ax1.plot(x_coords, y_coords, 'g--', linewidth=2, alpha=0.8)
            
            ax1.set_ylabel('Price')
            ax1.set_title(f'{self.symbol} - {reason} - {df["time"].iloc[-1].strftime("%Y-%m-%d %H:%M")}')
            ax1.grid(True, alpha=0.3)
            
            # ANOTAÇÃO DE DIVERGENCIA
            color = 'green' if divergence_type == 'bullish' else 'red'
            ax1.annotate(f'{reason}', xy=(df['time'].iloc[-1], df['close'].iloc[-1]), 
                        xytext=(10, 10), textcoords='offset points',
                        bbox=dict(boxstyle='round,pad=0.3', fc=color, alpha=0.7),
                        arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0'))
            
            # GRAFICO MACD COM TRENDLINES
            ax2.plot(df['time'], df['macd'], 'b-', linewidth=1, label='MACD')
            ax2.plot(df['time'], df['signal'], 'orange', linewidth=1, label='Signal')
            ax2.bar(df['time'], df['histogram'], alpha=0.3, color='gray', label='Histogram')
            ax2.axhline(y=0, color='black', linestyle='-', alpha=0.3)
            
            # MARCA TRENDLINES NO MACD
            if macd_peaks:
                peak_times = [analysis_df['time'].iloc[p[0]] for p in macd_peaks]
                peak_values = [p[1] for p in macd_peaks]
                ax2.scatter(peak_times, peak_values, color='red', s=30, marker='^')
                
                if len(macd_peaks) >= 2:
                    last_two = macd_peaks[-2:]
                    x_coords = [analysis_df['time'].iloc[p[0]] for p in last_two]
                    y_coords = [p[1] for p in last_two]
                    ax2.plot(x_coords, y_coords, 'r--', linewidth=2, alpha=0.8)
                    
            if macd_troughs:
                trough_times = [analysis_df['time'].iloc[t[0]] for t in macd_troughs]
                trough_values = [t[1] for t in macd_troughs]
                ax2.scatter(trough_times, trough_values, color='green', s=30, marker='v')
                
                if len(macd_troughs) >= 2:
                    last_two = macd_troughs[-2:]
                    x_coords = [analysis_df['time'].iloc[t[0]] for t in last_two]
                    y_coords = [t[1] for t in last_two]
                    ax2.plot(x_coords, y_coords, 'g--', linewidth=2, alpha=0.8)
            
            ax2.set_ylabel('MACD')
            ax2.set_xlabel('Time')
            ax2.legend()
            ax2.grid(True, alpha=0.3)
            
            if len(df) > 0:
                ax2.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
                ax2.xaxis.set_major_locator(mdates.HourLocator(interval=2))
                plt.xticks(rotation=45)
            
            plt.tight_layout()
            
            # GUARDA O GRÁFICO
            timestamp = df['time'].iloc[-1].strftime('%Y%m%d_%H%M%S')
            filename = f"{chart_dir}/{self.symbol}_{divergence_type}_{timestamp}.png"
            
            plt.savefig(filename, dpi=300, bbox_inches='tight')
            plt.close()  
            
            logging.info(f"Chart saved: {filename}")
            
        except Exception as e:
            logging.error(f"Error saving chart: {e}")
            import traceback
            logging.error(f"Traceback: {traceback.format_exc()}")

    def run(self):
        logging.info(f"Starting bot for {self.symbol}")
        
        last_histogram = None
        last_trade_time = 0
        cooldown = 60
        divergence_valid_time = 1800
        
        while True:
            try:
                macd_df = self.get_macd()
                if macd_df is None or len(macd_df) < self.min_history:
                    time.sleep(30)
                    continue
                
                current_time = time.time()
                current_histogram = macd_df['histogram'].iloc[-1]
                
                # MOSTRA EXPOSIÇAO DE MERCADO
                net_exposure = self.hedging_manager.calculate_net_exposure()
                logging.info(f"{self.symbol} - Histogram: {current_histogram:.6f} | Net Exposure: {net_exposure:.2f}")
                
                if current_time - last_trade_time < cooldown:
                    time.sleep(10)
                    continue
                
                # DETECTA DIVERGENCIAS MACD BEARISH Y BULLISH
                if self.detect_bullish_divergence(macd_df):
                    self.divergence_detected = "bullish"
                    self.divergence_timestamp = current_time
                    logging.info(f"🔍 BULLISH DIVERGENCE detected in {self.symbol}")
                    
                elif self.detect_bearish_divergence(macd_df):
                    self.divergence_detected = "bearish"
                    self.divergence_timestamp = current_time
                    logging.info(f"🔍 BEARISH DIVERGENCE detected in {self.symbol}")
                
                # DETECTA DIVERGENCIAS MACD
                if (self.divergence_detected is not None and 
                    current_time - self.divergence_timestamp > divergence_valid_time):
                    self.divergence_detected = None
                    self.divergence_timestamp = 0
                
                
                should_buy = False
                should_sell = False
                trade_reason = ""
                
                if (self.divergence_detected is not None and last_histogram is not None):
                    
                    if (self.divergence_detected == "bullish" and
                        last_histogram <= 0 and current_histogram > 0):
                        should_buy = True
                        trade_reason = "Bullish Divergence + Histogram Zero Cross"
                        
                    elif (self.divergence_detected == "bearish" and
                          last_histogram >= 0 and current_histogram < 0):
                        should_sell = True
                        trade_reason = "Bearish Divergence + Histogram Zero Cross"
                
                if should_buy:
                    logging.info(f"🟢 BUY SIGNAL: {trade_reason}")
                    if self.order_send_with_hedging("buy", trade_reason):
                        last_trade_time = current_time
                        self.divergence_detected = None
                        self.divergence_timestamp = 0
                        
                elif should_sell:
                    logging.info(f"🔴 SELL SIGNAL: {trade_reason}")
                    if self.order_send_with_hedging("sell", trade_reason):
                        last_trade_time = current_time
                        self.divergence_detected = None
                        self.divergence_timestamp = 0
                
                last_histogram = current_histogram
                
            except Exception as e:
                logging.error(f"❌ Error in {self.symbol}: {e}")
                
            time.sleep(10)

def main():
    print("🚀 Forex Trading Bot with Hedging Starting...")
    
    parser = argparse.ArgumentParser(description='Forex Trading Bot with Hedging')
    parser.add_argument('--lot_size', type=float, default=0.01, help='Lot size')
    parser.add_argument('--symbols', nargs='+', default=["EURUSD", "USDJPY"], help='Symbols')
    parser.add_argument('--hedging', action='store_true', help='Enable hedging (default: enabled)')
    args = parser.parse_args()

    print(f"Lot size: {args.lot_size}")
    print(f"Symbols: {args.symbols}")
    print(f"Hedging: {'Enabled' if args.hedging or True else 'Disabled'}")

    bots = [ForexTradingBot(symbol=s, lot_size=args.lot_size) for s in args.symbols]
    threads = []
    
    for bot in bots:
        bot.hedging_enabled = args.hedging if args.hedging else True
        t = threading.Thread(target=bot.run)
        t.daemon = True
        t.start()
        threads.append(t)

    try:
        print("Bot is running... Press Ctrl+C to stop")
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
        logging.info("Shutting down...")
    finally:
        mt5.shutdown()
        print("✅ MT5 disconnected")

if __name__ == "__main__":
    main()