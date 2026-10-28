# Research limitations

These gold trading programs are research prototypes. No reliable edge over matched random trading has been established. A positive historical return would not guarantee future profit, and the programs remain locked to the MetaTrader 5 Strategy Tester.

## Reused historical periods

The original baseline used January 13–June 30, 2026 for development, July 1–August 14 for its reserved validation, and August 17–October 23 for an additional check. Each window starts independently; their returns should not be added or described as one continuous account history.

All three periods have now been examined. Tests of the revised regime/retest program on those same dates are **exploratory retests**, not a new untouched holdout. Adding filters after observing a failed validation does not make the original validation unseen again. Further claims require genuinely new data and a prospectively fixed evaluation plan. Selecting only profitable variants or periods would overstate the evidence. See [The Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf).

## Capital and execution constraints

The initial $10,000 simulated balance allowed too few trades: at 0.25% planned stop risk, the minimum permitted gold lot exceeded the budget for many hourly stops. The main $100,000 virtual capacity study reduces that volume-granularity distortion. It is a simulation assumption, not a recommendation to deposit or commit capital.

The 0.25% setting is planned loss from entry to stop, not a guaranteed realized-loss ceiling. Gaps, spread changes, slippage, financing, trading restrictions and failed fills can produce larger losses. Daily flattening in the revision reduces overnight exposure but cannot guarantee an exit when quotes or trading permission are unavailable.

## Costs and measurements

Native journal summaries retain recorded profit, swaps, commissions and fees. They top up commission to at least $7 per lot round trip and add an adverse $0.10 gold-price movement per side. With a 100-unit contract, that slippage allowance is $20 per lot. Recorded native fees are credited against the commission target so they are not counted twice. The stress scenario doubles the declared commission and slippage targets; recorded native fees are again retained and credited.

Financing models use exported swap rates and weekday multipliers. Historical rate changes are unavailable. Additional journal cost overlays do not retroactively change the native positions’ historical sizing. Closed-balance drawdown excludes open-position equity excursions.

Native tick tests and an independent benchmark using minute aggregates can differ in intraminute ordering, gap fills, stop slippage and rounding. Actual bid/ask aggregates and trading-session restrictions improve consistency, but do not recreate every tick. Random-direction benchmark ranks are conditional on the strategy’s opportunity times; they are not probabilities of future profit or proof of general timing skill. MetaTrader documents relevant [Strategy Tester behavior and limitations](https://www.mql5.com/en/docs/runtime/testing).
