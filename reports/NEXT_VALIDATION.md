# Fixed next validation protocol

Recorded October 30, 2026. This is a research plan; no unattended service, automation or live trading has been started.

## Future window and candidates

Evaluate broker-server dates November 2, 2026 inclusive through February 1, 2027 exclusive. Keep `GoldRegimeRetest_Research.mq5` at its frozen SHA256 `aee4304916495f18895d8022608b09211ade99e3898587b04453a852ee3b9e7f`, with the existing USD 100,000 virtual balance, 0.25% planned stop risk and published presets. Do not adjust entry filters, trading hours, stops or risk in response to interim P/L. Record any necessary operational repair and invalidate or separately label the affected evaluation.

The **hours-only profile is primary**, because it is the simpler execution-controlled candidate. The retest/ADX profile is a prespecified secondary comparison. Do not switch the primary profile after seeing returns. A secondary profit would need a separate untouched replication before a reliability claim.

Use the native real-tick tester and preserve the full window, zero-trade cases, input hashes, execution warnings and cost-adjusted journals. Start each profile independently. These are simulation assumptions; they do not recommend depositing money. Check coverage through entry and closing windows, actual broker sessions, journal completeness and installed-source identity.

## Evidence gates at the fixed review

Require at least 30 closed trades and at least 8 distinct calendar weeks containing trades before interpreting primary evidence. Compare direction choices at its fixed signal opportunities with 5,000 fair-direction and 5,000 long-bias paths using the same engine, cost assumptions, one-position rule and daily closing. Native/model entry discrepancies must be explained before interpreting ranks. Gates are positive native after-cost return, above the 95th percentile of both controls, a positive lower weekly-bootstrap expectancy bound, and positive return with doubled declared commission/slippage targets. Passing these preliminary gates would support more validation; it would not guarantee future profit.

If the fixed window has too few trades or blocks, label it inconclusive. Do not quietly change dates, risk or eligibility to manufacture a pass. If the candidate loses money or fails a gate, retain that result. Source changes after reviewing this window start a new experiment; the same dates no longer count as untouched data.

The October 26–29 extension is excluded from this future window. Its one trade is descriptive only, and the new confidence-interval safeguard prevents a single active week from being reported as precise statistical evidence. The next review requires data that do not yet exist in this research record; it cannot be completed today.
