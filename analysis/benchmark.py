"""Frozen gold-policy benchmark. Run with bundled Python (numpy and pandas).

This is a conservative M1 execution approximation, not a replacement for MT5's
real-tick tester. It conditions on the strategy's logged signal opportunities.
No parameter search or validation-dependent strategy changes occur here.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PERIODS = {
    "development": ("2026-01-13", "2026-07-01"),
    "validation": ("2026-07-01", "2026-08-15"),
    "contextual": ("2026-08-17", "2026-10-24"),
}
SEED = 20261026
N_SIMULATIONS = 5000
INITIAL_BALANCE = 10000.0
RISK_FRACTION = 0.0025
ROUNDTRIP_COMMISSION = 7.0
SLIPPAGE_PRICE_PER_SIDE = 0.10
MAX_SPREAD_PRICE = 1.0
MAX_SPREAD_TO_STOP = 0.10
MAX_EXTRA_COST_TO_BUDGET = 0.10
MAX_H1_BARS = 72
SWAP_REFERENCE = "https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants"


def read_specs(path: Path) -> dict[str, str]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))
    return {row[0]: row[1] for row in rows[1:] if len(row) >= 2}


def as_seconds(values: Any) -> np.ndarray:
    return pd.DatetimeIndex(values).as_unit("s").asi8


def iso(seconds: int) -> str:
    return pd.Timestamp(int(seconds), unit="s").isoformat()


class Market:
    def __init__(self, frame: pd.DataFrame, specs: dict[str, str], swap_name: str | None,
                 sessions: pd.DataFrame | None = None, dataset_name: str = "legacy_bid_M1"):
        self.specs = specs
        self.point = float(specs["point"])
        self.digits = int(specs["digits"])
        self.tick = float(specs["tick_size"])
        self.contract = float(specs["contract_size"])
        self.min_lot = float(specs["volume_min"])
        self.max_lot = float(specs["volume_max"])
        self.lot_step = float(specs["volume_step"])
        self.stop_min = float(specs.get("stops_level_points", 0)) * self.point
        if specs.get("currency_profit") != "USD" or specs.get("account_currency") != "USD":
            raise ValueError("This frozen benchmark supports USD profit and account currency only.")
        if any(v <= 0 for v in [self.point, self.tick, self.contract, self.min_lot, self.max_lot, self.lot_step]):
            raise ValueError("Invalid contract or volume specification.")
        self.frame = frame
        self.times = as_seconds(frame["time"])
        self.open = frame["open"].to_numpy(float)
        self.high = frame["high"].to_numpy(float)
        self.low = frame["low"].to_numpy(float)
        self.close = frame["close"].to_numpy(float)
        self.spread = frame["spread"].to_numpy(float) * self.point
        self.actual_ask_ohlc = all("ask_" + field in frame for field in ["open", "high", "low", "close"])
        self.ask_open = frame["ask_open"].to_numpy(float) if self.actual_ask_ohlc else self.open + self.spread
        self.ask_high = frame["ask_high"].to_numpy(float) if self.actual_ask_ohlc else self.high + self.spread
        self.ask_low = frame["ask_low"].to_numpy(float) if self.actual_ask_ohlc else self.low + self.spread
        self.ask_close = frame["ask_close"].to_numpy(float) if self.actual_ask_ohlc else self.close + self.spread
        self.last_tick_times = as_seconds(frame["last_tick_time"]) if "last_tick_time" in frame else self.times + 59
        self.dataset_name = dataset_name
        self.session_rows = [] if sessions is None else [(int(row.day), int(row.from_seconds), int(row.to_seconds)) for row in sessions.itertuples()]
        self.has_trade_sessions = sessions is not None
        self.zero_length_sessions = 0
        for day, beginning, ending in self.session_rows:
            if not 0 <= day <= 6 or not 0 <= beginning < 86400 or not 0 <= ending <= 86400:
                raise ValueError("Invalid broker trade-session weekday or seconds.")
            self.zero_length_sessions += beginning == ending
        self._build_trade_minutes()
        self.hour_times, self.hour_first = np.unique(self.times // 3600, return_index=True)
        self.extra_per_lot = ROUNDTRIP_COMMISSION + 2 * SLIPPAGE_PRICE_PER_SIDE * self.contract
        self.swap_mode = int(specs["swap_mode"])
        self.swap_name = swap_name or specs.get("swap_mode_name")
        self.swap_unit, self.funding_description = self._funding_unit()
        # When explicit per-weekday multipliers are not exported, the traditional
        # weekday/triple-day schedule is an assumption, not a known broker fact.
        self.weekday_ratios = np.zeros(7)
        triple = int(specs.get("swap_rollover3days", 3))
        names = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]
        self.explicit_weekday_ratios = all("swap_" + d in specs for d in names)
        for mql_day, day in enumerate(names):
            default = 0.0 if mql_day in (0, 6) else (3.0 if mql_day == triple else 1.0)
            self.weekday_ratios[mql_day] = float(specs.get("swap_" + day, default))

    def _build_trade_minutes(self) -> None:
        """Intersect quoted minutes with recurring broker-server sessions.

        A partial boundary minute remains approximate because its OHLC can also
        include non-tradable quotes. Exact entry timestamps are checked separately.
        """
        self.first_tradable_time = self.times.copy()
        self.last_tradable_time = self.times + 59
        self.tradable = np.ones(len(self.times), dtype=bool)
        if self.has_trade_sessions:
            self.first_tradable_time[:] = np.iinfo(np.int64).max
            self.last_tradable_time[:] = -1
            date_start = self.times // 86400 * 86400
            weekdays = (self.times // 86400 + 4) % 7  # 1970-01-01 was Thursday.
            for day, beginning, ending in self.session_rows:
                if beginning == ending:
                    continue  # Explicit 0..86400 represents a full day instead.
                duration_end = ending + (86400 if ending < beginning else 0)
                for day_shift in (0, -1):
                    origin_day = (weekdays + day_shift) % 7
                    session_start = date_start + day_shift * 86400 + beginning
                    session_end = date_start + day_shift * 86400 + duration_end
                    first = np.maximum(self.times, session_start)
                    last = np.minimum(self.times + 60, session_end) - 1
                    overlaps = (origin_day == day) & (first <= last)
                    self.first_tradable_time = np.where(overlaps, np.minimum(self.first_tradable_time, first), self.first_tradable_time)
                    self.last_tradable_time = np.where(overlaps, np.maximum(self.last_tradable_time, last), self.last_tradable_time)
            self.tradable = (self.last_tradable_time >= self.first_tradable_time) & (self.last_tick_times >= self.first_tradable_time)
        self.tradable_indices = np.flatnonzero(self.tradable)
        self.partial_boundary_minutes = int(np.sum(self.tradable & ((self.first_tradable_time > self.times) | (self.last_tradable_time < self.times + 59))))

    def trading_at(self, timestamp: int) -> bool:
        if not self.has_trade_sessions:
            return True
        day = (timestamp // 86400 + 4) % 7
        second = timestamp % 86400
        for session_day, beginning, ending in self.session_rows:
            if beginning < ending and day == session_day and beginning <= second < ending:
                return True
            if beginning > ending and ((day == session_day and second >= beginning) or (day == (session_day + 1) % 7 and second < ending)):
                return True
        return False

    def tradable_fill_time(self, index: int, at_open: bool) -> int:
        if at_open:
            return int(self.first_tradable_time[index])
        return int(min(self.last_tick_times[index], self.last_tradable_time[index]))

    def _funding_unit(self) -> tuple[float, str]:
        mode = self.swap_mode
        if mode == 0:
            return 0.0, "Disabled swap mode."
        if mode == 1:
            return self.point * self.contract, "Static exported point swap, converted to USD per lot."
        if mode == 3 and self.specs.get("currency_margin") == "USD":
            return 1.0, "Static exported swap in USD margin currency per lot."
        if mode == 4:
            return 1.0, "Static exported swap in USD account currency per lot."
        if mode == 9 and self.swap_name == "SYMBOL_SWAP_MODE_CURRENCY_PROFIT":
            return 1.0, "Native-verified CURRENCY_PROFIT mode 9; profit currency USD; static exported rates per lot."
        if mode == 9:
            raise ValueError(
                "Swap mode 9 requires native enum confirmation. Supply "
                "--verified-swap-mode-name SYMBOL_SWAP_MODE_CURRENCY_PROFIT only after "
                "confirming that value in the installed MQL5 runtime. Funding was not silently omitted."
            )
        raise ValueError(f"Unsupported swap mode {mode}; refusing an after-costs benchmark with omitted funding.")

    def funding(self, entered: int, exited: int, direction: int) -> float:
        if self.swap_unit == 0 or exited <= entered:
            return 0.0
        first = pd.Timestamp(entered, unit="s").normalize() + pd.Timedelta(days=1)
        last = pd.Timestamp(exited, unit="s").normalize()
        if first > last:
            return 0.0
        # Midnight on date D rolls the position held on date D-1.
        days = pd.date_range(first, last, freq="D") - pd.Timedelta(days=1)
        mql_weekdays = (days.dayofweek.to_numpy() + 1) % 7
        charge_units = float(self.weekday_ratios[mql_weekdays].sum())
        rate = float(self.specs["swap_long" if direction > 0 else "swap_short"])
        return rate * self.swap_unit * charge_units

    def rounded_levels(self, entry: float, atr: float, direction: int) -> tuple[float, float]:
        if direction > 0:
            return round(float(np.floor((entry - 2 * atr) / self.tick) * self.tick), self.digits), round(float(np.ceil((entry + 4 * atr) / self.tick) * self.tick), self.digits)
        return round(float(np.ceil((entry + 2 * atr) / self.tick) * self.tick), self.digits), round(float(np.floor((entry - 4 * atr) / self.tick) * self.tick), self.digits)

    def outcome(self, signal: pd.Series, direction: int, period_end: int) -> dict[str, Any]:
        entered = int(pd.Timestamp(signal["time"]).timestamp())
        minute = entered // 60 * 60
        index = int(np.searchsorted(self.times, minute))
        invalid = {"valid": False, "entered": entered, "direction": direction, "reason": "missing_entry_minute"}
        if index >= len(self.times) or self.times[index] != minute:
            return invalid
        if not self.trading_at(entered):
            return {**invalid, "reason": "broker_market_closed_at_entry"}
        bid, ask = float(signal["entrybid"]), float(signal["ask"])
        entry = ask if direction > 0 else bid
        atr = float(signal["ATR"])
        stop, target = self.rounded_levels(entry, atr, direction)
        stop_distance = abs(entry - stop)
        spread = ask - bid
        if entry <= 0 or atr <= 0 or stop <= 0 or target <= 0 or spread < 0:
            return {**invalid, "reason": "invalid_quote_or_levels"}
        if spread > min(MAX_SPREAD_PRICE, MAX_SPREAD_TO_STOP * stop_distance) + 1e-10:
            return {**invalid, "reason": "spread_gate"}
        stops_ok = (stop < bid and target > ask and bid - stop >= self.stop_min and target - bid >= self.stop_min) if direction > 0 else (stop > ask and target < bid and stop - ask >= self.stop_min and ask - target >= self.stop_min)
        if not stops_ok:
            return {**invalid, "reason": "broker_stop_gate"}

        hour_index = int(np.searchsorted(self.hour_times, entered // 3600))
        deadline_hour = hour_index + MAX_H1_BARS
        deadline_index = int(self.hour_first[deadline_hour]) if deadline_hour < len(self.hour_first) else len(self.times)
        next_open = int(np.searchsorted(self.tradable_indices, deadline_index))
        deadline_index = int(self.tradable_indices[next_open]) if next_open < len(self.tradable_indices) else len(self.times)
        period_limit = int(np.searchsorted(self.times, period_end))
        limit = min(deadline_index, period_limit, len(self.times))
        if limit <= index:
            return {**invalid, "reason": "empty_exit_path"}

        # Check tradable quote minutes preceding the time exit. For same-minute
        # stop and target touches, the stop wins. Closed-session quotes cannot fill.
        selection = slice(index, limit)
        opening = self.open[selection]
        highs = self.high[selection]
        lows = self.low[selection]
        if direction < 0:
            opening = self.ask_open[selection]
            highs = self.ask_high[selection]
            lows = self.ask_low[selection]
        active = self.tradable[selection]
        stop_hits = np.flatnonzero(active & (lows <= stop)) if direction > 0 else np.flatnonzero(active & (highs >= stop))
        target_hits = np.flatnonzero(active & (highs >= target)) if direction > 0 else np.flatnonzero(active & (lows <= target))
        stop_offset = int(stop_hits[0]) if len(stop_hits) else limit - index + 1
        target_offset = int(target_hits[0]) if len(target_hits) else limit - index + 1
        ambiguous = False
        if stop_offset <= target_offset and stop_offset < limit - index:
            j = index + stop_offset
            gap = self.open[j] if direction > 0 else self.ask_open[j]
            gap_stop = gap <= stop if direction > 0 else gap >= stop
            exit_price = min(gap, stop) if direction > 0 else max(gap, stop)
            exited = self.tradable_fill_time(j, gap_stop)
            reason = "stop_gap" if gap_stop else "stop"
            ambiguous = stop_offset == target_offset
        elif target_offset < limit - index:
            j = index + target_offset
            gap = self.open[j] if direction > 0 else self.ask_open[j]
            gap_target = gap >= target if direction > 0 else gap <= target
            exit_price = target  # No favorable target-gap improvement.
            exited = self.tradable_fill_time(j, gap_target)
            reason = "target"
        elif deadline_index == limit and deadline_index < min(period_limit, len(self.times)):
            j = deadline_index
            gap = self.open[j] if direction > 0 else self.ask_open[j]
            if (gap <= stop if direction > 0 else gap >= stop):
                exit_price = min(gap, stop) if direction > 0 else max(gap, stop)
                reason = "stop_at_time_exit_open"
            elif (gap >= target if direction > 0 else gap <= target):
                exit_price = target
                reason = "target_at_time_exit_open"
            else:
                exit_price = gap
                reason = "72_bar_time_exit"
            exited = self.tradable_fill_time(j, True)
        else:
            j = limit - 1
            # Native Strategy Tester forcibly settles at the final quote even
            # if the trade session is closed. This is a test boundary, not an
            # order fill that a running strategy could necessarily obtain.
            exit_price = self.close[j] if direction > 0 else self.ask_close[j]
            exited = int(min(self.last_tick_times[j], period_end - 1))
            reason = "period_end_forced_settlement"

        return {
            "valid": True, "entered": entered, "exited": exited, "direction": direction,
            "entry": entry, "stop": stop, "target": target, "exit_price": float(exit_price),
            "risk_per_lot": stop_distance * self.contract,
            "gross_per_lot": direction * (exit_price - entry) * self.contract,
            "swap_per_lot": self.funding(entered, exited, direction),
            "extra_per_lot": self.extra_per_lot, "margin_per_lot": entry * self.contract / 100,
            "reason": reason, "ambiguous_stop_target_minute": bool(ambiguous),
        }


def simulate(market: Market, outcomes: list[tuple[dict, dict]], policy: str, rng: np.random.Generator,
             count: int = 1, long_probability: float = 0.5, extra_cost_multiplier: float = 1.0,
             signal_directions: np.ndarray | None = None, keep_trades: bool = False) -> dict[str, Any]:
    balance = np.full(count, INITIAL_BALANCE)
    peak = balance.copy()
    max_dd = np.zeros(count)
    free_after = np.full(count, -1, dtype=np.int64)
    trade_counts = np.zeros(count, dtype=int)
    wins = np.zeros(count, dtype=int)
    long_counts = np.zeros(count, dtype=int)
    sum_r = np.zeros(count)
    gross_wins = np.zeros(count)
    gross_losses = np.zeros(count)
    records: list[dict[str, Any]] = []
    skip_counts = {"busy": 0, "minimum_volume_or_budget": 0, "extra_cost_gate": 0, "margin_gate": 0, "invalid_path": 0}

    for signal_index, pair in enumerate(outcomes):
        entered = pair[0]["entered"]
        available = (free_after <= entered) & (balance > 0)
        if count == 1 and not available[0]:
            skip_counts["busy"] += 1
        if policy == "actual":
            directions = np.full(count, int(signal_directions[signal_index]))
        elif policy == "long_only":
            directions = np.ones(count, dtype=int)
        else:
            directions = np.where(rng.random(count) < long_probability, 1, -1)
        for direction, outcome in zip((1, -1), pair):
            choose = available & (directions == direction)
            if not outcome["valid"]:
                if count == 1 and choose[0]: skip_counts["invalid_path"] += 1
                continue
            budget = balance * RISK_FRACTION
            raw = np.minimum(budget / outcome["risk_per_lot"], market.max_lot)
            lots = np.floor(np.round(raw / market.lot_step, 8)) * market.lot_step
            valid_size = (raw >= market.min_lot) & (lots >= market.min_lot) & (lots <= market.max_lot) & (lots * outcome["risk_per_lot"] <= budget * (1 + 1e-10))
            extra = lots * outcome["extra_per_lot"] * extra_cost_multiplier
            # The stress scenario charges higher costs without changing frozen
            # eligibility: it measures robustness, not a new selected strategy.
            valid_cost = lots * outcome["extra_per_lot"] <= MAX_EXTRA_COST_TO_BUDGET * budget + 1e-10
            valid_margin = lots * outcome["margin_per_lot"] <= balance
            take = choose & valid_size & valid_cost & valid_margin
            if count == 1 and choose[0]:
                if not valid_size[0]: skip_counts["minimum_volume_or_budget"] += 1
                elif not valid_cost[0]: skip_counts["extra_cost_gate"] += 1
                elif not valid_margin[0]: skip_counts["margin_gate"] += 1
            net = lots * (outcome["gross_per_lot"] + outcome["swap_per_lot"]) - extra
            risk = lots * outcome["risk_per_lot"]
            realized_r = np.divide(net, risk, out=np.zeros_like(net), where=risk > 0)
            if keep_trades and count == 1 and take[0]:
                records.append({
                    "signal_index": signal_index, "entry_time": iso(entered), "exit_time": iso(outcome["exited"]),
                    "direction": direction, "lots": float(lots[0]), "entry": outcome["entry"],
                    "stop": outcome["stop"], "target": outcome["target"], "exit_price": outcome["exit_price"],
                    "gross_usd": float(lots[0] * outcome["gross_per_lot"]),
                    "funding_usd": float(lots[0] * outcome["swap_per_lot"]),
                    "additional_cost_usd": float(extra[0]), "net_usd": float(net[0]),
                    "planned_stop_risk_usd": float(risk[0]), "net_R": float(realized_r[0]),
                    "balance_after": float(balance[0] + net[0]), "exit_reason": outcome["reason"],
                    "ambiguous_stop_target_minute": outcome["ambiguous_stop_target_minute"],
                })
            balance += np.where(take, net, 0)
            peak = np.maximum(peak, balance)
            max_dd = np.maximum(max_dd, (peak - balance) / peak)
            free_after = np.where(take, outcome["exited"], free_after)
            trade_counts += take
            wins += take & (net > 0)
            long_counts += take & (direction > 0)
            sum_r += np.where(take, realized_r, 0)
            gross_wins += np.where(take & (net > 0), net, 0)
            gross_losses += np.where(take & (net < 0), -net, 0)

    return {"balances": balance, "returns_pct": (balance / INITIAL_BALANCE - 1) * 100,
            "closed_balance_drawdown_pct": max_dd * 100, "trade_counts": trade_counts,
            "win_counts": wins, "long_counts": long_counts, "sum_net_R": sum_r,
            "positive_net_usd": gross_wins, "negative_net_usd": gross_losses,
            "trades": records, "skip_counts": skip_counts}


def one_summary(sim: dict[str, Any]) -> dict[str, Any]:
    n = int(sim["trade_counts"][0])
    loss = float(sim["negative_net_usd"][0])
    return {"net_usd": float(sim["balances"][0] - INITIAL_BALANCE),
            "return_pct": float(sim["returns_pct"][0]), "trades": n,
            "win_rate_pct": float(sim["win_counts"][0] / n * 100) if n else None,
            "long_trades": int(sim["long_counts"][0]),
            "net_expectancy_R": float(sim["sum_net_R"][0] / n) if n else None,
            "closed_balance_max_drawdown_pct": float(sim["closed_balance_drawdown_pct"][0]),
            "profit_factor_after_modeled_costs": float(sim["positive_net_usd"][0] / loss) if loss else None,
            "skips": sim["skip_counts"]}


def distribution(sim: dict[str, Any], observed_return: float) -> dict[str, Any]:
    returns = sim["returns_pct"]
    return {"simulations": len(returns),
            "return_pct_quantiles": dict(zip(["p05", "p50", "p95"], map(float, np.quantile(returns, [.05, .5, .95])))),
            "probability_of_positive_return": float(np.mean(returns > 0)),
            "observed_percentile": float(np.mean(returns < observed_return) * 100),
            "benchmark_upper_tail_probability": float((1 + np.count_nonzero(returns >= observed_return)) / (len(returns) + 1)),
            "trade_count_min_median_max": list(map(float, [sim["trade_counts"].min(), np.median(sim["trade_counts"]), sim["trade_counts"].max()])),
            "interpretation": "Conditional random-policy benchmark rank; not a formal exchangeable permutation p-value."}


def weekly_bootstrap(trades: list[dict[str, Any]], start: str, end: str, rng: np.random.Generator) -> dict[str, Any]:
    weeks = pd.period_range(pd.Timestamp(start).to_period("W-SUN"), (pd.Timestamp(end) - pd.Timedelta(seconds=1)).to_period("W-SUN"), freq="W-SUN")
    sums = np.zeros(len(weeks)); counts = np.zeros(len(weeks), dtype=int)
    for trade in trades:
        period = pd.Timestamp(trade["exit_time"]).to_period("W-SUN")
        j = weeks.get_loc(period)
        sums[j] += trade["net_R"]; counts[j] += 1
    sample = rng.integers(0, len(weeks), size=(N_SIMULATIONS, len(weeks)))
    total_count = counts[sample].sum(axis=1)
    means = np.divide(sums[sample].sum(axis=1), total_count, out=np.full(N_SIMULATIONS, np.nan), where=total_count > 0)
    valid = means[np.isfinite(means)]
    ci = list(map(float, np.quantile(valid, [.025, .975]))) if len(valid) else [None, None]
    return {"unit": "calendar week, grouped by trade exit, including zero-trade weeks",
            "calendar_weeks": len(weeks), "zero_trade_weeks": int(np.sum(counts == 0)),
            "replications": N_SIMULATIONS, "valid_nonempty_replications": len(valid),
            "net_expectancy_R_95pct_interval": ci,
            "distinct_entry_days": len({trade["entry_time"][:10] for trade in trades}),
            "limitation": "Few calendar blocks give imprecise intervals; days and trades are not assumed independent."}


def load_market(data: Path, swap_name: str | None) -> Market:
    specs = read_specs(data / "CodexGold_specs_20261026.csv")
    quote_path = data / "CodexGold_QuoteM1_20261028.csv"
    data_path = quote_path if quote_path.exists() else data / "CodexGold_M1_20261026.csv"
    frame = pd.read_csv(data_path, encoding="utf-8-sig")
    frame["time"] = pd.to_datetime(frame["time"], format="%Y.%m.%d %H:%M", errors="raise")
    numeric = ["open", "high", "low", "close", "spread"]
    if data_path == quote_path:
        numeric += ["ask_open", "ask_high", "ask_low", "ask_close"]
        if pd.api.types.is_numeric_dtype(frame["last_tick_time"]):
            frame["last_tick_time"] = pd.to_datetime(frame["last_tick_time"], unit="s", errors="raise")
        else:
            frame["last_tick_time"] = pd.to_datetime(frame["last_tick_time"], format="%Y.%m.%d %H:%M:%S", errors="raise")
        if ((frame["last_tick_time"] < frame["time"]) | (frame["last_tick_time"] >= frame["time"] + pd.Timedelta(minutes=1))).any():
            raise ValueError("Quote last-tick timestamp is outside its aggregated minute.")
    values = frame[numeric].to_numpy(float)
    if not np.isfinite(values).all(): raise ValueError("Missing/non-finite bar prices or spreads.")
    if frame["time"].duplicated().any() or not frame["time"].is_monotonic_increasing:
        raise ValueError("M1 bars must have unique chronological timestamps.")
    if (frame["spread"] < 0).any() or (frame[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("Invalid price or spread.")
    if (frame["high"] < frame[["open", "close", "low"]].max(axis=1)).any() or (frame["low"] > frame[["open", "close", "high"]].min(axis=1)).any():
        raise ValueError("Inconsistent OHLC bars.")
    if data_path == quote_path:
        if (frame[["ask_open", "ask_high", "ask_low", "ask_close"]] <= 0).any().any():
            raise ValueError("Invalid ask quote.")
        if (frame["ask_high"] < frame[["ask_open", "ask_close", "ask_low"]].max(axis=1)).any() or (frame["ask_low"] > frame[["ask_open", "ask_close", "ask_high"]].min(axis=1)).any():
            raise ValueError("Inconsistent ask OHLC bars.")
    session_path = data / "CodexGold_trade_sessions_20261028.csv"
    if data_path == quote_path and not session_path.exists():
        raise ValueError("Actual quote dataset requires the corresponding broker trade-session export.")
    sessions = pd.read_csv(session_path, encoding="utf-8-sig") if session_path.exists() else None
    dataset_type = "native real-tick bid/ask quotes aggregated to M1" if data_path == quote_path else "legacy bid M1 with ask approximated from spread snapshot"
    market = Market(frame, specs, swap_name, sessions=sessions, dataset_name=dataset_type)
    market.data_path = data_path
    market.session_path = session_path if session_path.exists() else None
    return market


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True, choices=PERIODS)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--initial-balance", type=float, choices=[10000.0,100000.0], default=10000.0)
    parser.add_argument("--verified-swap-mode-name", choices=["SYMBOL_SWAP_MODE_CURRENCY_PROFIT"])
    args = parser.parse_args()
    global INITIAL_BALANCE
    INITIAL_BALANCE = args.initial_balance
    market = load_market(args.data, args.verified_swap_mode_name)
    start, end = PERIODS[args.label]
    end_seconds = int(pd.Timestamp(end).timestamp())
    source = args.data / (args.label + "_GoldBreakout_Opportunities_20261026.csv")
    opportunities = pd.read_csv(source, encoding="utf-8-sig")
    opportunities["time"] = pd.to_datetime(opportunities["time"], format="%Y.%m.%d %H:%M:%S", errors="raise")
    if opportunities["time"].duplicated().any() or not opportunities["time"].is_monotonic_increasing:
        raise ValueError("Opportunity timestamps must be unique and chronological.")
    opportunities = opportunities[(opportunities["time"] >= start) & (opportunities["time"] < end)].copy()
    if not opportunities["dir"].isin([-1, 1]).all(): raise ValueError("Invalid signal direction.")
    if not np.isfinite(opportunities[["ATR", "entrybid", "ask"]].to_numpy(float)).all(): raise ValueError("Invalid opportunity values.")
    outcomes = [(market.outcome(row, 1, end_seconds), market.outcome(row, -1, end_seconds)) for _, row in opportunities.iterrows()]
    directions = opportunities["dir"].to_numpy(int)
    rng = np.random.default_rng(SEED)
    actual = simulate(market, outcomes, "actual", rng, signal_directions=directions, keep_trades=True)
    observed = one_summary(actual)
    long_fraction = observed["long_trades"] / observed["trades"] if observed["trades"] else 0.5
    fair = simulate(market, outcomes, "random", np.random.default_rng(SEED + 1), count=N_SIMULATIONS)
    balanced = simulate(market, outcomes, "random", np.random.default_rng(SEED + 2), count=N_SIMULATIONS, long_probability=long_fraction)
    long_only = simulate(market, outcomes, "long_only", np.random.default_rng(SEED + 3))
    stress = simulate(market, outcomes, "actual", np.random.default_rng(SEED + 4), signal_directions=directions, extra_cost_multiplier=2.0, keep_trades=True)
    bootstrap = weekly_bootstrap(actual["trades"], start, end, np.random.default_rng(SEED + 5))
    fair_summary = distribution(fair, observed["return_pct"])
    bias_summary = distribution(balanced, observed["return_pct"])
    lower_ci = bootstrap["net_expectancy_R_95pct_interval"][0]
    gates = {"positive_net_return": observed["return_pct"] > 0,
             "above_fair_coin_95th_percentile": observed["return_pct"] > fair_summary["return_pct_quantiles"]["p95"],
             "above_long_bias_control_95th_percentile": observed["return_pct"] > bias_summary["return_pct_quantiles"]["p95"],
             "positive_weekly_bootstrap_lower_bound": lower_ci is not None and lower_ci > 0,
             "positive_after_doubled_additional_costs": float(stress["returns_pct"][0]) > 0,
             "at_least_30_trades": observed["trades"] >= 30}
    report = {"label": args.label, "period_start_inclusive": start, "period_end_exclusive": end,
              "status": "preliminary_gates_passed" if all(gates.values()) else "edge_not_established",
              "initial_balance_usd": INITIAL_BALANCE, "raw_signal_opportunities": len(opportunities),
              "seed": SEED, "simulations_per_random_policy": N_SIMULATIONS,
              "actual_policy_same_engine": observed, "fair_coin_policy": fair_summary,
              "long_bias_control_probability": long_fraction, "long_bias_control_policy": bias_summary,
              "long_only_policy": one_summary(long_only), "doubled_additional_costs": one_summary(stress),
              "weekly_block_bootstrap": bootstrap, "preliminary_gates": gates,
              "funding": {"mode": market.swap_mode, "verified_mode_name": market.swap_name,
                          "calculation": market.funding_description,
                          "weekday_multipliers": market.weekday_ratios.tolist(),
                          "weekday_schedule_exported": market.explicit_weekday_ratios,
                          "limitation": "Static exported rates and midnight broker-server rollover are used; historical rate changes are unavailable.",
                          "reference": SWAP_REFERENCE},
              "costs": {"historical_entry_spread": "native opportunity quote", "exit_spread": "M1 bar snapshot",
                        "roundtrip_commission_usd_per_lot": ROUNDTRIP_COMMISSION,
                        "adverse_slippage_price_per_side_usd": SLIPPAGE_PRICE_PER_SIDE,
                        "total_extra_cost_usd_per_lot": market.extra_per_lot,
                        "stress_multiplier_on_extra_costs": 2.0},
              "execution_dataset": {"type": market.dataset_name, "file": market.data_path.name,
                                    "actual_ask_OHLC": market.actual_ask_ohlc,
                                    "broker_trade_sessions_applied": market.has_trade_sessions,
                                    "partial_session_boundary_minutes": market.partial_boundary_minutes,
                                    "zero_length_session_rows_treated_closed": market.zero_length_sessions,
                                    "period_end": "Forced native-tester settlement at actual last quote, including closed sessions."},
              "source_hashes": {source.name: hashlib.sha256(source.read_bytes()).hexdigest(),
                                market.data_path.name: hashlib.sha256(market.data_path.read_bytes()).hexdigest(),
                                "benchmark.py": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
              "limitations": [
                  "All policies share strategy-conditioned opportunity times. This evaluates directional choices conditional on that timing, not arbitrary timing skill.",
                  "Random trade directions change holding periods and therefore trade counts; every path enforces one position.",
                  "The long-bias control uses the observed executed-trade long proportion as a Bernoulli probability; exact counts are not fixed.",
                  "Separately aggregated bid/ask quote OHLC is used when available; legacy fallback approximates asks from bid bars and spread snapshots.",
                  "Trades cannot enter or touch SL/TP outside broker trade sessions. Partial session-boundary minute OHLC can contain closed-session quotes and remains approximate.",
                  "Time exits wait for the first quoted tradable minute after 72 existing H1 bars. Within-minute ordering and seconds remain approximate, with adverse same-minute SL/TP priority.",
                  "Drawdown is based on closed balances and excludes open-position mark-to-market excursions.",
                  "Native MT5 and same-engine actual-policy results must be compared before interpreting benchmark ranks.",
                  "These results are a historical conditional benchmark, not proof of future profitability or a formal randomized experiment."]}
    report["costs"]["exit_spread"] = "Separate native ask/bid quote OHLC" if market.actual_ask_ohlc else "M1 spread snapshot (legacy approximation)"
    if market.session_path is not None:
        report["source_hashes"][market.session_path.name] = hashlib.sha256(market.session_path.read_bytes()).hexdigest()
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / (args.label + "_benchmark.json")).write_text(json.dumps(report, indent=2, allow_nan=False))
    trade_path = args.out / (args.label + "_modeled_trades.csv")
    if actual["trades"]:
        pd.DataFrame(actual["trades"]).to_csv(trade_path, index=False)
    else:
        trade_path.write_text("entry_time,exit_time,direction,lots,net_usd,net_R\n")
    # Compact distribution arrays support transparent independent plotting and audit.
    distribution_path = args.out / (args.label + "_random_returns.json")
    distribution_path.write_text(json.dumps({"fair_coin_return_pct": fair["returns_pct"].tolist(), "long_bias_control_return_pct": balanced["returns_pct"].tolist()}))
    print(json.dumps({"label": args.label, "status": report["status"], "actual": observed,
                      "fair_coin": fair_summary, "long_bias_control": bias_summary,
                      "weekly_bootstrap": bootstrap, "gates": gates}, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
