#!/usr/bin/env python3
"""Summarize a complete MT5 gold deal journal, using only Python's standard library.

Example:
    python summarize_native.py --deals deals.csv --opportunities opportunities.csv \
        --out results --label development --initial-balance 100000

Times are broker-server timestamps, with no inferred time-zone conversion. Inputs
must contain complete positions, including all entry and exit fills. The USD cost
overlay is the gold study's fixed assumption: commission at least $7/entry lot
round trip and $20/entry lot adverse slippage (a $0.10 move per side at a 100-unit
contract). Stress targets are $14 and $40. This is not a generic instrument model.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
import math
from pathlib import Path
import re
import statistics
from typing import Any


ZERO = Decimal("0")
TRADE_FIELDS = (
    "entry_time", "exit_time", "direction", "lots", "gross_profit_usd",
    "swap_usd", "native_commission_and_fee_usd", "native_net_usd",
    "additional_cost_usd", "adjusted_net_usd", "doubled_additional_cost_net_usd",
    "planned_stop_risk_usd", "adjusted_net_R", "effective_contract_from_deals",
)
COST_MODEL = (
    "Native fees retained; commission topped up to at least USD7/lot roundtrip, "
    "plus USD20/lot adverse slippage. Stress targets USD14 commission plus "
    "USD40 slippage, without double-counting native fees. Assumes USD gold "
    "and a 100-unit contract for the fixed slippage allowance."
)
LIMITATION = (
    "Additional costs are journal overlays; native position sizing used "
    "broker-reported account equity before these extra overlays. Closed-balance "
    "drawdown uses completed positions and excludes open-position excursions. "
    "Planned stop risk is matched only to an exact entry timestamp."
)


@dataclass(frozen=True)
class Deal:
    time: datetime
    side: str
    entry: str
    volume: Decimal
    price: Decimal
    profit: Decimal
    swap: Decimal
    commission: Decimal
    fee: Decimal
    position: str
    row_number: int


@dataclass(frozen=True)
class Opportunity:
    risk_per_lot: Decimal
    stop_distance: Decimal | None


def _number(value: str | Decimal, context: str) -> Decimal:
    try:
        number = Decimal(value)
        valid = number.is_finite() and math.isfinite(float(number))
    except (InvalidOperation, TypeError, ValueError, OverflowError):
        valid = False
    if not valid:
        raise ValueError(f"{context}: expected a finite number")
    return number


def _time(value: str, context: str) -> datetime:
    for fmt in ("%Y.%m.%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    raise ValueError(f"{context}: expected a broker-server timestamp with seconds")


def _rows(path: Path, required: set[str]):
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames
        if fields is None or len(fields) != len(set(fields)):
            raise ValueError("CSV requires a header with unique column names")
        missing = required - set(fields)
        if missing:
            raise ValueError("CSV missing required columns: " + ", ".join(sorted(missing)))
        for row_number, row in enumerate(reader, 2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"CSV row {row_number}: inconsistent column count")
            yield row_number, {name: value.strip() for name, value in row.items()}


def read_deals(path: Path) -> list[Deal]:
    required = {"time", "type", "entry", "volume", "price", "profit", "swap",
                "commission", "positionid"}
    deals = []
    deal_ids: set[str] = set()
    for row_number, row in _rows(path, required):
        context = f"Deal row {row_number}"
        entry = row["entry"].lower()
        if entry == "inout":
            raise ValueError(f"{context}: inout reversals are unsupported; use separate entry/exit deals")
        if entry not in {"in", "out", "out_by"}:
            raise ValueError(f"{context}: unsupported deal entry kind")
        side = row["type"].lower()
        if side not in {"buy", "sell"}:
            raise ValueError(f"{context}: expected a buy or sell deal")
        position = row["positionid"]
        if not re.fullmatch(r"[0-9]+", position) or int(position) <= 0:
            raise ValueError(f"{context}: expected a positive position identifier")
        position = str(int(position))
        deal_id = row.get("dealid", "")
        if deal_id:
            if not re.fullmatch(r"[0-9]+", deal_id) or int(deal_id) <= 0:
                raise ValueError(f"{context}: expected a positive deal identifier")
            deal_id = str(int(deal_id))
            if deal_id in deal_ids:
                raise ValueError(f"{context}: duplicate deal identifier")
            deal_ids.add(deal_id)
        amounts = {name: _number(row[name], f"{context} {name}")
                   for name in ("volume", "price", "profit", "swap", "commission")}
        if amounts["volume"] <= ZERO or amounts["price"] <= ZERO:
            raise ValueError(f"{context}: volume and price must be positive")
        deals.append(Deal(
            time=_time(row["time"], context), side=side, entry=entry,
            fee=_number(row.get("fee", "0"), f"{context} fee"),
            position=position, row_number=row_number, **amounts,
        ))
    return deals


def read_opportunities(path: Path) -> dict[datetime, Opportunity]:
    opportunities = {}
    for row_number, row in _rows(path, {"time", "one_lot_stop_loss_usd"}):
        context = f"Opportunity row {row_number}"
        timestamp = _time(row["time"], context)
        if timestamp in opportunities:
            raise ValueError(f"{context}: duplicate opportunity timestamp makes risk matching ambiguous")
        risk = _number(row["one_lot_stop_loss_usd"], context)
        distance_text = row.get("SLdistance", "")
        distance = _number(distance_text, context) if distance_text else None
        if risk < ZERO or (distance is not None and distance < ZERO):
            raise ValueError(f"{context}: stop risk and distance cannot be negative")
        opportunities[timestamp] = Opportunity(risk, distance)
    return opportunities


def _complete_position(rows: list[Deal]) -> tuple[list[Deal], list[Deal]]:
    """Reject truncated, duplicated, reversed, or otherwise unbalanced positions."""
    rows.sort(key=lambda row: (row.time, row.row_number))
    entries, exits = [], []
    outstanding = ZERO
    entry_side = None
    closed = False
    for row in rows:
        context = f"Position journal at deal row {row.row_number}"
        if closed:
            raise ValueError(f"{context}: position identifier reused after complete closure")
        if row.entry == "in":
            if entry_side is None:
                entry_side = row.side
            if row.side != entry_side:
                raise ValueError(f"{context}: mixed entry sides require reversal accounting")
            entries.append(row)
            outstanding += row.volume
        else:
            if not entries:
                raise ValueError(f"{context}: exit before entry; incomplete native position journal")
            if row.side == entry_side:
                raise ValueError(f"{context}: exit must have the opposite side to the entry")
            if row.volume > outstanding:
                raise ValueError(f"{context}: exit volume exceeds outstanding entry volume")
            outstanding -= row.volume
            exits.append(row)
            closed = outstanding == ZERO
    if not entries or not exits or outstanding != ZERO:
        raise ValueError("Incomplete native position journal: entry and exit volumes must balance")
    return entries, exits


def _median(values: list[Decimal]) -> float | None:
    return float(statistics.median(values)) if values else None


def _serialize_trade(trade: dict[str, Any]) -> dict[str, Any]:
    return {name: float(value) if isinstance(value, Decimal) else value
            for name, value in trade.items()}


def summarize(deals_path: Path, opportunities_path: Path, label: str,
              initial_balance: Decimal | str | int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return summary and public trade rows; fail before writing on invalid journals."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", label):
        raise ValueError("Label must be 1-80 letters, digits, dots, underscores or hyphens; start with a letter/digit")
    initial = _number(str(initial_balance), "Initial balance")
    if initial <= ZERO:
        raise ValueError("Initial balance must be positive")
    deals = read_deals(Path(deals_path))
    opportunities = read_opportunities(Path(opportunities_path))
    positions: dict[str, list[Deal]] = {}
    for deal in deals:
        positions.setdefault(deal.position, []).append(deal)
    trades = []
    for rows in positions.values():
        entries, exits = _complete_position(rows)
        volume = sum((row.volume for row in entries), ZERO)
        profit = sum((row.profit for row in rows), ZERO)
        swap = sum((row.swap for row in rows), ZERO)
        commission_and_fee = sum((row.commission + row.fee for row in rows), ZERO)
        native_net = profit + swap + commission_and_fee
        # Native P/L already includes the fees. Only top up the declared targets.
        actual_fee = max(-commission_and_fee, ZERO)
        extra = max(Decimal("7") * volume - actual_fee, ZERO) + Decimal("20") * volume
        stress_extra = max(Decimal("14") * volume - actual_fee, ZERO) + Decimal("40") * volume
        direction = 1 if entries[0].side == "buy" else -1
        average_entry = sum((row.price * row.volume for row in entries), ZERO) / volume
        average_exit = sum((row.price * row.volume for row in exits), ZERO) / volume
        price_pnl = direction * (average_exit - average_entry) * volume
        contract = profit / price_pnl if abs(price_pnl) > Decimal("1e-8") else None
        # Match every entry fill exactly; never borrow a nearby signal's risk.
        matched = [opportunities.get(row.time) for row in entries]
        risk = (sum((opp.risk_per_lot * row.volume for opp, row in zip(matched, entries)), ZERO)
                if all(opp is not None and opp.risk_per_lot > ZERO for opp in matched) else None)
        trades.append({
            "entry_time": entries[0].time.isoformat(), "exit_time": exits[-1].time.isoformat(),
            "direction": direction, "lots": volume, "gross_profit_usd": profit,
            "swap_usd": swap, "native_commission_and_fee_usd": commission_and_fee,
            "native_net_usd": native_net, "additional_cost_usd": extra,
            "adjusted_net_usd": native_net - extra,
            "doubled_additional_cost_net_usd": native_net - stress_extra,
            "planned_stop_risk_usd": risk,
            "adjusted_net_R": (native_net - extra) / risk if risk else None,
            "effective_contract_from_deals": contract,
        })
    trades.sort(key=lambda row: row["exit_time"])
    net = sum((row["adjusted_net_usd"] for row in trades), ZERO)
    stress_net = sum((row["doubled_additional_cost_net_usd"] for row in trades), ZERO)
    balance = peak = initial
    drawdown = ZERO
    for trade in trades:
        balance += trade["adjusted_net_usd"]
        peak = max(peak, balance)
        drawdown = max(drawdown, (peak - balance) / peak * 100)
    wins = sum(row["adjusted_net_usd"] > ZERO for row in trades)
    risk_factors = [opp.risk_per_lot / opp.stop_distance for opp in opportunities.values()
                    if opp.stop_distance is not None and opp.stop_distance > ZERO]
    contracts = [row["effective_contract_from_deals"] for row in trades
                 if row["effective_contract_from_deals"] is not None]
    result = {
        "label": label,
        "native_trades": len(trades),
        "native_wins_after_added_costs": wins,
        "net_before_additional_costs_usd": float(sum((row["native_net_usd"] for row in trades), ZERO)),
        "additional_cost_usd": float(sum((row["additional_cost_usd"] for row in trades), ZERO)),
        "adjusted_net_usd": float(net),
        "adjusted_return_pct": float(net / initial * 100),
        "adjusted_win_rate_pct": 100 * wins / len(trades) if trades else None,
        "adjusted_closed_balance_max_drawdown_pct": float(drawdown),
        "doubled_additional_cost_return_pct": float(stress_net / initial * 100),
        "median_native_risk_usd_per_price_unit_per_lot": _median(risk_factors),
        "median_contract_from_native_deals": _median(contracts),
        "native_swap_usd": float(sum((row["swap_usd"] for row in trades), ZERO)),
        "initial_simulated_balance_usd": float(initial),
        "trades_without_matched_planned_risk": sum(row["planned_stop_risk_usd"] is None for row in trades),
        "journal_validation": "complete positions; balanced entry/exit volume; no inout reversals",
        "status": "complete" if trades else "no_trades",
        "extra_cost_model": COST_MODEL,
        "limitation": LIMITATION,
    }
    return result, [_serialize_trade(trade) for trade in trades]


def analyze(deals: Path, opportunities: Path, out: Path, label: str,
            initial_balance: Decimal | str | int) -> dict[str, Any]:
    result, trades = summarize(deals, opportunities, label, initial_balance)
    # Validate JSON before creating output files. Never copy arbitrary input columns.
    encoded = json.dumps(result, indent=2, allow_nan=False) + "\n"
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{label}_native.json").write_text(encoded, encoding="utf-8")
    with (out / f"{label}_native_adjusted_trades.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=TRADE_FIELDS)
        writer.writeheader()
        writer.writerows(trades)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deals", type=Path, required=True, help="Complete native MT5 deal CSV")
    parser.add_argument("--opportunities", type=Path, required=True, help="Matching opportunity CSV")
    parser.add_argument("--out", type=Path, required=True, help="Output directory")
    parser.add_argument("--label", required=True, help="Portable result filename prefix")
    parser.add_argument("--initial-balance", required=True, help="Actual simulated starting balance in USD")
    args = parser.parse_args(argv)
    try:
        result = analyze(args.deals, args.opportunities, args.out, args.label, args.initial_balance)
    except (ValueError, OSError, csv.Error) as error:
        parser.exit(2, f"Cannot summarize journal: {error}\n")
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
