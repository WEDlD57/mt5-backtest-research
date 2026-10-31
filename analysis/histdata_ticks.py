"""Convert user-supplied HistData XAUUSD monthly tick ZIPs into paired M1 OHLC.

Requires Python 3.10+, pandas and numpy. This module performs no network access.
Only supply local archives you are entitled to use; a reproducible converter does
not grant permission to redistribute the provider's continuous price history.

HistData declares fixed EST (UTC-05:00), including summer. We therefore add
exactly five hours, without inferring DST. The physical UTC clock is not
independently verified. Entire supplied months pass validation before UTC clipping
or replacement of the output CSV. Equal-time quotes retain their original order;
clock reversals are rejected, never sorted or repaired. Missing quotes/minutes
are not filled. Choose the input months using the separately retained source
quality audit, before examining trading outcomes.

Example (repeat --zip or supply several paths after it)::

    python histdata_ticks.py --zip XAUUSD_T_202211.zip XAUUSD_T_202212.zip \
        --from 2022-11-01 --until 2023-01-01 --out minutes.csv --report audit.json
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import zipfile
import zlib

import numpy as np
import pandas as pd


COLUMNS = [
    "time", "open", "high", "low", "close", "ask_open", "ask_high",
    "ask_low", "ask_close", "tick_volume", "spread", "last_tick_time",
    "first_tick_time", "last_tick_time_utc", "first_tick_time_utc",
    "spread_price_min", "spread_price_max", "spread_price_open",
]
CSV_MEMBER = re.compile(r"DAT_ASCII_XAUUSD_T_(\d{4})(\d{2})\.csv\Z")
STAMP = re.compile(r"[0-9]{8} [0-9]{9}\Z")
VIRTUAL_POINT = 0.01
SOURCE_TIMEZONE = "Provider-declared fixed EST (UTC-05:00), year-round; add exactly 5 hours"
MINUTE_AGG = {
    "open": "first", "high": "max", "low": "min", "close": "last",
    "ask_open": "first", "ask_high": "max", "ask_low": "min", "ask_close": "last",
    "tick_volume": "sum", "spread_price_min": "min", "spread_price_max": "max",
    "spread_price_open": "first", "first_tick": "min", "last_tick": "max",
}


class DataQualityError(ValueError):
    """A supplied archive or its unmodified quote stream failed validation."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _iso(value) -> str:
    return pd.Timestamp(value).isoformat() + "Z"


def _utc_bound(value: str | None, name: str):
    if value is None:
        return None
    try:
        stamp = pd.Timestamp(value)
        if pd.isna(stamp):
            raise ValueError("missing timestamp")
        if stamp.tzinfo is not None:
            stamp = stamp.tz_convert("UTC").tz_localize(None)
        if stamp != stamp.floor("min"):
            raise ValueError("boundary is not minute-aligned")
        return stamp
    except (ValueError, TypeError, OverflowError) as exc:
        raise DataQualityError(f"{name} must be a minute-aligned UTC date/timestamp") from exc


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n",
                                         dir=path.parent, prefix=".histdata-report-",
                                         suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _describe_archive(path: Path) -> dict:
    record = {"archive": path.name, "status": "not_validated"}
    try:
        record.update({"sha256": sha256(path), "compressed_bytes": path.stat().st_size})
        with zipfile.ZipFile(path) as archive:
            members = [item for item in archive.infolist()
                       if item.filename.lower().endswith(".csv")]
            if len(members) != 1:
                raise DataQualityError(f"{path.name}: expected exactly one monthly XAUUSD CSV member")
            member = members[0]
            match = CSV_MEMBER.fullmatch(member.filename)
            if match is None or not 1 <= int(match[2]) <= 12:
                raise DataQualityError(f"{path.name}: unsupported symbol, month or CSV member name")
            if member.flag_bits & 1:
                raise DataQualityError(f"{path.name}: encrypted members are unsupported")
            record.update({"csv_member": member.filename,
                           "source_month_est": f"{match[1]}-{match[2]}",
                           "raw_csv_uncompressed_bytes": member.file_size})
    except DataQualityError:
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise DataQualityError(f"{path.name}: cannot read a valid local ZIP archive") from exc
    return record


def _chunks(stream, chunk_size: int, archive_name: str):
    """Use csv.reader to check every row's width, including chunk boundaries.

    pandas' C CSV parser can silently discard an extra field on a later row when
    chunks are small, even with on_bad_lines='error'. Validate widths explicitly.
    """
    reader = csv.reader(stream, strict=True)
    batch = []
    try:
        for row_number, row in enumerate(reader, 1):
            if len(row) != 4:
                raise DataQualityError(f"{archive_name}: row {row_number} must contain exactly 4 fields")
            batch.append(row)
            if len(batch) == chunk_size:
                yield batch
                batch = []
        if batch:
            yield batch
    except (csv.Error, UnicodeError) as exc:
        raise DataQualityError(f"{archive_name}: malformed ASCII CSV") from exc


def _validate_minutes(frame: pd.DataFrame) -> None:
    if frame.empty:
        raise DataQualityError("No observed minute bars remain in the requested UTC clip")
    if not frame.index.is_unique or not frame.index.is_monotonic_increasing:
        raise DataQualityError("Combined minute index is duplicated or not chronological")
    numeric = frame[list(MINUTE_AGG)[:-2]].to_numpy(dtype=float)
    if not np.isfinite(numeric).all():
        raise DataQualityError("Aggregated minute values contain nonfinite numbers")
    for prefix in ("", "ask_"):
        o, h, low, c = [frame[prefix + field] for field in ("open", "high", "low", "close")]
        if not ((low > 0) & (h >= low) & (o >= low) & (o <= h) & (c >= low) & (c <= h)).all():
            raise DataQualityError("Aggregated bid/ask OHLC bounds are invalid")
    if not (frame["ask_open"] >= frame["open"]).all() or not (frame["ask_close"] >= frame["close"]).all():
        raise DataQualityError("Aggregated first/last quotes are crossed")
    if not ((frame["tick_volume"] >= 1) & (frame["spread_price_min"] >= 0)).all():
        raise DataQualityError("Minute quote counts or spreads are invalid")
    for name in ("first_tick", "last_tick"):
        if not ((frame[name] >= frame.index) &
                (frame[name] < frame.index + pd.Timedelta(minutes=1))).all():
            raise DataQualityError("Actual tick timestamps lie outside their observed minute")
    if not (frame["first_tick"] <= frame["last_tick"]).all():
        raise DataQualityError("Actual first/last tick bounds are reversed")


def _aggregate_archive(path: Path, record: dict, chunk_size: int) -> pd.DataFrame:
    parts = []
    previous = None
    month = record["source_month_est"].replace("-", "")
    record.update({"status": "validating", "tick_rows_read": 0,
                   "equal_timestamp_pairs_preserved": 0, "invalid_price_rows": 0,
                   "crossed_quote_rows": 0, "source_month_mismatch_rows": 0,
                   "out_of_order_rows": 0})
    try:
        with zipfile.ZipFile(path) as archive, archive.open(record["csv_member"]) as binary:
            with io.TextIOWrapper(binary, encoding="ascii", newline="") as text:
                for rows in _chunks(text, chunk_size, path.name):
                    offset = record["tick_rows_read"]
                    record["tick_rows_read"] += len(rows)
                    chunk = pd.DataFrame(rows, columns=["stamp", "bid", "ask", "unused_volume"])
                    pattern = chunk["stamp"].map(lambda value: STAMP.fullmatch(value) is not None)
                    if not pattern.all():
                        raise DataQualityError(f"{path.name}: malformed source millisecond timestamp")
                    # strptime implementations can reinterpret overlong clock
                    # components. Check the fixed-width source fields ourselves.
                    if ((chunk["stamp"].str[9:11].astype(int) > 23) |
                        (chunk["stamp"].str[11:13].astype(int) > 59) |
                        (chunk["stamp"].str[13:15].astype(int) > 59)).any():
                        raise DataQualityError(f"{path.name}: invalid source clock component")
                    mismatch = ~chunk["stamp"].str.startswith(month)
                    record["source_month_mismatch_rows"] += int(mismatch.sum())
                    if mismatch.any():
                        raise DataQualityError(f"{path.name}: quote date does not match the CSV source month")
                    try:
                        times = pd.to_datetime(chunk["stamp"], format="%Y%m%d %H%M%S%f", errors="raise")
                        times = times + pd.Timedelta(hours=5)
                    except (ValueError, OverflowError) as exc:
                        raise DataQualityError(f"{path.name}: invalid source calendar timestamp") from exc
                    values = times.to_numpy(dtype="datetime64[ns]").astype("int64")
                    if "first_tick_utc" not in record:
                        record["first_tick_utc"] = _iso(times.iloc[0])
                    record["last_tick_read_utc"] = _iso(times.iloc[-1])
                    combined = np.r_[previous, values] if previous is not None else values
                    differences = np.diff(combined)
                    record["equal_timestamp_pairs_preserved"] += int((differences == 0).sum())
                    backward = np.flatnonzero(differences < 0)
                    record["out_of_order_rows"] += len(backward)
                    if len(backward):
                        i = int(backward[0])
                        record["first_backstep"] = {
                            "previous_utc": _iso(pd.Timestamp(int(combined[i]))),
                            "next_utc": _iso(pd.Timestamp(int(combined[i + 1]))),
                            "seconds": float(differences[i] / 1e9),
                            "raw_row_number": offset + i + (1 if previous is not None else 2),
                        }
                        raise DataQualityError(f"{path.name}: raw quote clock moves backward; no clock repair is permitted")
                    previous = int(values[-1])
                    try:
                        prices = np.asarray(chunk[["bid", "ask"]], dtype=float)
                        volumes = np.asarray(chunk["unused_volume"], dtype=float)
                    except (ValueError, TypeError, OverflowError) as exc:
                        raise DataQualityError(f"{path.name}: nonnumeric quote or source-volume field") from exc
                    with np.errstate(over="ignore", invalid="ignore"):
                        spreads = prices[:, 1] - prices[:, 0]
                    invalid = ~np.isfinite(prices).all(axis=1) | (prices <= 0).any(axis=1) | ~np.isfinite(spreads)
                    crossed = prices[:, 1] < prices[:, 0]
                    record["invalid_price_rows"] += int(invalid.sum())
                    record["crossed_quote_rows"] += int(crossed.sum())
                    if invalid.any() or crossed.any():
                        raise DataQualityError(f"{path.name}: invalid/nonpositive/nonfinite or crossed bid/ask quote")
                    if not (np.isfinite(volumes) & (volumes >= 0)).all():
                        raise DataQualityError(f"{path.name}: invalid source-volume field")
                    chunk["bid"], chunk["ask"] = prices[:, 0], prices[:, 1]
                    chunk["time"] = times
                    chunk["minute"] = times.dt.floor("min")
                    chunk["spread_price"] = spreads
                    parts.append(chunk.groupby("minute", sort=False).agg(
                        open=("bid", "first"), high=("bid", "max"), low=("bid", "min"), close=("bid", "last"),
                        ask_open=("ask", "first"), ask_high=("ask", "max"), ask_low=("ask", "min"), ask_close=("ask", "last"),
                        tick_volume=("bid", "size"), spread_price_min=("spread_price", "min"),
                        spread_price_max=("spread_price", "max"), spread_price_open=("spread_price", "first"),
                        first_tick=("time", "first"), last_tick=("time", "last"),
                    ))
        if not parts:
            raise DataQualityError(f"{path.name}: empty source quote file")
        if sha256(path) != record["sha256"]:
            raise DataQualityError(f"{path.name}: archive changed during conversion; input fingerprint is unstable")
        # Only combine already chronological chunk aggregates. No raw-clock sorting.
        frame = pd.concat(parts).groupby(level=0, sort=False).agg(MINUTE_AGG)
        _validate_minutes(frame)
        record.update({"status": "validated", "minute_rows_before_clip": len(frame),
                       "csv_read_to_eof_crc_checked": True, "zip_sha256_rechecked_after_read": True})
        return frame
    except DataQualityError:
        record["status"] = "rejected"
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError, UnicodeError, EOFError, zlib.error) as exc:
        record["status"] = "rejected"
        raise DataQualityError(f"{path.name}: source member read or ZIP integrity failure") from exc


def convert_archives(zip_paths, out, report, *, start=None, until=None,
                     chunk_size: int = 500_000) -> dict:
    """Validate complete local archives, then atomically replace a clipped CSV.

    Any validation error raises DataQualityError and writes a rejection report.
    A pre-existing output CSV remains untouched. Input paths and private parent
    directories are omitted from the report; basenames and SHA-256 identify ZIPs.
    Date-only/naive clip boundaries mean UTC; timezone-aware ones convert to UTC.
    The complete CSV and JSON report are replaced individually, not as one joint
    transaction. An I/O failure while writing the report can leave the new,
    completely validated CSV in place; consult output_csv_replaced if recorded.
    """
    paths = [Path(value) for value in zip_paths]
    out, report = Path(out), Path(report)
    reserved = [path.resolve() for path in paths]
    if out.resolve() == report.resolve() or out.resolve() in reserved or report.resolve() in reserved:
        raise DataQualityError("Output/report paths must be distinct from each other and all input ZIPs")
    audit = {
        "schema_version": 1, "status": "validating", "provider": "HistData.com Generic ASCII XAUUSD tick files",
        "provider_format": "https://www.histdata.com/f-a-q/data-files-detailed-specification/",
        "provider_timezone_faq": "https://www.histdata.com/f-a-q/",
        "source_timezone_assumption": SOURCE_TIMEZONE,
        "physical_utc_clock_independently_verified": False,
        "output_timezone": "UTC", "input_month_ordering": "Source month ascending; raw quotes never sorted",
        "selection": "Caller-selected complete local monthly ZIPs; retain the separate source quality audit and study plan",
        "full_calendar_year_readiness": "Not established by this conversion; prior failed full-year audits remain failed",
        "validation_scope": "Every raw quote in every supplied ZIP is checked before any UTC clipping or CSV replacement",
        "equal_time_quotes": "Preserved in original source order, including across chunk boundaries",
        "quote_or_clock_imputation": False, "tick_volume": "Observed quote row count; zero source volume does not discard a quote",
        "spread": "Minimum actual ask-minus-bid / 0.01 virtual point; not a provider tradable-tick-size claim",
        "spread_price_columns": "Actual ask-minus-bid in price units, preserving min/max/open for each observed minute",
        "float_serialization": "Round-trip floating point text; bid/ask source prices are not rescaled",
        "timestamp_columns": "time=UTC minute; first/last_tick_time=actual UTC quote seconds; *_utc retains milliseconds",
        "limitations": ["Provider-declared fixed EST conversion is an assumption, not an independently verified physical UTC clock.",
                        "Missing intervals remain absent; gaps do not establish the expected trading calendar.",
                        "Minute OHLC cannot reconstruct intraminute bid/ask sequence or execution paths.",
                        "Conversion grants no right to redistribute continuous raw or aggregated provider prices."],
        "runtime": {"python": sys.version.split()[0], "pandas": pd.__version__, "numpy": np.__version__},
        "archives": [],
    }
    temporary = None
    output_replaced = False
    try:
        if not paths or chunk_size < 1:
            raise DataQualityError("Supply at least one ZIP and a positive chunk size")
        if len(set(reserved)) != len(reserved):
            raise DataQualityError("The same input ZIP was supplied more than once")
        lower, upper = _utc_bound(start, "--from"), _utc_bound(until, "--until")
        if lower is not None and upper is not None and lower >= upper:
            raise DataQualityError("--from must precede exclusive --until")
        audit["clip_start_utc_inclusive"] = _iso(lower) if lower is not None else None
        audit["clip_end_utc_exclusive"] = _iso(upper) if upper is not None else None
        described = []
        for path in paths:
            record = _describe_archive(path)
            described.append((record["source_month_est"], path, record))
            audit["archives"].append(record)
        months = [month for month, _, _ in described]
        if len(set(months)) != len(months):
            raise DataQualityError("Two supplied archives contain the same source month; no deduplication is permitted")
        described.sort(key=lambda item: item[0])
        audit["archives"] = [record for _, _, record in described]
        frames = [_aggregate_archive(path, record, chunk_size) for _, path, record in described]
        frame = pd.concat(frames)
        _validate_minutes(frame)
        audit["raw_quote_rows_validated"] = sum(record["tick_rows_read"] for record in audit["archives"])
        audit["minute_rows_before_clip"] = len(frame)
        if lower is not None:
            frame = frame.loc[frame.index >= lower]
        if upper is not None:
            frame = frame.loc[frame.index < upper]
        _validate_minutes(frame)
        frame = frame.copy()
        frame["spread"] = frame["spread_price_min"] / VIRTUAL_POINT
        frame["time"] = frame.index.strftime("%Y.%m.%d %H:%M")
        for side in ("first", "last"):
            frame[f"{side}_tick_time"] = frame[f"{side}_tick"].dt.strftime("%Y.%m.%d %H:%M:%S")
            frame[f"{side}_tick_time_utc"] = frame[f"{side}_tick"].dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        differences = frame.index.to_series().diff().dt.total_seconds()
        gaps = []
        for index in np.flatnonzero((differences > 60).to_numpy()):
            gaps.append({"previous_minute_utc": _iso(frame.index[index - 1]),
                         "next_minute_utc": _iso(frame.index[index]),
                         "missing_minutes": int(differences.iloc[index] / 60) - 1})
        day = frame.groupby(frame.index.strftime("%Y-%m-%d")).agg(
            minute_rows=("tick_volume", "size"), quote_rows=("tick_volume", "sum"))
        audit.update({
            "status": "validated", "output_csv": out.name, "minute_rows": len(frame),
            "quote_rows_in_output_minutes": int(frame["tick_volume"].sum()),
            "first_minute_utc": _iso(frame.index[0]), "last_minute_utc": _iso(frame.index[-1]),
            "first_actual_tick_utc": _iso(frame["first_tick"].iloc[0]),
            "last_actual_tick_utc": _iso(frame["last_tick"].iloc[-1]),
            "duplicate_minute_indices": 0, "paired_actual_bid_ask_index": True,
            "actual_tick_bounds_valid": True, "imputed_quotes_or_minutes": 0,
            "observed_minute_gaps": gaps,
            "coverage_by_utc_day": {str(key): {name: int(value) for name, value in row.items()}
                                    for key, row in day.to_dict("index").items()},
        })
        out.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="",
                                         dir=out.parent, prefix=".histdata-minutes-",
                                         suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            frame[COLUMNS].to_csv(stream, index=False)
        audit["output_bytes"] = temporary.stat().st_size
        audit["output_sha256"] = sha256(temporary)
        os.replace(temporary, out)
        output_replaced = True
        audit["output_csv_replaced"] = True
        _write_json(report, audit)
        return audit
    except Exception as exc:
        audit["status"] = "rejected"
        audit["output_csv_replaced"] = output_replaced
        audit["error_type"] = type(exc).__name__
        # Controlled quality messages contain only basenames, never private paths.
        audit["error"] = str(exc) if isinstance(exc, DataQualityError) else "Conversion failed during validation or output commit"
        _write_json(report, audit)
        raise
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--zip", action="append", nargs="+", required=True, dest="archives", metavar="LOCAL_ZIP")
    parser.add_argument("--out", required=True, help="Output paired M1 CSV (replaced only after validation)")
    parser.add_argument("--report", required=True, help="Validation/report JSON, including rejection details")
    parser.add_argument("--from", dest="start", help="Inclusive minute-aligned UTC boundary (date-only means UTC)")
    parser.add_argument("--until", help="Exclusive minute-aligned UTC boundary")
    parser.add_argument("--chunk-size", type=int, default=500_000, help="Raw quote rows per bounded-memory aggregation chunk")
    args = parser.parse_args(argv)
    try:
        audit = convert_archives([path for group in args.archives for path in group], args.out, args.report,
                                 start=args.start, until=args.until, chunk_size=args.chunk_size)
    except Exception as exc:
        message = str(exc) if isinstance(exc, DataQualityError) else type(exc).__name__
        print("REJECTED: " + message, file=sys.stderr)
        return 2
    print(json.dumps({"status": audit["status"], "minute_rows": audit["minute_rows"],
                      "output_csv": audit["output_csv"], "output_sha256": audit["output_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
