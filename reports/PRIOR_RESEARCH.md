# What the earlier bots actually showed

The earlier EURUSD work had modest positive simulated results, alongside losing periods and weak sample sizes. It should not be described as a sequence of universal failures, or as proof that the same entry filters will work on gold. This review uses saved aggregate research records; it does not add new tests.

## EURUSD baseline

These runs each began with USD 25,000, nominal risk of 0.25%, M15 signals and an H1 trend filter. Dates are broker-server dates; the end date is exclusive. Net profit is the saved native MT5 result, without the new gold study's additional cost overlay. PF means profit factor; drawdown is native maximal equity drawdown. These figures are therefore historical context rather than a directly comparable gold ranking.

| Profile | Window | Net USD | Return | Trades | PF | Equity drawdown |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Original EURUSD V2.18a | Common reference, 2026-01-21–2026-08-15 | +496.25 | +1.9850% | 22 | 1.78 | 426.72 (1.67%) |
| Original EURUSD V2.18a | Later, 2026-08-15–2026-10-21 | +21.72 | +0.0869% | 6 | 1.13 | 164.59 (0.66%) |
| Checked EURUSD | Common reference, 2026-01-21–2026-08-15 | +443.06 | +1.7722% | 22 | 1.70 | 425.31 (1.66%) |
| Checked EURUSD | Later, 2026-08-15–2026-10-21 | +21.11 | +0.0844% | 6 | 1.13 | 163.51 (0.65%) |

Sources: `Regime suite/regime-common-results.json`, `Regime suite/regime-eurusd-results.json`, and `Regime suite/regime-main-results.json`. The checked baseline is also retained in `Regime round 2/Baseline results.json`.

The earlier requested reference began on January 17. Over that longer EURUSD interval, the original made **USD 430.45 on 24 trades** (PF 1.61), and the checked version made **USD 377.04 on 24 trades** (PF 1.54). The common-reference comparison begins January 21 to align with available index coverage. These are different windows, not conflicting results.

The six trades in each later EURUSD window are insufficient to establish a stable edge. The saved Regime suite records report all 49 planned strategy runs completed; the broader index results included losing reference windows. Profits from separate account simulations must not be added into a supposed portfolio return.

## Positive and losing quarters

Each quarterly slice independently reset the balance and EA guard state to USD 25,000. Q3 is partial, ending August 15. Do not add or compound these slices as a continuous account result.

| Profile | Slice | Net USD | Return | Trades | PF |
| --- | --- | ---: | ---: | ---: | ---: |
| Original EURUSD V2.18a | Q1, Jan 17–Apr 1 | +321.57 | +1.2863% | 14 | 1.90 |
| Original EURUSD V2.18a | Q2, Apr 1–Jul 1 | -105.29 | -0.4212% | 8 | 0.69 |
| Original EURUSD V2.18a | Partial Q3, Jul 1–Aug 15 | +216.40 | +0.8656% | 2 | 35.08 |
| Checked EURUSD | Q1, Jan 17–Apr 1 | +319.16 | +1.2766% | 14 | 1.89 |
| Checked EURUSD | Q2, Apr 1–Jul 1 | -108.44 | -0.4338% | 8 | 0.68 |
| Checked EURUSD | Partial Q3, Jul 1–Aug 15 | +164.10 | +0.6564% | 2 | 27.05 |

Sources: `Regime suite/regime-eurusd-folds-results.json` and `Regime suite/regime-folds-results.json`. The large partial-Q3 profit factors come from only two trades and are unstable. Both EURUSD versions lost money in Q2.

## Removing the retest made EURUSD worse

The round-two direct-breakout experiment disabled the breakout retest requirement while retaining the checked EURUSD strategy's other preset fields. It increased activity and reduced net results in both saved windows.

| Entry version | Window | Net USD | Return | Trades | PF |
| --- | --- | ---: | ---: | ---: | ---: |
| Checked baseline, retest required | Reference, Jan 21–Aug 15 | +443.06 | +1.7722% | 22 | 1.70 |
| Direct breakout, retest disabled | Reference, Jan 21–Aug 15 | -53.99 | -0.2160% | 71 | 0.98 |
| Checked baseline, retest required | Later, Aug 15–Oct 21 | +21.11 | +0.0844% | 6 | 1.13 |
| Direct breakout, retest disabled | Later, Aug 15–Oct 21 | -394.47 | -1.5779% | 32 | 0.71 |

Sources: `Regime round 2/Baseline results.json` and `Regime round 2/round2-experiments-results.json`.

Other saved EURUSD variants do not establish a replacement winner. Pullback-only produced -USD 131.90 on three reference trades and -USD 65.00 on one later trade. Raising minimum ADX to 30 produced +USD 388.16 on 21 reference trades and the same +USD 21.11 on six later trades. More filtering can leave too little evidence; more trading can add losses.

## Round-two completion status

The schedule contains **40 planned experiments**. The saved results contain **36 complete records and one failed record**, with three planned cases lacking a saved result. The failed case is the Dow fixed-2R reference experiment, whose terminal exited before a complete report. Missing records are Dow fixed-2R later and Nasdaq fixed-2R reference/later. No outcome is inferred for failed or missing cases, and this is not a claim that all 40 completed.

Sources: `Regime round 2/round2-experiments.json` and `Regime round 2/round2-experiments-results.json`.

## What transfers to the gold experiment

The evidence supports testing a later-bar retest and trend-strength condition as a distinct hypothesis. It also supports retaining fixed risk, checking actual symbol trading sessions, respecting minimum trade sizes, recording rejected orders, and comparing an operations-only variant with a filtered-entry variant. These principles explain the new gold experiment; the earlier EURUSD profits do not validate gold.

The gold revision is not a port of the entire EURUSD strategy. It retains gold's H1 EMA200/24-bar-breakout foundation and ATR exits, then separately tests session controls, daily closing, and a retest/ADX gate. Daily closing is a new operational hypothesis for gold, not a demonstrated source of EURUSD profit. All reused gold periods are exploratory retests. The previous results do not justify choosing new hours from already-seen hourly profits or increasing risk to improve headline returns. A dependable edge still requires fresh evidence after realistic costs.

## Aggregate evidence fingerprints

These SHA-256 hashes identify the original saved aggregate files used for this review. Paths are relative to the earlier research output collection. The original records remain local; no account configurations, raw terminal logs, or broker credentials are included here.

| Original aggregate file | SHA-256 |
| --- | --- |
| `Regime suite/regime-common-results.json` | `fca09d4dc2af922ab8299ec84294d5a71f7a2747173ed8b7ae3e7e778705a050` |
| `Regime suite/regime-eurusd-results.json` | `c093fcfc1d2761f3b60abf6e4aa8c9f5c4da29b44a30c00ede637fe314ebf831` |
| `Regime suite/regime-main-results.json` | `a15b64081922562e2d25d56c3e3f74fcd509d5d7c741b875fcf83fba142a46fd` |
| `Regime suite/regime-eurusd-folds-results.json` | `411f302b05ea709c3b839e60eb484fe808a38dc38f91b0f5bbd4b2adf2479aaa` |
| `Regime suite/regime-folds-results.json` | `91457e21ed480bc2fa05679c7bfc2ca68c1b292c33d31eea8016672d30df6279` |
| `Regime suite/summary.json` | `be8c71c23e4a74f95235a2e005a8fa9387438dcf73a1397d161676d217031313` |
| `Regime round 2/Baseline results.json` | `12268327bfe86b950eccd1e33d5f6779f1604ea82ebdadf91a51b54d7f535ff9` |
| `Regime round 2/round2-experiments-results.json` | `303c0ad02410b8cec1e7f5ef47c9251d7f7bbfb4782e0e6d988db1583cfb3e16` |
| `Regime round 2/round2-experiments.json` | `7e9121a575f967716f45d05d278ca01e4262454cb6f86bde88e1d8388ad83c74` |
