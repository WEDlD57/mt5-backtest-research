"""Fixed-plan independent UTC quote-feed stress study; no broker connection.

Run only after data validation and study authorization:
  python independent_study.py --data quotes.csv --plan study_plan.json --out results
Use --validate-only to write coverage/provenance without calculating returns.
The immutable sibling signal and execution modules are checked against the plan.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import benchmark_revision as engine
import gold_signals as signals

MODULE_DIR = Path(__file__).resolve().parent
PRICE_FIELDS = ["open", "high", "low", "close", "ask_open", "ask_high", "ask_low", "ask_close"]
VARIANTS = ("operations_only", "regime_retest")
DATASET_NAME = "HistData actual paired tick quotes aggregated to bid/ask M1; UTC modeled scenario"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_naive(values: pd.Series, name: str) -> pd.Series:
    try:
        result = pd.to_datetime(values, format="mixed", errors="raise")
        if isinstance(result.dtype, pd.DatetimeTZDtype):
            if str(result.dt.tz) != "UTC":
                raise ValueError(f"{name} must already be UTC, not another clock")
            result = result.dt.tz_localize(None)
        elif not pd.api.types.is_datetime64_any_dtype(result.dtype):
            raise ValueError(f"{name} mixes timezone conventions")
    except (TypeError, AttributeError) as error:
        raise ValueError(f"Invalid {name} timestamps") from error
    if result.isna().any():
        raise ValueError(f"Missing {name} timestamps")
    return result


def validate_minutes(frame: pd.DataFrame, point: float = 0.01) -> pd.DataFrame:
    """Validate actual paired OHLC and quote-time bounds; never reconstruct asks."""
    required = {"time", "tick_volume", *PRICE_FIELDS}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError("Missing required actual quote columns: " + ", ".join(missing))
    if frame.empty:
        raise ValueError("Quote input contains no minutes")
    result = frame.copy()
    result["time"] = utc_naive(result["time"], "minute")
    if result["time"].duplicated().any() or not result["time"].is_monotonic_increasing:
        raise ValueError("UTC minutes must be unique and strictly chronological")
    if (result["time"] != result["time"].dt.floor("min")).any():
        raise ValueError("time must identify UTC minute boundaries")
    numbers = result[PRICE_FIELDS].apply(pd.to_numeric, errors="raise").to_numpy(float)
    if not np.isfinite(numbers).all() or (numbers <= 0).any():
        raise ValueError("Actual bid/ask OHLC must be finite and positive")
    result[PRICE_FIELDS] = numbers
    for prefix in ("", "ask_"):
        if (result[prefix + "high"] < result[[prefix + n for n in ("open", "low", "close")]].max(axis=1)).any() or (result[prefix + "low"] > result[[prefix + n for n in ("open", "high", "close")]].min(axis=1)).any():
            raise ValueError("Inconsistent " + (prefix or "bid_") + "OHLC")
    if (result[["ask_" + n for n in ("open", "high", "low", "close")]].to_numpy() + 1e-12 < result[["open", "high", "low", "close"]].to_numpy()).any():
        raise ValueError("Crossed actual bid/ask OHLC")
    volumes = pd.to_numeric(result["tick_volume"], errors="raise").to_numpy(float)
    if not np.isfinite(volumes).all() or (volumes <= 0).any() or (volumes != np.floor(volumes)).any():
        raise ValueError("tick_volume must be a positive integer")
    result["tick_volume"] = volumes.astype(np.int64)
    has_full_pair = {"first_tick_time_utc", "last_tick_time_utc"}.issubset(result.columns)
    if ("first_tick_time_utc" in result) != ("last_tick_time_utc" in result):
        raise ValueError("Both actual UTC tick-time companion columns are required")
    if not has_full_pair and not {"first_tick_time", "last_tick_time"}.issubset(result.columns):
        raise ValueError("Actual first_tick_time and last_tick_time are required")
    full = {}
    for side in ("first", "last"):
        name = side + "_tick_time"
        chosen = name + "_utc" if has_full_pair else name
        value = utc_naive(result[chosen], chosen)
        if ((value < result["time"]) | (value >= result["time"] + pd.Timedelta(minutes=1))).any():
            raise ValueError(chosen + " is outside its UTC minute")
        if has_full_pair and name in result:
            alias = utc_naive(result[name], name)
            if not alias.dt.floor("s").equals(value.dt.floor("s")):
                raise ValueError("Conflicting actual tick-time representations")
        full[side] = value
        result[name + "_actual"] = value
        # The copied MQL-style kernel has whole-second event times. Preserve the
        # precise inputs separately and disclose this quantization in reports.
        result[name] = value.dt.floor("s")
    if (full["first"] > full["last"]).any():
        raise ValueError("Actual first tick occurs after the last tick")
    if not np.isfinite(point) or point <= 0:
        raise ValueError("Invalid declared quote point")
    # Compatibility only: the kernel uses actual ask OHLC, not this column, for
    # fills. This is a calculation from actual paired opening quotes, not an ask model.
    result["spread"] = (result["ask_open"] - result["open"]) / point
    return result


def load_plan(path: Path) -> tuple[dict[str, Any], dict[str, str]]:
    plan = json.loads(Path(path).read_text(encoding="utf-8"))
    if tuple(plan["variants"]) != VARIANTS or plan["primary"] != "operations_only" or plan["secondary"] != "regime_retest":
        raise ValueError("The fixed candidate ordering changed")
    if plan["scenario_clock"] != "UTC" or plan["optimization_permitted"] is not False:
        raise ValueError("This adapter requires the fixed UTC, non-optimized study")
    start, end, warm = [pd.Timestamp(plan[k]) for k in ("evaluation_start_inclusive", "evaluation_end_exclusive", "warmup_start_inclusive")]
    if not warm < start < end or any(t.tz is not None or t != t.normalize() for t in (warm, start, end)):
        raise ValueError("Plan dates must be ordered UTC-naive midnight boundaries")
    specs = plan["virtual_contract"]
    if float(specs["contract_size"]) != 100.0 or int(specs["swap_mode"]) != 4 or specs["currency_profit"] != "USD" or specs["account_currency"] != "USD":
        raise ValueError("Unexpected virtual contract or static USD financing mode")
    hashes = {}
    for key, filename in (("signal_module_sha256", "gold_signals.py"), ("execution_module_sha256", "benchmark_revision.py")):
        actual = sha256_file(MODULE_DIR / filename)
        if actual != plan[key]:
            raise ValueError("Plan module hash mismatch: " + filename)
        hashes[filename] = actual
    return plan, hashes


def configure_engine(plan: dict[str, Any]) -> None:
    knobs = {
        "INITIAL_BALANCE": ("initial_simulated_balance_usd", 100000.0),
        "RISK_FRACTION": ("risk_fraction", 0.0025),
        "ROUNDTRIP_COMMISSION": ("commission_roundtrip_usd_per_lot", 7.0),
        "SLIPPAGE_PRICE_PER_SIDE": ("adverse_slippage_price_per_side", 0.1),
        "MAX_SPREAD_PRICE": ("max_spread_price", 1.0),
        "MAX_SPREAD_TO_STOP": ("max_spread_to_stop", 0.1),
        "MAX_EXTRA_COST_TO_BUDGET": ("max_extra_cost_to_risk_budget", 0.1),
        "N_SIMULATIONS": ("simulations_per_random_policy", 5000),
    }
    for attr, (key, fixed) in knobs.items():
        value = plan[key]
        if float(value) != float(fixed):
            raise ValueError("Unexpected fixed study setting: " + key)
        setattr(engine, attr, int(value) if attr == "N_SIMULATIONS" else float(value))
    if float(plan["stress_cost_multiplier"]) != 2.0:
        raise ValueError("Unexpected cost stress multiplier")
    engine.SEED = int(plan["seed"])


class ObservedQuoteMarket(engine.Market):
    """Copied execution kernel with actual observed whole-second quote bounds."""
    def __init__(self, frame: pd.DataFrame, specs: dict[str, str]):
        if not set(PRICE_FIELDS + ["first_tick_time", "last_tick_time"]).issubset(frame.columns):
            raise ValueError("Actual paired quotes and quote-time bounds are required")
        super().__init__(frame, specs, None, sessions=None, dataset_name=DATASET_NAME)
        self.first_tradable_time = engine.as_seconds(frame["first_tick_time"])
        self.last_tick_times = engine.as_seconds(frame["last_tick_time"])
        self.last_tradable_time = self.last_tick_times.copy()
        self.tradable = self.first_tradable_time <= self.last_tick_times
        self.tradable_indices = np.flatnonzero(self.tradable)
        self.partial_boundary_minutes = int(np.sum((self.first_tradable_time > self.times) | (self.last_tick_times < self.times + 59)))

    def outcome(self, signal: pd.Series, direction: int, period_end: int) -> dict[str, Any]:
        result = super().outcome(signal, direction, period_end)
        names = {"broker_market_closed_at_entry": "no_observed_quote_at_entry_time", "broker_stop_gate": "virtual_stop_distance_gate"}
        if result.get("reason") in names:
            result = {**result, "reason": names[result["reason"]]}
        return result

    def trading_at(self, timestamp: int) -> bool:
        minute = timestamp // 60 * 60
        index = int(np.searchsorted(self.times, minute))
        return bool(index < len(self.times) and self.times[index] == minute and self.first_tradable_time[index] <= timestamp <= self.last_tick_times[index])


def coverage_report(frame: pd.DataFrame, plan: dict[str, Any], output: Path) -> dict[str, Any]:
    """Clock/coverage diagnostics only; missing quotes are never imputed."""
    start, end, warm = [pd.Timestamp(plan[k]) for k in ("evaluation_start_inclusive", "evaluation_end_exclusive", "warmup_start_inclusive")]
    minute_times = frame["time"]
    daily = minute_times.dt.normalize().value_counts().to_dict()
    days = pd.date_range(warm, end - pd.Timedelta(days=1), freq="D")
    day_counts = {day.date().isoformat(): int(daily.get(day, 0)) for day in days}
    hour_starts = pd.date_range(warm, end - pd.Timedelta(hours=1), freq="h")
    hours = frame.groupby(frame["time"].dt.floor("h"), sort=True).agg(quoted_minutes=("time", "size"), first_tick=("first_tick_time_actual", "min"), last_tick=("last_tick_time_actual", "max")).reindex(hour_starts)
    hours.index.name = "utc_hour"
    hours["quoted_minutes"] = hours["quoted_minutes"].fillna(0).astype(int)
    hours.to_csv(output / "coverage_hours.csv", date_format="%Y-%m-%dT%H:%M:%S.%f")
    differences = minute_times.diff().dt.total_seconds().to_numpy()
    gaps = []
    for j in np.flatnonzero(differences > 60):
        missing_start = minute_times.iloc[j - 1] + pd.Timedelta(minutes=1)
        gaps.append({"missing_start_inclusive": missing_start.isoformat(), "next_observed_minute": minute_times.iloc[j].isoformat(), "missing_minutes": int(differences[j] // 60 - 1), "prior_observed_last_tick": frame.iloc[j-1]["last_tick_time_actual"].isoformat(), "next_observed_first_tick": frame.iloc[j]["first_tick_time_actual"].isoformat()})
    evaluation = frame[(minute_times >= start) & (minute_times < end)]
    evaluation_months = pd.period_range(start, end - pd.Timedelta(seconds=1), freq="M")
    month_counts = evaluation["time"].dt.to_period("M").value_counts()
    months_without_quotes = [str(month) for month in evaluation_months if int(month_counts.get(month, 0)) == 0]
    if months_without_quotes:
        raise ValueError("No quotes for declared evaluation months: " + ", ".join(months_without_quotes))
    earlier_hours = frame.loc[minute_times < start, "time"].dt.floor("h").nunique()
    if evaluation.empty or earlier_hours < max(signals.RULES.ema_period + 2, signals.RULES.atr_period + 2):
        raise ValueError("Insufficient evaluation quotes or prior H1 warm-up bars")
    report = {"clock": "UTC; input was already converted, no further EST or broker offset shift applied", "rows": len(frame), "evaluation_rows": len(evaluation), "earlier_existing_H1_bars": int(earlier_hours), "first_minute": minute_times.iloc[0].isoformat(), "last_minute": minute_times.iloc[-1].isoformat(), "first_actual_tick": frame.iloc[0]["first_tick_time_actual"].isoformat(), "last_actual_tick": frame.iloc[-1]["last_tick_time_actual"].isoformat(), "tick_quotes": int(frame["tick_volume"].sum()), "minutes_by_calendar_day": day_counts, "empty_calendar_days": [d for d,n in day_counts.items() if not n], "hours": len(hours), "empty_calendar_hours": int((hours["quoted_minutes"] == 0).sum()), "gap_episodes": gaps, "gap_count": len(gaps), "evaluation_months_without_quotes": months_without_quotes, "unquoted_minutes_before_first_observation": max(0, int((minute_times.iloc[0]-warm).total_seconds()//60)), "unquoted_minutes_after_last_observation": max(0, int((end-minute_times.iloc[-1]).total_seconds()//60)-1), "missing_minutes_inside_observed_span": sum(g["missing_minutes"] for g in gaps), "coverage_hours_file": "coverage_hours.csv", "limitation": "No gap is automatically classified as a market closure or permission restriction. No price or quote is imputed. Intra-minute first/last bounds are observed; kernel event times are floored to seconds, with subsecond ordering unavailable."}
    (output / "coverage.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return report


def quote_grid_diagnostics(frame: pd.DataFrame, specs: dict[str, str]) -> dict[str, Any]:
    """Describe source precision versus protective-order grid without rounding quotes."""
    tick = float(specs["tick_size"])
    off_rows = np.zeros(len(frame), dtype=bool)
    off_cells = 0
    max_distance = 0.0
    by_field = {}
    for name in PRICE_FIELDS:
        values = frame[name].to_numpy(float)
        distance = np.abs(values / tick - np.rint(values / tick))
        off_grid = distance > 1e-7  # Ignore floating-point representation error.
        by_field[name] = int(np.count_nonzero(off_grid))
        off_cells += by_field[name]
        off_rows |= off_grid
        max_distance = max(max_distance, float((distance * tick).max()) if len(values) else 0.0)
    return {"source_quote_prices_preserved": True, "protective_level_tick_size": tick,
            "protective_level_decimal_digits": int(specs["digits"]),
            "OHLC_cells_off_protective_grid": off_cells,
            "minutes_with_any_quote_off_protective_grid": int(np.count_nonzero(off_rows)),
            "off_grid_cells_by_field": by_field,
            "maximum_price_distance_to_protective_grid": max_distance,
            "limitation": "Provider entry/exit quote prices retain decoded precision. Only protective stop/target levels are rounded to the declared order grid. Finer provider quotes are not asserted executable on the original broker."}


def holding_flags(entered: int, exited: int) -> dict[str, Any]:
    midnight_count = max(0, exited // 86400 - entered // 86400)
    weekday = pd.Timestamp(entered, unit="s").dayofweek
    deadline = entered // 86400 * 86400 + (17 if weekday == 4 else 20) * 3600
    return {"crossed_utc_midnights": midnight_count, "overnight": midnight_count > 0, "exit_after_daily_deadline": exited > deadline, "exit_past_daily_deadline_minute": exited >= deadline + 60}


def quote_path_observation(quoted_minutes: np.ndarray, entered: int, exited: int) -> dict[str, int]:
    """Count absent UTC quote minutes across the inclusive holding-minute span.

    The input index is already validated, sorted, unique and minute-aligned.
    Valid executions have observed entry/exit minutes, so absent minutes lie
    strictly between them. Gaps are not classified as closures or feed errors.
    Presence of a quote minute does not establish a complete intraminute path.
    """
    if exited < entered:
        raise ValueError("Exit precedes entry in quote-path diagnostics")
    first = entered // 60 * 60
    last = exited // 60 * 60
    left = int(np.searchsorted(quoted_minutes, first, side="left"))
    right = int(np.searchsorted(quoted_minutes, last, side="right"))
    observed = quoted_minutes[left:right]
    span = (last - first) // 60 + 1
    absent = span - len(observed)
    boundaries = np.concatenate(([first - 60], observed, [last + 60])).astype(np.int64)
    gap_lengths = np.diff(boundaries) // 60 - 1
    if absent < 0 or (gap_lengths < 0).any():
        raise ValueError("Quote-minute index is not unique and chronological")
    return {"quote_minute_span": int(span), "observed_quote_minutes": len(observed),
            "unobserved_quote_minutes": int(absent),
            "max_unobserved_quote_gap_minutes": int(gap_lengths.max())}


def annotate_trade_observation(records: list[dict[str, Any]], quoted_minutes: np.ndarray) -> list[dict[str, Any]]:
    """Add diagnostics to copies; never select, drop or change execution records."""
    return [{**record, **quote_path_observation(
        quoted_minutes, int(pd.Timestamp(record["entry_time"]).timestamp()),
        int(pd.Timestamp(record["exit_time"]).timestamp()))} for record in records]


def study_status(gates: dict[str, bool]) -> str:
    if not gates["all_available_direction_price_paths_observed"]:
        return "inconclusive_unobserved_price_paths"
    return "historical_scenario_gates_passed_research_only" if all(gates.values()) else "edge_not_established"


def holding_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    flags = [holding_flags(int(pd.Timestamp(r["entry_time"]).timestamp()), int(pd.Timestamp(r["exit_time"]).timestamp())) for r in records]
    return {"trades": len(records), "overnight_trades": sum(f["overnight"] for f in flags), "crossed_utc_midnights": sum(f["crossed_utc_midnights"] for f in flags), "exits_after_deadline": sum(f["exit_after_daily_deadline"] for f in flags), "exits_past_deadline_minute": sum(f["exit_past_daily_deadline_minute"] for f in flags), "period_end_forced_settlements": sum(r.get("exit_reason") == "period_end_forced_settlement" for r in records), "funding_usd": sum(float(r.get("funding_usd", 0)) for r in records), "trades_with_unobserved_quote_minutes": sum(int(r.get("unobserved_quote_minutes", 0)) > 0 for r in records), "unobserved_quote_minutes": sum(int(r.get("unobserved_quote_minutes", 0)) for r in records), "max_unobserved_quote_gap_minutes": max((int(r.get("max_unobserved_quote_gap_minutes", 0)) for r in records), default=0)}


def run_variant(frame: pd.DataFrame, market: ObservedQuoteMarket, plan: dict[str, Any], variant: str, output: Path, provenance: dict[str, Any]) -> dict[str, Any]:
    start, end = plan["evaluation_start_inclusive"], plan["evaluation_end_exclusive"]
    opportunities, signal_metadata = signals.generate_signals(frame, start, end, variant, sessions=None)
    opportunities.to_csv(output / f"{variant}_opportunities.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S")
    end_seconds = int(pd.Timestamp(end).timestamp())
    pairs = [(market.outcome(row, 1, end_seconds), market.outcome(row, -1, end_seconds)) for _, row in opportunities.iterrows()]
    directions = opportunities["dir"].to_numpy(int)
    seed = int(plan["seed"])
    actual = engine.simulate(market, pairs, "actual", np.random.default_rng(seed), signal_directions=directions, keep_trades=True)
    observed = engine.one_summary(actual)
    long_fraction = observed["long_trades"] / observed["trades"] if observed["trades"] else .5
    fair = engine.simulate(market, pairs, "random", np.random.default_rng(seed+1), count=engine.N_SIMULATIONS)
    bias = engine.simulate(market, pairs, "random", np.random.default_rng(seed+2), count=engine.N_SIMULATIONS, long_probability=long_fraction)
    long_only = engine.simulate(market, pairs, "long_only", np.random.default_rng(seed+3), keep_trades=True)
    stress = engine.simulate(market, pairs, "actual", np.random.default_rng(seed+4), signal_directions=directions, extra_cost_multiplier=float(plan["stress_cost_multiplier"]), keep_trades=True)
    bootstrap = engine.weekly_bootstrap(actual["trades"], start, end, np.random.default_rng(seed+5))
    fair_summary = engine.distribution(fair, observed["return_pct"])
    bias_summary = engine.distribution(bias, observed["return_pct"])
    lower = bootstrap["net_expectancy_R_95pct_interval"][0]
    gates = {"positive_modeled_after_cost_return": observed["return_pct"] > 0, "above_fair_control_95th_percentile": observed["return_pct"] > fair_summary["return_pct_quantiles"]["p95"], "above_long_bias_control_95th_percentile": observed["return_pct"] > bias_summary["return_pct_quantiles"]["p95"], "positive_weekly_expectancy_lower_bound": lower is not None and lower > 0, "at_least_8_nonempty_weekly_blocks": bootstrap["nonempty_weekly_blocks"] >= 8, "at_least_30_closed_trades": observed["trades"] >= 30, "positive_after_doubled_commission_slippage": float(stress["returns_pct"][0]) > 0}
    # These additions occur after all execution simulations and cannot affect
    # eligibility, chosen directions, costs or returns. Every trade is retained.
    for simulation in (actual, long_only, stress):
        simulation["trades"] = annotate_trade_observation(simulation["trades"], market.times)
    valid_outcomes = []
    invalid = Counter()
    for pair in pairs:
        for outcome in pair:
            if not outcome["valid"]:
                invalid[outcome["reason"]] += 1
                continue
            flags = holding_flags(outcome["entered"], outcome["exited"])
            if not np.isclose(outcome["swap_per_lot"], market.funding(outcome["entered"], outcome["exited"], outcome["direction"]), rtol=0, atol=1e-10):
                raise ValueError("An outcome omitted declared financing")
            observation = quote_path_observation(market.times, outcome["entered"], outcome["exited"])
            valid_outcomes.append({**outcome, **flags, **observation, "entered": engine.iso(outcome["entered"]), "exited": engine.iso(outcome["exited"])})
    gates["all_available_direction_price_paths_observed"] = all(path["unobserved_quote_minutes"] == 0 for path in valid_outcomes)
    holdings = {"actual_executed": holding_summary(actual["trades"]), "long_only_executed": holding_summary(long_only["trades"]), "doubled_cost_executed": holding_summary(stress["trades"]), "all_available_direction_outcomes": {"paths": len(valid_outcomes), "overnight_paths": sum(r["overnight"] for r in valid_outcomes), "paths_past_deadline_minute": sum(r["exit_past_daily_deadline_minute"] for r in valid_outcomes), "invalid_paths_by_reason": dict(invalid), "paths_with_unobserved_quote_minutes": sum(r["unobserved_quote_minutes"] > 0 for r in valid_outcomes), "unobserved_quote_minutes": sum(r["unobserved_quote_minutes"] for r in valid_outcomes), "max_unobserved_quote_gap_minutes": max((r["max_unobserved_quote_gap_minutes"] for r in valid_outcomes), default=0), "aggregation_note": "Unobserved minutes are summed separately across direction paths; overlapping calendar minutes are counted again, not reported as unique global missing minutes."}, "random_control_note": "Per-trajectory holding counts are not stored by the immutable kernel. Every selected direction outcome already includes the same declared financing across all crossed UTC midnights; available-path counts are not executed-control trade counts."}
    report = {"variant": variant, "role": "primary" if variant == plan["primary"] else "secondary_exploratory", "classification": plan["classification"], "status": study_status(gates), "period_start_inclusive": start, "period_end_exclusive": end, "scenario_clock": "UTC", "broker_clock_offset": plan["broker_clock_offset"], "provider": plan["provider"], "provenance": provenance, "fixed_plan": plan, "signal_generation": signal_metadata, "initial_simulated_balance_usd": engine.INITIAL_BALANCE, "raw_signal_opportunities": len(opportunities), "actual_policy_same_engine": observed, "fair_random_direction_control": fair_summary, "long_bias_control_probability": long_fraction, "long_bias_control": bias_summary, "long_only_control": engine.one_summary(long_only), "doubled_commission_slippage": engine.one_summary(stress), "weekly_block_bootstrap": bootstrap, "preliminary_evidence_gates": gates, "holding_diagnostics": holdings, "costs": {"spread": "Actual paired bid/ask opening and exit-side candle prices", "roundtrip_commission_usd_per_lot": engine.ROUNDTRIP_COMMISSION, "adverse_price_slippage_per_side": engine.SLIPPAGE_PRICE_PER_SIDE, "base_total_commission_slippage_per_lot": market.extra_per_lot, "stress_multiplier": plan["stress_cost_multiplier"], "raw_quotes_contain_no_recorded_commission": True}, "financing": {"mode": 4, "units": "Declared static USD per lot, not actual historical provider rates", "long_per_lot": float(market.specs["swap_long"]), "short_per_lot": float(market.specs["swap_short"]), "weekday_multipliers_sunday_first": market.weekday_ratios.tolist(), "rollover_clock": "UTC midnight, charging previous weekday's multiplier", "note": plan["financing_note"]}, "execution": {"price_data": DATASET_NAME, "actual_bid_and_ask_OHLC_required": True, "quoted_minutes_assumed_fillable": True, "broker_session_schedule_used": False, "quote_bounds": "Actual first/last quote times, quantized to whole seconds by the immutable kernel; no fabricated :00/:59 tick endpoints", "period_end": "Forced modeled settlement at the last observed pre-boundary quote, explicitly counted", "coverage_file": "coverage.json", "coverage_hour_file": "coverage_hours.csv"}, "limitations": ["Provider UTC candles and numeric hours are not assumed physically equivalent to the original broker's unknown-offset clock.", "M1 OHLC does not reveal intraminute ordering; same-minute stop/target uses adverse stop priority and target gaps receive no favorable improvement.", "Contract, margin, financing and quoted-minute execution are virtual scenario assumptions, not verified provider executable specifications.", "Random-direction ranks condition on strategy-generated opportunity timing and are not a formal exchangeable experiment or probabilities of future profit.", "Closed-balance drawdown excludes floating equity excursions.", "A secondary favorable result cannot replace the predeclared primary; historical passes require further untouched validation."]}
    report["data_fidelity"] = {
        "gate": "all_available_direction_price_paths_observed",
        "observation_unit": "UTC quote-minute presence over each inclusive holding-minute span",
        "scope": "Every valid long/short direction outcome, including alternatives not executed by the actual policy",
        "failure_status": "inconclusive_unobserved_price_paths",
        "gap_classification": "None: absent quote minutes may reflect market closure, feed gaps or another cause",
        "execution_selection": "All modeled trades and returns retained; coverage diagnostics never filter or change an execution",
        "limitation": "Zero absent minutes is necessary for this gate, not proof of a complete tick path or known intraminute ordering."}
    report["limitations"].append("Unobserved quote minutes cannot establish the intervening price path. Any affected available direction outcome makes the scenario inconclusive regardless of numeric performance gates; no trade is dropped or repriced.")
    report["execution"]["price_precision"] = "Provider entry/exit quotes are retained at decoded precision; only protective levels are rounded to the declared .01 tick/digits=2 grid. No original-broker executability of finer quotes is asserted."
    # Preserve header-only output for a zero-trade or zero-opportunity variant.
    for suffix, simulation in (("modeled_trades", actual), ("long_only_modeled_trades", long_only), ("doubled_cost_modeled_trades", stress)):
        records = simulation["trades"]
        fields = list(records[0]) if records else ["entry_time", "exit_time", "direction", "lots", "net_usd", "net_R", "quote_minute_span", "observed_quote_minutes", "unobserved_quote_minutes", "max_unobserved_quote_gap_minutes"]
        pd.DataFrame(records, columns=fields).to_csv(output / f"{variant}_{suffix}.csv", index=False)
    pd.DataFrame(valid_outcomes, columns=list(valid_outcomes[0]) if valid_outcomes else ["entered", "exited", "direction", "valid"]).to_csv(output / f"{variant}_direction_outcomes.csv", index=False)
    (output / f"{variant}_random_returns.json").write_text(json.dumps({"fair_random_direction_return_pct": fair["returns_pct"].tolist(), "long_bias_return_pct": bias["returns_pct"].tolist()}, allow_nan=False) + "\n")
    (output / f"{variant}_report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return report


def run_study(data: Path, plan_path: Path, output: Path, validate_only: bool = False) -> dict[str, Any]:
    plan, modules = load_plan(plan_path)
    configure_engine(plan)
    raw = pd.read_csv(data, float_precision="round_trip")
    frame = validate_minutes(raw, float(plan["virtual_contract"]["point"]))
    warm, end = pd.Timestamp(plan["warmup_start_inclusive"]), pd.Timestamp(plan["evaluation_end_exclusive"])
    frame = frame[(frame["time"] >= warm) & (frame["time"] < end)].reset_index(drop=True)
    if frame.empty:
        raise ValueError("No quotes inside the declared warm-up/evaluation range")
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    coverage = coverage_report(frame, plan, output)
    provenance = {"input_file": Path(data).name, "input_sha256": sha256_file(data), "plan_file": Path(plan_path).name, "plan_sha256": sha256_file(plan_path), "module_sha256": {**modules, "independent_study.py": sha256_file(Path(__file__))}, "strategy_source_sha256_from_fixed_plan": plan["strategy_source_sha256"], "source_clock_note": plan["source_clock"], "adapter_clock_conversion": "None: canonical input must already be UTC", "actual_quote_time_precision": "Precise companion timestamps validated where present; execution event times floored to whole seconds, matching the signal module/kernel", "quote_price_grid": quote_grid_diagnostics(frame, plan["virtual_contract"]), "coverage_file": "coverage.json", "rows_used": len(frame), "rows_outside_fixed_range": len(raw)-len(frame)}
    (output / "provenance.json").write_text(json.dumps(provenance, indent=2, allow_nan=False) + "\n")
    if validate_only:
        summary = {"status": "validated_without_return_evaluation", "provenance": provenance, "coverage": {"rows": coverage["rows"], "evaluation_rows": coverage["evaluation_rows"], "gap_count": coverage["gap_count"]}}
    else:
        market = ObservedQuoteMarket(frame, plan["virtual_contract"])
        reports = [run_variant(frame, market, plan, variant, output, provenance) for variant in plan["variants"]]
        summary = {"status": "inconclusive_unobserved_price_paths" if any(r["status"] == "inconclusive_unobserved_price_paths" for r in reports) else "independent_historical_scenario_only", "classification": plan["classification"], "provenance": provenance, "variants": [{"variant": r["variant"], "role": r["role"], "status": r["status"], "actual_policy_same_engine": r["actual_policy_same_engine"], "preliminary_evidence_gates": r["preliminary_evidence_gates"]} for r in reports]}
    (output / "study_summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    summary = run_study(args.data, args.plan, args.out, args.validate_only)
    print(json.dumps(summary, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
