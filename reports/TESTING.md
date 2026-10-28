# Verification record

Completed October 28, 2026. The revised native source compiled with 0 errors and 0 warnings. Six independent real-tick historical runs completed. All intended input switches were checked in their native reports. Complete native position volumes balance; zero positions crossed midnight, zero native swaps were charged, and no market-closed attempts or order rejections were recorded. Retest confirmation ages were 1–3.

Independent modeled entry sets match all six native runs. Five thousand fair random-direction paths and five thousand long-bias controls were run per period/variant. No case passed all evidence gates. Native P/L and minute-model P/L remain separately reported.

The 16 public fixture tests passed: 9 journal-accounting and completeness checks, plus 7 daily-flat execution checks. Native baseline summaries recomputed with the portable summarizer exactly match the earlier 76/18/32-trade results. No live orders were placed. Source hashes and simulation metadata are recorded in `provenance.json` and `SHA256SUMS.json`.
