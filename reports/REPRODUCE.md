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
