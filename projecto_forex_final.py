import MetaTrader5 as mt5
import time
import logging
import pandas as pd
import argparse
import threading
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import os  # Add this missing import

# Initialize MT5
mt5.initialize(path="C:\\Program Files\\MetaTrader 5\\terminal64.exe")

# Login
account = 1009160
authorized = mt5.login(account, password="I9tqhwal_", server="JFD-DEMO")
if authorized:
    print("Connected to MT5")
else:
    print(f"Failed to connect: {mt5.last_error()}")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class ForexTradingBot:
    def __init__(self, symbol, lot_size):
        self.symbol = symbol
        self.lot_size = lot_size
        self.min_history = 50  # Reduced for faster startup
        self.divergence_lookback = 50  # Reduced for testing
        self.chart_enabled = False  # Disable charts initially for testing
        self.divergence_detected = None
        self.divergence_timestamp = 0

    def get_macd(self, periods=250):  # Increased to get more data
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
        """Detect bullish divergence in last 200 candles"""
        if len(df) < self.divergence_lookback:
            return False
            
        # Use last 200 candles for analysis
        analysis_df = df.tail(self.divergence_lookback)
        
        price_peaks, price_troughs = self.find_peaks_troughs(analysis_df['close'], lookback=3)
        macd_peaks, macd_troughs = self.find_peaks_troughs(analysis_df['macd'], lookback=3)
        
        if len(price_troughs) < 2 or len(macd_troughs) < 2:
            return False
            
        # Check multiple trough combinations for stronger divergence
        for i in range(len(price_troughs)-1):
            for j in range(len(macd_troughs)-1):
                if i < len(price_troughs)-1 and j < len(macd_troughs)-1:
                    price_trough1 = price_troughs[i]
                    price_trough2 = price_troughs[i+1]
                    macd_trough1 = macd_troughs[j]
                    macd_trough2 = macd_troughs[j+1]
                    
                    # Price makes lower low, MACD makes higher low
                    price_lower_low = price_trough2[1] < price_trough1[1]
                    macd_higher_low = macd_trough2[1] > macd_trough1[1]
                    
                    if price_lower_low and macd_higher_low:
                        return True
                        
        return False

    def detect_bearish_divergence(self, df):
        """Detect bearish divergence in last 200 candles"""
        if len(df) < self.divergence_lookback:
            return False
            
        # Use last 200 candles for analysis
        analysis_df = df.tail(self.divergence_lookback)
        
        price_peaks, price_troughs = self.find_peaks_troughs(analysis_df['close'], lookback=3)
        macd_peaks, macd_troughs = self.find_peaks_troughs(analysis_df['macd'], lookback=3)
        
        if len(price_peaks) < 2 or len(macd_peaks) < 2:
            return False
            
        # Check multiple peak combinations for stronger divergence
        for i in range(len(price_peaks)-1):
            for j in range(len(macd_peaks)-1):
                if i < len(price_peaks)-1 and j < len(macd_peaks)-1:
                    price_peak1 = price_peaks[i]
                    price_peak2 = price_peaks[i+1]
                    macd_peak1 = macd_peaks[j]
                    macd_peak2 = macd_peaks[j+1]
                    
                    # Price makes higher high, MACD makes lower high
                    price_higher_high = price_peak2[1] > price_peak1[1]
                    macd_lower_high = macd_peak2[1] < macd_peak1[1]
                    
                    if price_higher_high and macd_lower_high:
                        return True
                        
        return False

    def detect_macd_convergence(self, df):
        """Enhanced convergence detection"""
        if len(df) < 50:
            return None
            
        macd_values = df['macd'].tail(50)
        signal_values = df['signal'].tail(50)
        diff = abs(macd_values - signal_values)
        
        # Check if MACD and signal are converging
        recent_diff = diff.tail(10).mean()
        older_diff = diff.head(10).mean()
        
        if recent_diff < older_diff * 0.5:  # 50% convergence
            current_histogram = df['histogram'].iloc[-1]
            if current_histogram > 0:
                return "convergence_from_above"
            else:
                return "convergence_from_below"
                    
        return None

    def order_send(self, action, reason=""):
        # Select symbol
        mt5.symbol_select(self.symbol, True)
        
        # Get tick data
        tick = mt5.symbol_info_tick(self.symbol)
        if tick is None:
            return False
            
        # Get symbol info
        symbol_info = mt5.symbol_info(self.symbol)
        if symbol_info is None:
            return False
            
        # Calculate prices
        price = tick.ask if action == 'buy' else tick.bid
        point = symbol_info.point
        sl = price - 50 * point if action == 'buy' else price + 50 * point
        tp = price + 50 * point if action == 'buy' else price - 50 * point

        # Build request
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
            "comment": f"{action} - {reason}",
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        # Send order
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
            # Create charts directory first
            chart_dir = "charts"
            if not os.path.exists(chart_dir):
                os.makedirs(chart_dir)
            
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(15, 8), sharex=True)
            
            # Price chart with trend lines
            ax1.plot(df['time'], df['close'], 'b-', linewidth=1, label='Price')
            
            # Find and plot peaks/troughs - FIX THE INDEXING
            analysis_df = df.tail(200)  # Work with last 200 candles
            price_peaks, price_troughs = self.find_peaks_troughs(analysis_df['close'])
            macd_peaks, macd_troughs = self.find_peaks_troughs(analysis_df['macd'])
            
            # Plot price peaks and troughs
            if price_peaks:
                peak_times = [analysis_df['time'].iloc[p[0]] for p in price_peaks]
                peak_values = [p[1] for p in price_peaks]
                ax1.scatter(peak_times, peak_values, color='red', s=30, marker='^')
                
                # Draw trend line connecting last two peaks
                if len(price_peaks) >= 2:
                    last_two = price_peaks[-2:]
                    x_coords = [analysis_df['time'].iloc[p[0]] for p in last_two]
                    y_coords = [p[1] for p in last_two]
                    ax1.plot(x_coords, y_coords, 'r--', linewidth=2, alpha=0.8)
                    
            if price_troughs:
                trough_times = [analysis_df['time'].iloc[t[0]] for t in price_troughs]
                trough_values = [t[1] for t in price_troughs]
                ax1.scatter(trough_times, trough_values, color='green', s=30, marker='v')
                
                # Draw trend line connecting last two troughs
                if len(price_troughs) >= 2:
                    last_two = price_troughs[-2:]
                    x_coords = [analysis_df['time'].iloc[t[0]] for t in last_two]
                    y_coords = [t[1] for t in last_two]
                    ax1.plot(x_coords, y_coords, 'g--', linewidth=2, alpha=0.8)
            
            ax1.set_ylabel('Price')
            ax1.set_title(f'{self.symbol} - {reason} - {df["time"].iloc[-1].strftime("%Y-%m-%d %H:%M")}')
            ax1.grid(True, alpha=0.3)
            
            # Add divergence annotation
            color = 'green' if divergence_type == 'bullish' else 'red'
            ax1.annotate(f'{reason}', xy=(df['time'].iloc[-1], df['close'].iloc[-1]), 
                        xytext=(10, 10), textcoords='offset points',
                        bbox=dict(boxstyle='round,pad=0.3', fc=color, alpha=0.7),
                        arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0'))
            
            # MACD chart with trend lines
            ax2.plot(df['time'], df['macd'], 'b-', linewidth=1, label='MACD')
            ax2.plot(df['time'], df['signal'], 'orange', linewidth=1, label='Signal')
            ax2.bar(df['time'], df['histogram'], alpha=0.3, color='gray', label='Histogram')
            ax2.axhline(y=0, color='black', linestyle='-', alpha=0.3)
            
            # Plot MACD peaks and troughs with trend lines
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
            
            # Format x-axis
            if len(df) > 0:
                ax2.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
                ax2.xaxis.set_major_locator(mdates.HourLocator(interval=2))
                plt.xticks(rotation=45)
            
            plt.tight_layout()
            
            # Save chart
            timestamp = df['time'].iloc[-1].strftime('%Y%m%d_%H%M%S')
            filename = f"{chart_dir}/{self.symbol}_{divergence_type}_{timestamp}.png"
            
            plt.savefig(filename, dpi=300, bbox_inches='tight')
            plt.close()  # Close to free memory
            
            logging.info(f"Chart saved: {filename}")
            
        except Exception as e:
            logging.error(f"Error saving chart: {e}")
            import traceback
            logging.error(f"Traceback: {traceback.format_exc()}")

    def run(self):
        logging.info(f"Starting bot for {self.symbol}")
        
        last_histogram = None
        last_trade_time = 0
        cooldown = 60  # Reduced for testing
        divergence_valid_time = 1800  # 30 minutes for testing
        
        while True:
            try:
                # Check MT5 connection
                if not mt5.terminal_info():
                    logging.error(f"MT5 not connected for {self.symbol}")
                    time.sleep(30)
                    continue
                
                macd_df = self.get_macd()
                if macd_df is None:
                    logging.warning(f"No data received for {self.symbol}")
                    time.sleep(30)
                    continue
                    
                if len(macd_df) < self.min_history:
                    logging.warning(f"Insufficient data for {self.symbol}: {len(macd_df)}/{self.min_history}")
                    time.sleep(30)
                    continue
                
                current_time = time.time()
                current_histogram = macd_df['histogram'].iloc[-1]
                
                logging.info(f"{self.symbol} - Histogram: {current_histogram:.6f}")
                
                # Check cooldown
                if current_time - last_trade_time < cooldown:
                    time.sleep(10)
                    continue
                
                # 1. CHECK FOR DIVERGENCES (and mark them)
                try:
                    if self.detect_bullish_divergence(macd_df):
                        self.divergence_detected = "bullish"
                        self.divergence_timestamp = current_time
                        logging.info(f"🔍 BULLISH DIVERGENCE detected in {self.symbol} - waiting for histogram zero cross")
                        if self.chart_enabled:
                            self.save_divergence_chart(macd_df, "bullish", "Bullish Divergence Detected")
                        
                    elif self.detect_bearish_divergence(macd_df):
                        self.divergence_detected = "bearish"
                        self.divergence_timestamp = current_time
                        logging.info(f"🔍 BEARISH DIVERGENCE detected in {self.symbol} - waiting for histogram zero cross")
                        if self.chart_enabled:
                            self.save_divergence_chart(macd_df, "bearish", "Bearish Divergence Detected")
                except Exception as div_error:
                    logging.error(f"Error in divergence detection for {self.symbol}: {div_error}")
                
                # 2. CHECK FOR CONVERGENCES (and mark them)
                try:
                    convergence_type = self.detect_macd_convergence(macd_df)
                    if convergence_type is not None:
                        if convergence_type == "convergence_from_below":
                            self.divergence_detected = "bullish_convergence"
                            self.divergence_timestamp = current_time
                            logging.info(f"🔍 BULLISH CONVERGENCE detected in {self.symbol} - waiting for histogram zero cross")
                        elif convergence_type == "convergence_from_above":
                            self.divergence_detected = "bearish_convergence"
                            self.divergence_timestamp = current_time
                            logging.info(f"🔍 BEARISH CONVERGENCE detected in {self.symbol} - waiting for histogram zero cross")
                except Exception as conv_error:
                    logging.error(f"Error in convergence detection for {self.symbol}: {conv_error}")
                
                # 3. CHECK IF DIVERGENCE/CONVERGENCE IS STILL VALID
                if (self.divergence_detected is not None and 
                    current_time - self.divergence_timestamp > divergence_valid_time):
                    logging.info(f"⏰ Divergence/Convergence expired for {self.symbol}")
                    self.divergence_detected = None
                    self.divergence_timestamp = 0
                
                # 4. EXECUTE TRADES
                should_buy = False
                should_sell = False
                trade_reason = ""
                
                if (self.divergence_detected is not None and last_histogram is not None):
                    
                    # BULLISH SIGNALS
                    if (self.divergence_detected in ["bullish", "bullish_convergence"] and
                        last_histogram <= 0 and current_histogram > 0):
                        should_buy = True
                        trade_reason = f"{self.divergence_detected.replace('_', ' ').title()} + Histogram Zero Cross"
                        
                    # BEARISH SIGNALS
                    elif (self.divergence_detected in ["bearish", "bearish_convergence"] and
                          last_histogram >= 0 and current_histogram < 0):
                        should_sell = True
                        trade_reason = f"{self.divergence_detected.replace('_', ' ').title()} + Histogram Zero Cross"
                
                # Execute trades
                if should_buy:
                    logging.info(f"🟢 BUY SIGNAL: {trade_reason}")
                    if self.order_send("buy", trade_reason):
                        last_trade_time = current_time
                        self.divergence_detected = None
                        self.divergence_timestamp = 0
                        
                elif should_sell:
                    logging.info(f"🔴 SELL SIGNAL: {trade_reason}")
                    if self.order_send("sell", trade_reason):
                        last_trade_time = current_time
                        self.divergence_detected = None
                        self.divergence_timestamp = 0
                
                # Show current status
                if self.divergence_detected is not None:
                    time_remaining = divergence_valid_time - (current_time - self.divergence_timestamp)
                    logging.info(f"📊 {self.symbol} - Waiting for histogram cross | "
                               f"Divergence: {self.divergence_detected} | "
                               f"Time remaining: {time_remaining/60:.1f} min")
                else:
                    logging.info(f"📊 {self.symbol} - Scanning for divergence/convergence...")
                
                # Update last values
                last_histogram = current_histogram
                
            except Exception as e:
                logging.error(f"❌ Critical error in {self.symbol}: {e}")
                import traceback
                logging.error(f"Traceback: {traceback.format_exc()}")
                
            time.sleep(10)  # Reduced sleep time

def main():
    parser = argparse.ArgumentParser(description='Forex Trading Bot')
    parser.add_argument('--lot_size', type=float, default=0.01, help='Lot size')
    parser.add_argument('--symbols', nargs='+', default=["EURUSD", "USDJPY"], help='Symbols')
    args = parser.parse_args()

    bots = [ForexTradingBot(symbol=s, lot_size=args.lot_size) for s in args.symbols]
    threads = []
    
    for bot in bots:
        t = threading.Thread(target=bot.run)
        t.daemon = True
        t.start()
        threads.append(t)

    try:
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        logging.info("Shutting down...")
    finally:
        mt5.shutdown()

if __name__ == "__main__":
    main()
