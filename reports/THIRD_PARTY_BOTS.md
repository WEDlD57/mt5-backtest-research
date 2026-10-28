# Earlier public-source gold bot checks

These historical Strategy Tester checks used local variants with enforced stops, grid/martingale disabled, tester-only guards, fixed risk controls, and USD 10,000 simulated starts. They were run on XAUUSD M5, August 17–October 23, 2026. Figures are saved native test results; the later gold study cost overlay was not applied to these older runs. They are neither exact upstream defaults nor independently verified live records.

| Local variant | Trades | Net return |
|---|---:|---:|
| Leviathan research |135|-3.48%|
| BBRSI research |2|-0.43%|
| 2MACDSTO research |399|-7.04%|

Upstream projects: [Leviathan](https://github.com/santiquiroz/leviathan), [geraked MT5 strategies](https://github.com/geraked/metatrader5). Source was inspectable; no reliable profit claim was established. This repository contains the original gold research programs created afterwards. It does not bundle those upstream programs or standard MetaTrader headers.

Research also consulted broader-web sources, including [MetaQuotes testing documentation](https://www.metatrader5.com/en/terminal/help/algotrading/testing), [EarnForex's Adjustable MA discussion](https://www.earnforex.com/metatrader-expert-advisors/Adjustable-MA/), and [MQL5's code library](https://www.mql5.com/en/code). Repository popularity and published backtests were not used as evidence of profitability.
