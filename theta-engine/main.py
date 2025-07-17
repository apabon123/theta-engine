from AlgorithmImports import *

class DeltaHedgedThetaEngine(QCAlgorithm):
    def Initialize(self):
        self.SetStartDate(2023, 1, 1)
        self.SetEndDate(2023, 6, 30)
        self.SetCash(1000000)
        self.symbol = self.AddIndex("SPX").Symbol
        self.option = self.AddIndexOption("SPX", Resolution.Daily)
        self.option.SetFilter(-50, 50, 70, 110)
        self.optionSymbol = self.option.Symbol

        self.Schedule.On(self.DateRules.EveryDay(), self.TimeRules.AfterMarketOpen("SPX", 5), self.EntryLogic)
        self.Schedule.On(self.DateRules.EveryDay(), self.TimeRules.BeforeMarketClose("SPX", 30), self.HedgeLogic)
        self.Schedule.On(self.DateRules.EveryDay(), self.TimeRules.AfterMarketOpen("SPX", 5), self.CheckExits)

        self.positions = []
        self.max_positions = 4
        self.days_between_trades = 5
        self.last_trade_time = None

        self.iv_window = RollingWindow[float](252)  # 1 year of daily IVs
        self.SetWarmUp(timedelta(days=365))  # 1 year warmup for IVRank

    def OnData(self, slice: Slice):
        chain = slice.OptionChains.get(self.optionSymbol)
        if chain:
            iv = max([x.ImpliedVolatility for x in chain])
            if iv:
                self.iv_window.Add(iv)

    def filter_chain_efficiently(self, chain):
        target_expiry = self.Time + timedelta(days=90)
        relevant_contracts = [x for x in chain if abs((x.Expiry - target_expiry).days) <= 7]
        puts = [x for x in relevant_contracts if x.Right == OptionRight.Put]
        return puts

    def EntryLogic(self):
        if self.IsWarmingUp:
            return
        if self.last_trade_time and (self.Time - self.last_trade_time).days < self.days_between_trades:
            return
        if len(self.positions) >= self.max_positions:
            return
        if not self.iv_window.IsReady:
            return

        chain = self.CurrentSlice.OptionChains.get(self.optionSymbol)
        if not chain: return

        puts = self.filter_chain_efficiently(chain)
        if not puts:
            return
        expiry = sorted([x.Expiry for x in puts])[0]
        puts = [x for x in puts if x.Expiry == expiry]
        puts = sorted(puts, key=lambda x: abs(x.Greeks.Delta + 0.15))
        if not puts: return
        short_put = puts[0]
        price = (short_put.BidPrice + short_put.AskPrice) / 2

        # Check for price data before trading
        if not self.Securities.ContainsKey(short_put.Symbol) or not self.Securities[short_put.Symbol].HasData:
            return

        qty = int(max(1, ((0.13 / 0.27 / 252) * self.Portfolio.TotalPortfolioValue) / (price * 100)))
        self.MarketOrder(short_put.Symbol, -qty)

        self.positions.append({
            "symbol": short_put.Symbol,
            "qty": qty,
            "entry_price": price,
            "entry_time": self.Time,
            "hedged": False
        })
        self.last_trade_time = self.Time

    def HedgeLogic(self):
        if self.IsWarmingUp:
            return
        if not self.iv_window.IsReady:
            return
        iv_rank = sum([1 for x in self.iv_window if x <= self.iv_window[0]]) / self.iv_window.Count

        if iv_rank < 0.5:
            return

        chain = self.CurrentSlice.OptionChains.get(self.optionSymbol)
        if not chain:
            return

        puts = self.filter_chain_efficiently(chain)
        for pos in self.positions:
            if pos["hedged"]:
                continue

            expiry = pos["symbol"].ID.Date
            hedge_puts = [x for x in puts if x.Expiry == expiry]
            if not hedge_puts:
                continue
            hedge_put = sorted(hedge_puts, key=lambda x: abs(x.Greeks.Delta + 0.04))[0]

            # Check for price data before trading
            if not self.Securities.ContainsKey(hedge_put.Symbol) or not self.Securities[hedge_put.Symbol].HasData:
                continue

            self.MarketOrder(hedge_put.Symbol, 3 * pos["qty"])
            pos["hedged"] = True

    def CheckExits(self):
        if self.IsWarmingUp:
            return
        to_remove = []
        for pos in self.positions:
            sec = self.Securities[pos["symbol"]]
            price = sec.Price
            entry = pos["entry_price"]
            qty = pos["qty"]
            pnl = (entry - price) * qty * 100

            target = entry * 0.6 * qty * 100
            stop = entry * 3.0 * qty * 100

            if pnl >= target or pnl <= -stop or (self.Time - pos["entry_time"]).days >= 90:
                self.Liquidate(pos["symbol"])
                to_remove.append(pos)

        for pos in to_remove:
            self.positions.remove(pos)
