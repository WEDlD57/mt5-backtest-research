"""Build the research overview from saved native and conditional-benchmark JSONs."""
from pathlib import Path
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
WINDOWS=[('development','Jan 13–Jun 30'),('validation_seen','Jul 1–Aug 14'),('context_seen','Aug 17–Oct 23')]
SERIES=[('baseline','Original breakout','#8995a5'),('operations_only','Hours + daily close','#387bc0'),('regime_retest','Hours + retest + ADX','#147d70')]


def records():
    rows=[]
    for variant,name,color in SERIES:
        for period,dates in WINDOWS:
            baseline_period={'validation_seen':'validation','context_seen':'contextual'}.get(period,period)
            label=baseline_period if variant=='baseline' else variant+'_'+period
            group='baseline' if variant=='baseline' else 'revision'
            native=json.loads((ROOT/'results'/group/(label+'_native.json')).read_text())
            benchmark=json.loads((ROOT/'results'/group/(label+'_benchmark.json')).read_text())
            rows.append((variant,name,color,period,dates,native,benchmark))
    return rows


def main():
    rows=records()
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11})
    fig,ax=plt.subplots(figsize=(12,6.4))
    x=np.arange(3);width=.24
    for i,(variant,name,color) in enumerate(SERIES):
        subset=[r for r in rows if r[0]==variant]
        vals=[r[5]['adjusted_return_pct'] for r in subset]
        bars=ax.bar(x+(i-1)*width,vals,width,label=name,color=color)
        for bar,row in zip(bars,subset):
            value=row[5]['adjusted_return_pct'];n=row[5]['native_trades']
            ax.annotate(f'{value:+.2f}%\nn={n}',(bar.get_x()+bar.get_width()/2,value),
                        xytext=(0,7 if value>=0 else -7),textcoords='offset points',ha='center',
                        va='bottom' if value>=0 else 'top',fontsize=9)
    ax.set_xticks(x,[d for _,d in WINDOWS]);ax.set_ylabel('After-cost native return (%)')
    ax.axhline(0,color='#444444',linewidth=.9)
    ax.set_ylim(-1.45,2.95)
    ax.set_title('Gold research: execution fixes did not establish an edge',loc='left',weight='bold',pad=18)
    ax.legend(loc='upper right',frameon=False,fontsize=10)
    ax.grid(axis='y',alpha=.15);ax.set_axisbelow(True)
    ax.spines[['top','right']].set_visible(False)
    fig.text(.08,.035,'Each run resets to USD 100,000 simulated equity. Risk 0.25% per trade. All revision dates were previously seen.\nNo case passed the random-policy and weekly-bootstrap evidence gates. Returns are not one continuous account.',fontsize=9,color='#444444')
    fig.subplots_adjust(left=.08,right=.98,bottom=.19,top=.88)
    fig.savefig(ROOT/'reports/overview.png',dpi=170)
    plt.close(fig)
    text='''# Gold backtest results

**Execution problems were fixed; a dependable profitable edge was not established.** Both revised versions remain research candidates. Every period starts independently atUSD 100,000 simulated equity, with0.25% planned stop risk. Returns must not be added as a continuous account history.

The original breakout had positive development returns and lost money in both later windows. The revision compares the operational changes alone against those same changes plus a later-bar retest and ADX trend-strength requirement. All revision dates were already seen, so these are exploratory retests.

![Native after-cost comparison](overview.png)

| Version | Period (2026) | Trades | Native after-cost return | Win rate | Modeled return | Conditional fair-coin percentile |
|---|---|---:|---:|---:|---:|---:|
'''
    for variant,name,color,period,dates,n,b in rows:
        text+=f"|{name}|{dates}|{n['native_trades']}|{n['adjusted_return_pct']:+.3f}%|{n['adjusted_win_rate_pct']:.1f}%|{b['actual_policy_same_engine']['return_pct']:+.3f}%|{b['fair_coin_policy']['observed_percentile']:.2f}|\n"
    text+='''
Every conditional fair-coin and long-bias rank is below95, and every weekly-bootstrap expectancy interval includes zero. The retest version's later gains come from only7and11trades; its development period lost money. They do not demonstrate a reliable edge. Win rate alone also ignores payoff sizes and costs.

The revision's native/model entry sets match exactly for all six runs: 59/20/26 operations-only and 26/7/11 retest trades. The original entry sets also match 76/18/32. Minute modeling still differs from native tick execution in stop timing, gap/slippage and rounding, so native returns are the primary execution outcome. Percentiles compare policies within the same benchmark engine, not native P/L against a different execution model.

## What was fixed

The revised EA checks actual broker trading sessions, restricts entries to a daytime window, stops new entries30minutes before its daily exit deadline, and closes on the first available tradable tick at/after20:00broker time orFriday17:00. Exit retries are throttled to60seconds. In all six native runs, there were zero order rejections, zero market-closed attempts, zero overnight positions, zero swaps, and complete volume-balanced deal journals. Confirming retest bars had ages1–3, with no entry on the breakout candle itself.

The retest/ADX addition was inspired by earlier EURUSD research, where removing retests worsened results. It is a new gold hypothesis rather than a validated transfer. The operations-only comparison prevents attributing every effect to the entry filter.

## Costs and evidence limits

Native recorded fees and swaps are retained. Commission is topped up to at leastUSD7/lot roundtrip, andUSD20/lot adverse slippage is added. The stress target isUSD14commission plusUSD40slippage, crediting recorded fees again. Extra journal overlays do not retroactively resize positions. Closed-balance drawdown excludes floating equity excursions. Broker history, financing rates and symbol specifications can change the outcome.

Each conditional benchmark has5,000 fair random-direction and 5,000 long-bias paths. Opportunity timing is conditioned on the strategy, which limits the question to direction choice at those times. Historical ranks are not probabilities of future profits. No revised version passes the evidence gates and no previously seen period is presented as a new holdout.

For improvement, keep the corrected execution layer, freeze the next candidate before collecting new data, and require cost-adjusted performance on a prospective untouched period. Do not select only profitable windows, increase risk to inflate returns, or keep adding filters against these same dates. The evidence does not yet justify deploying either revision for live trading.

See[earlier EURUSD research](PRIOR_RESEARCH.md), [limitations](LIMITATIONS.md), [reproduction steps](REPRODUCE.md), [native verification](revision_verification.json), and the complete JSON/CSV results under`results/`and`data/`.
'''
    # Keep prose easy to read without modifying code identifiers or table data.
    for a,b in [('atUSD','at USD '),('with0.25','with 0.25'),('below95','below 95'),('only7and11trades','only 7 and 11 trades'),('exactly76','exactly 76'),('exactly59','exactly 59'),('26/7/11 retest','26/7/11 retest'),('entries30minutes','entries 30 minutes'),('at/after20:00broker','at/after 20:00 broker'),('orFriday17:00','or Friday 17:00'),('to60seconds','to 60 seconds'),('ages1–3','ages 1–3'),('leastUSD7/lot','least USD 7/lot'),('andUSD20/lot','and USD 20/lot'),('isUSD14commission','is USD 14 commission'),('plusUSD40slippage','plus USD 40 slippage'),('has5,000','has 5,000'),('See[','See ['),('under`results/`and`data/`','under `results/` and `data/`')]:text=text.replace(a,b)
    (ROOT/'reports/RESULTS.md').write_text(text)

if __name__=='__main__':main()
