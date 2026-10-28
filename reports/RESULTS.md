# Gold backtest results

**Execution problems were fixed; a dependable profitable edge was not established.** Both revised versions remain research candidates. Every period starts independently at USD  100,000 simulated equity, with 0.25% planned stop risk. Returns must not be added as a continuous account history.

The original breakout had positive development returns and lost money in both later windows. The revision compares the operational changes alone against those same changes plus a later-bar retest and ADX trend-strength requirement. All revision dates were already seen, so these are exploratory retests.

![Native after-cost comparison](overview.png)

| Version | Period (2026) | Trades | Native after-cost return | Win rate | Modeled return | Conditional fair-coin percentile |
|---|---|---:|---:|---:|---:|---:|
|Original breakout|Jan 13–Jun 30|76|+2.278%|39.5%|+2.290%|73.00|
|Original breakout|Jul 1–Aug 14|18|-0.296%|33.3%|-0.199%|74.14|
|Original breakout|Aug 17–Oct 23|32|-0.983%|28.1%|-1.022%|36.10|
|Hours + daily close|Jan 13–Jun 30|59|+1.562%|52.5%|+1.575%|86.40|
|Hours + daily close|Jul 1–Aug 14|20|-0.210%|40.0%|-0.205%|27.88|
|Hours + daily close|Aug 17–Oct 23|26|-0.087%|38.5%|-0.076%|55.94|
|Hours + retest + ADX|Jan 13–Jun 30|26|-0.830%|46.2%|-0.809%|41.56|
|Hours + retest + ADX|Jul 1–Aug 14|7|+0.531%|57.1%|+0.524%|66.64|
|Hours + retest + ADX|Aug 17–Oct 23|11|+0.412%|36.4%|+0.404%|58.88|

Every conditional fair-coin and long-bias rank is below 95, and every weekly-bootstrap expectancy interval includes zero. The retest version's later gains come from only 7 and 11 trades; its development period lost money. They do not demonstrate a reliable edge. Win rate alone also ignores payoff sizes and costs.

The revision's native/model entry sets match exactly for all six runs: 59/20/26 operations-only and 26/7/11 retest trades. The original entry sets also match 76/18/32. Minute modeling still differs from native tick execution in stop timing, gap/slippage and rounding, so native returns are the primary execution outcome. Percentiles compare policies within the same benchmark engine, not native P/L against a different execution model.

## What was fixed

The revised EA checks actual broker trading sessions, restricts entries to a daytime window, stops new entries 30 minutes before its daily exit deadline, and closes on the first available tradable tick at/after 20:00 broker time or Friday 17:00. Exit retries are throttled to 60 seconds. In all six native runs, there were zero order rejections, zero market-closed attempts, zero overnight positions, zero swaps, and complete volume-balanced deal journals. Confirming retest bars had ages 1–3, with no entry on the breakout candle itself.

The retest/ADX addition was inspired by earlier EURUSD research, where removing retests worsened results. It is a new gold hypothesis rather than a validated transfer. The operations-only comparison prevents attributing every effect to the entry filter.

## Costs and evidence limits

Native recorded fees and swaps are retained. Commission is topped up to at least USD 7/lot roundtrip, and USD 20/lot adverse slippage is added. The stress target is USD 14 commission plus USD 40 slippage, crediting recorded fees again. Extra journal overlays do not retroactively resize positions. Closed-balance drawdown excludes floating equity excursions. Broker history, financing rates and symbol specifications can change the outcome.

Each conditional benchmark has 5,000 fair random-direction and 5,000 long-bias paths. Opportunity timing is conditioned on the strategy, which limits the question to direction choice at those times. Historical ranks are not probabilities of future profits. No revised version passes the evidence gates and no previously seen period is presented as a new holdout.

For improvement, keep the corrected execution layer, freeze the next candidate before collecting new data, and require cost-adjusted performance on a prospective untouched period. Do not select only profitable windows, increase risk to inflate returns, or keep adding filters against these same dates. The evidence does not yet justify deploying either revision for live trading.

See [earlier EURUSD research](PRIOR_RESEARCH.md), [limitations](LIMITATIONS.md), [reproduction steps](REPRODUCE.md), [native verification](revision_verification.json), and the complete JSON/CSV results under `results/` and `data/`.
