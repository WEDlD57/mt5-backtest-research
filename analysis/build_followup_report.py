"""Render the October31 research follow-up from saved native/model artifacts."""
from pathlib import Path
import argparse,json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


def main():
    p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--tests',type=int,required=True);args=p.parse_args()
    root=args.repo.resolve();folder=root/'results/independent_2023_cleanblock'
    variants=[('operations_only','Hours only · primary'),('regime_retest','Retest + ADX · secondary')]
    reports={v:json.loads((folder/(v+'_report.json')).read_text()) for v,_ in variants}
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10})
    fig,axes=plt.subplots(1,2,figsize=(12,5.6))
    for ax,(variant,name) in zip(axes,variants):
        report=reports[variant];d=json.loads((folder/(variant+'_random_returns.json')).read_text())
        fair=np.asarray(d['fair_random_direction_return_pct']);bias=np.asarray(d['long_bias_return_pct']);value=report['actual_policy_same_engine']['return_pct']
        bins=np.linspace(min(fair.min(),bias.min(),value),max(fair.max(),bias.max(),value),55)
        ax.hist(fair,bins=bins,alpha=.55,color='#8a98a5',label='Fair random directions')
        ax.hist(bias,bins=bins,alpha=.45,color='#148a7d',label='Long-bias controls')
        ax.axvline(value,color='#222222',linewidth=2,label=f'Rule policy: {value:+.2f}%')
        ax.set_title(f"{name}\n{report['actual_policy_same_engine']['trades']} modeled trades",loc='left',weight='bold')
        ax.set_xlabel('Modeled after-cost return (%)');ax.set_ylabel('Paths out of 5,000')
        ax.grid(axis='y',alpha=.15);ax.set_axisbelow(True);ax.spines[['top','right']].set_visible(False)
        ax.legend(frameon=False,fontsize=8)
    fig.suptitle('Exploratory January–September 2023 stress: no established edge',x=.065,ha='left',weight='bold',fontsize=14)
    fig.text(.065,.04,'Both scenarios are inconclusive because holdings cross unobserved quote minutes.\nVirtual contract/costs and provider-declared clock; this is not native broker validation or a forecast.',fontsize=9,color='#444444')
    fig.subplots_adjust(left=.065,right=.98,bottom=.21,top=.82,wspace=.22)
    fig.savefig(root/'reports/independent_2023_comparison.png',dpi=170);plt.close(fig)
    week={v:json.loads((root/'results/week_20261026_30'/(v+'_week_oct26_30_native.json')).read_text()) for v,_ in variants}
    text='''# Completed week and longer-history research — October31,2026

**The bot still has no established dependable edge.** The new native week was profitable on three and one trades. A larger independent modeled scenario lost money, failed its numerical evidence gates, and remained inconclusive because of unobserved quote intervals. The original full-year data test was rejected before returns were calculated.

## Completed native week: October26–30

Each profile independently starts with USD100,000 simulated equity and0.25% planned stop risk. This is one weekly block. October26–29 had already been inspected; October30 adds one completed day. The combined week is not a new untouched five-day validation, and its return must not be added to earlier independent account runs.

| Unchanged native profile | Closed trades | After-cost net USD | Return | Cost-stress return |
|---|---:|---:|---:|---:|
'''
    for v,name in variants:
        n=week[v];text+=f"|{name}|{n['native_trades']}|{n['adjusted_net_usd']:+.2f}|{n['adjusted_return_pct']:+.5f}%|{n['doubled_additional_cost_return_pct']:+.5f}%|\n"
    text+='''
The frozen EA/source and installed binary were unchanged. Its entry and closing windows were quoted throughout, including Friday17:00. Journals balance, all positions closed on the entry day, swaps were zero, and neither profile recorded rejected orders, market-closed attempts or indicator warm-up skips. The one-week confidence guard correctly withheld an interval.

The longer trace differs from the earlier four-day export only in its prior final23:59minute: it includes nine additional ticks through23:59:59, while that earlier test stopped at23:59:58. No quotes were repaired. Broker trading-session metadata also changed between runs; the intended entry/closing windows remained open. This is recorded in[execution verification](completed_week_verification.json), not hidden as an immutable historical setting.

## Larger independent scenario

The fixed full2023 archive attempt failed clock-quality checks. Of15monthly tick files, October2022 and October2023 each contained an unexplained one-hour timestamp reversal. The original full-year study remains **NOT RUN**; no failed month was silently sorted or normalized.

Before any independent-feed returns were calculated, a separate exploratory plan selected the longest contiguous valid monthly block: November–December2022 warm-up and January1–October1,2023 evaluation (January–September). The later valid November/December2023 files were retained in the audit and excluded from this scenario. This was a timestamp-quality selection, not a return-based winner search. It does not satisfy the rejected full-year plan or constitute prospective validation.

The source uses actual paired bid/ask ticks, converted by the provider's stated fixedEST+5hours. Its physical UTC alignment is not independently certified. Numeric07:00–20:00/Friday17:00 hours are a provider-clock scenario, not assumed to match the original broker's unknown offset. The1:100 leverage,100-ounce contract,0.01 minimum lot,7USD/lot commission and0.10price slippage per side are declared virtual assumptions. Entry/exit quotes retain provider precision; only protective levels use a0.01price grid. Observed quoted minutes are assumed fillable; no broker trading calendar is fabricated.

![Conditional model comparisons](independent_2023_comparison.png)

| Exploratory model profile | Trades | Return | Fair-control percentile | Long-bias percentile | Doubled-cost return |
|---|---:|---:|---:|---:|---:|
'''
    for v,name in variants:
        r=reports[v];a=r['actual_policy_same_engine'];text+=f"|{name}|{a['trades']}|{a['return_pct']:+.3f}%|{r['fair_random_direction_control']['observed_percentile']:.2f}|{r['long_bias_control']['observed_percentile']:.2f}|{r['doubled_commission_slippage']['return_pct']:+.3f}%|\n"
    text+='''
Each control uses5,000 paths within the same execution engine and strategy-conditioned opportunities. The primary profile has113trades, yet its return is negative, its rank is below the95th-percentile thresholds, and its weekly expectancy interval spans zero. Retest has29trades and also loses money. The ranges and ranks are descriptive model outputs, not probabilities of future profit.

| Profile | Executed holds crossing unobserved minutes | Overnight trades | Declared financing charged USD |
|---|---:|---:|---:|
'''
    for v,name in variants:
        h=reports[v]['holding_diagnostics']['actual_executed'];text+=f"|{name}|{h['trades_with_unobserved_quote_minutes']} / {h['trades']}|{h['overnight_trades']}|{h['funding_usd']:.5f}|\n"
    text+='''
Absence of a quote may reflect a closed market or missing feed data; the study does not guess which. Price-path gaps prevent a complete-path evidence pass for both profiles. Every affected trade and its modeled return was retained rather than dropped to improve performance. Some modeled closes were delayed until the next observed quote. Static financing assumptions were applied across crossed midnights; those rates are not verified provider rates for2023. Actual first/last quote bounds were preserved, while execution timestamps use whole-second precision and M1OHLC still cannot reproduce intraminute ordering. No native/live broker execution equivalence is claimed.

## What improved

An independent signal implementation matches all236recorded native opportunities by minute and direction. Three native events occur one second after their M1timestamp; the older minute archive cannot expose that first-tick second. EMA/ATR/ADX differences on the matching inputs are limited to CSV rounding. It reproduces MetaTrader's ATR/iADX arithmetic rather than substituting a typical Wilder implementation.

A further seven native opportunities in the completed week match timestamps/directions and entry quotes. Full numeric parity is not claimed on that stitched chart/tick input: EMA differs by up to0.002209 because of an input-history boundary. No rule or price was changed to fit it. See[signal parity](signal_parity_summary.json) and[the additional check](signal_parity_completed_week.json).

The independent adapter requires actual both-side OHLC and first/last tick bounds, records gaps and finer quote precision, applies financing to delayed closes, and forces inconclusive status when a valid direction path contains unobserved minutes. It never reconstructs asks from a fixed spread or removes losing trades on coverage grounds.
'''
    text+=f"\nThe public test suite has **{args.tests} passing tests** after these additions. The EA signal/risk/exit rules remain frozen. Old studies and losing cases are retained.\n"
    text+='''
## Decision and reproducibility

These results do not justify promoting either bot as reliably profitable. Keep the existing[future validation protocol](NEXT_VALIDATION.md) fixed. A favorable primary result would still require credible quote coverage, realistic execution/costs and untouched replication; additional filters tuned to these dates would be a new experiment, not a repair of failed validation.

See the[15-month source audit](independent_source_quality_audit.json),[explicit source selection](independent_source_selection.json), and the[original rejected plan](../results/independent_2023_cleanblock/original_full2023_plan.json) alongside the[amended local plan](../results/independent_2023_cleanblock/study_plan.json). Plans were recorded locally before the corresponding return calculations and published afterwards; they are not externally timestamped preregistrations. Derived journals, control distributions and coverage metadata are under`results/independent_2023_cleanblock/`; native week journals are under`data/week_20261026_30/`and`results/week_20261026_30/`. Continuous quote history and raw archives are excluded.

Source references: [HistData FAQ](https://www.histdata.com/f-a-q/),[official download page](https://www.histdata.com/download-free-forex-data/),[MetaQuotes testing behavior](https://www.mql5.com/en/docs/runtime/testing). A requested2023 native broker probe produced no fresh quote export and was not substituted with older cached data.
'''
    replacements={'October31,2026':'October 31, 2026','October26–30':'October 26–30','October26–29':'October 26–29','October30':'October 30','USD100,000':'USD 100,000','and0.25%':'and 0.25%','Friday17:00':'Friday 17:00','final23:59minute':'final 23:59 minute','through23:59:59':'through 23:59:59','at23:59:58':'at 23:59:58','in[execution':'in [execution','full2023':'full 2023','Of15monthly':'Of 15 monthly','October2022':'October 2022','October2023':'October 2023','December2022':'December 2022','January1–October1,2023':'January 1–October 1, 2023','December2023':'December 2023','fixedEST+5hours':'fixed EST +5 hours','Numeric07:00':'Numeric 07:00','The1:100':'The 1:100',',100-ounce':', 100-ounce',',0.01':', 0.01',',7USD/lot':', USD 7/lot','and0.10price':'and 0.10 price','a0.01price':'a 0.01 price','uses5,000':'uses 5,000','has113trades':'has 113 trades','the95th-percentile':'the 95th-percentile','has29trades':'has 29 trades','for2023':'for 2023','M1OHLC':'M1 OHLC','all236recorded':'all 236 recorded','their M1timestamp':'their M1 timestamp','to0.002209':'to 0.002209','See[signal':'See [signal',') and[the':') and [the','existing[future':'existing [future','the[15-month':'the [15-month',', [explicit':', [explicit',') and the[original':') and the [original','the[amended':'the [amended','under`results/independent_2023_cleanblock/`':'under `results/independent_2023_cleanblock/`','under`data/week_20261026_30/`and`results/week_20261026_30/`':'under `data/week_20261026_30/` and `results/week_20261026_30/`','),[':'), [','requested2023':'requested 2023'}
    for a,b in replacements.items():text=text.replace(a,b)
    text=text.replace('original_full 2023_plan.json','original_full2023_plan.json').replace('the[original','the [original')
    (root/'reports/PROGRESS_2026_10_31.md').write_text(text)

if __name__=='__main__':main()
