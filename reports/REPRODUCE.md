# Reproducing the research

## Native MT5 runs

Compile the `.mq5` programs in MetaEditor using the standard platform headers. Every EA is locked to the Strategy Tester. Compile from source; no compiled binaries, saved logins or terminal settings are included.

Select XAUUSD, H1, USD simulated account currency, USD 100,000 deposit, leverage 1:100, and “Every tick based on real ticks.” Turn optimization off. Test each date window separately with a reset balance:

| Label | From inclusive | To exclusive |
|---|---|---|
| development | 2026.01.13 | 2026.07.01 |
| validation / validation_seen | 2026.07.01 | 2026.08.15 |
| contextual / context_seen | 2026.08.17 | 2026.10.24 |

Use all source defaults. For the revision, load each of the two presets independently. Hours are broker-server time. The entry window is 07:00–19:30, with Friday cutoff 16:30; H1 evaluations mean the last regular hourly opportunity is 19:00 or Friday 16:00. Close on the first available tradable tick at/after 20:00 or Friday 17:00. Exported common-file journals must be copied immediately after each run because the next run overwrites the common filenames; prefix each file with its run label.

Different broker symbols, data, spreads, trading hours, commissions and historical financing can change the results. The native tests used MT5 build 6231 on macOS through Wine 11.1. A USD 100,000 virtual balance was used to study the minimum-lot constraint; this does not recommend funding that amount. The earlier USD 10,000 development test generated only 2 trades.

## Recompute native journal summaries

Install the listed packages before running the full test suite: `python3 -m pip install -r requirements.txt`. The journal summary command alone needs only the Python standard library.

The public deal and opportunity CSV files contain simulated research activity. They contain no live account identifiers. Native fees and swaps are retained. The summarizer adds only any gap below USD 7/lot roundtrip commission plus USD 20/lot adverse price slippage. Stress targets USD 14 plus USD 40. These overlays do not retroactively resize historical positions.

```sh
python3 analysis/summarize_native.py --deals data/revision/operations_only_development_GoldRegimeRetest_Trades_20261028.csv --opportunities data/revision/operations_only_development_GoldRegimeRetest_Opportunities_20261028.csv --out regenerated --label operations_only_development --initial-balance 100000
python3 -m unittest discover -s tests -v
```

Use the analogous paths and labels for every other run. The source validates complete volume-balanced positions before reporting returns.

## Conditional random benchmarks

Install `requirements.txt` in a Python virtual environment. Continuous historical broker price data are not bundled. Use the tester-only exporter and quote tracer with your own broker data to create the specs, sessions and actual bid/ask M1 aggregates. Run each exporter once over the full January 13–October 24 span, with XAUUSD and H1 selected. `ExportGoldRates` writes `CodexGold_M1_20261026.csv` and `CodexGold_specs_20261026.csv`. `TraceGoldQuotes` writes `CodexGold_QuoteM1_20261028.csv` and `CodexGold_trade_sessions_20261028.csv`. A shorter subsequent run overwrites the common export files. Put these four files in the `market-data` directory. Record native opportunity journals for all windows. Supply paths explicitly:

```sh
python3 analysis/benchmark.py --label development --data market-data --out regenerated/baseline --initial-balance 100000 --verified-swap-mode-name SYMBOL_SWAP_MODE_CURRENCY_PROFIT
python3 analysis/benchmark_revision.py --label operations_only_development --data data/revision --market-data market-data --out regenerated/revision --initial-balance 100000 --verified-swap-mode-name SYMBOL_SWAP_MODE_CURRENCY_PROFIT
```

For the baseline, put its prefixed opportunity CSVs in `market-data` alongside the quote/spec/session files. Supply the verified swap enum only after checking it in your installed MQL5 runtime; never silently omit unsupported financing. Each report records input hashes. Full historical tick reproduction requires the same broker history and platform behavior; the public summaries and journals can be recomputed without that history.

Each conditional policy uses 5,000 fair random-direction paths and 5,000 paths preserving the observed long bias. These test direction choices at strategy-conditioned opportunity times. Compare the native and modeled entry sets and return discrepancies before interpreting ranks. The revision engine includes daily flattening; do not apply the baseline 72-hour holding engine to the revision. All revision windows were previously seen.


## Completed October 26–30 week

Use the unchanged revision EA and presets with native dates `2026.10.26` inclusive to `2026.10.31` exclusive. The simulated balance and cost overlays above are unchanged. Published journals are in `data/week_20261026_30/` and summaries in `results/week_20261026_30/`. This overlaps the earlier October 26–29 extension; it is not a separate untouched validation window. The one-week confidence guard intentionally withholds a bootstrap interval.

## Independent January–September 2023 scenario

This is a separate exploratory model, not a native broker backtest. Read [the report](PROGRESS_2026_10_31.md), [15-month quality audit](independent_source_quality_audit.json), [selection](independent_source_selection.json), and both plans in `results/independent_2023_cleanblock/` before interpreting it. The original full-2023 study was not run: October 2022 and October 2023 archives failed timestamp ordering. No sorting, clock repair or quote imputation is allowed. The amended block uses November–December 2022 warm-up and January–September 2023 evaluation. Valid later months remain outside this scenario.

Obtain your own HistData XAUUSD **Generic ASCII tick** monthly ZIPs from the [official download page](https://www.histdata.com/download-free-forex-data/). M1 bid-only bars cannot substitute for paired bid/ask ticks. Retain the downloaded files locally and compare their SHA-256 values with the source audit. Raw ZIPs and continuous quotes are deliberately excluded from this repository. The converter does not download data or use an account.

Place the eleven complete monthly files under `market-data/`, named as below (local filenames may differ; pass their actual paths). Convert them without changing their original order:

```sh
python3 analysis/histdata_ticks.py \
  --zip market-data/XAUUSD_T_202211.zip market-data/XAUUSD_T_202212.zip \
        market-data/XAUUSD_T_202301.zip market-data/XAUUSD_T_202302.zip \
        market-data/XAUUSD_T_202303.zip market-data/XAUUSD_T_202304.zip \
        market-data/XAUUSD_T_202305.zip market-data/XAUUSD_T_202306.zip \
        market-data/XAUUSD_T_202307.zip market-data/XAUUSD_T_202308.zip \
        market-data/XAUUSD_T_202309.zip \
  --from 2022-11-01 --until 2023-10-01 \
  --out market-data/clean-block.csv --report regenerated/conversion.json

python3 analysis/independent_study.py \
  --data market-data/clean-block.csv \
  --plan results/independent_2023_cleanblock/study_plan.json \
  --out regenerated/independent --validate-only

python3 analysis/independent_study.py \
  --data market-data/clean-block.csv \
  --plan results/independent_2023_cleanblock/study_plan.json \
  --out regenerated/independent

python3 analysis/build_followup_report.py --tests 63
```

The converter checks complete raw months before clipping the requested interval, rejects clock reversals/crossed prices/malformed rows/source-month mismatches, preserves equal-time quotes in their original order, and aggregates actual bid/ask OHLC plus first/last tick bounds. It follows the provider's declared fixed EST clock by adding five hours; actual physical UTC alignment is not independently certified. The eleven-month conversion reproduced all 279,467 execution-input minute rows exactly in value, count and timestamp ([receipt](clean_block_reproduction.json)). Round-trip float CSV formatting can change the byte hash while preserving identical values; source ZIP hashes and adapter input hashes remain recorded separately.

The adapter checks source/engine hashes in the plan and uses the unchanged signal implementation and execution core. It runs 5,000 fair-direction and 5,000 long-bias paths per profile with seed 20261031. It retains all affected trades and forces `inconclusive_unobserved_price_paths` when a valid direction outcome crosses unobserved quote minutes. The published returns still fail the numerical gates. Numeric hours, contract, commission, slippage and static financing are declared scenario assumptions, not verified 2023 broker terms. M1 aggregates and whole-second execution cannot recover intraminute tick order. Coverage, provenance, opportunities, trade ledgers and saved control returns are published so these limits and arithmetic can be inspected without redistributing quotes.

The signal module matched all 236 earlier native events by minute/direction; three first-tick seconds were unavailable in the legacy M1 archive. A seven-event completed-week check matches event times/directions and entry quotes, with a disclosed EMA discrepancy on stitched history. See [earlier parity](signal_parity_summary.json) and [week parity](signal_parity_completed_week.json). These checks do not establish execution equivalence on an independent feed.
