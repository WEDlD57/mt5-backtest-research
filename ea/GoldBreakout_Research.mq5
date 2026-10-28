// Original frozen-hypothesis research EA. No chart trading is permitted.
#property strict
#property version "1.00"
#property description "Tester-only gold H1 breakout with EMA trend, ATR exits, fixed fractional risk and cost gates."

#include <Trade/Trade.mqh>

input int    InpBreakoutBars             = 24;
input int    InpEmaPeriod                = 200;
input int    InpAtrPeriod                = 14;
input double InpStopAtr                  = 2.0;
input double InpTargetAtr                = 4.0;
input int    InpMaxCompletedBarsHeld     = 72;
input double InpRiskPercent              = 0.25;
input double InpMaxSpreadPrice           = 1.00;
input double InpMaxSpreadToStop          = 0.10;
input double InpRoundtripCommissionPerLot= 7.00;
input double InpAdverseSlippagePerSide   = 0.10;
input double InpMaxExtraCostsToRisk      = 0.10;
input ulong  InpMagic                    = 2026102601;
input ulong  InpDeviationPoints          = 10;

CTrade g_trade;
int g_ema=INVALID_HANDLE;
int g_atr=INVALID_HANDLE;
int g_opportunities=INVALID_HANDLE;
bool g_ready=false;
bool g_loggingFailed=false;
datetime g_lastBar=0;
datetime g_nextCloseAttempt=0;
ulong g_timeExitTicket=0;
ulong g_bars=0,g_warmup=0,g_signals=0,g_busy=0,g_spreadReject=0;
ulong g_zeroVolume=0,g_costReject=0,g_stopsReject=0,g_marginReject=0;
ulong g_orderReject=0,g_entries=0,g_timeExits=0,g_logRows=0;

double PriceDown(const double price)
  {
   double step=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
   if(step<=0) return 0;
   return NormalizeDouble(MathFloor(price/step)*step,_Digits);
  }

double PriceUp(const double price)
  {
   double step=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
   if(step<=0) return 0;
   return NormalizeDouble(MathCeil(price/step)*step,_Digits);
  }

bool AcceptedTradeResult()
  {
   uint result=g_trade.ResultRetcode();
   return result==TRADE_RETCODE_DONE || result==TRADE_RETCODE_DONE_PARTIAL ||
          result==TRADE_RETCODE_PLACED;
  }

ulong OwnPositionTicket()
  {
   for(int i=PositionsTotal()-1;i>=0;i--)
     {
      ulong ticket=PositionGetTicket(i);
      if(ticket==0) continue;
      if(PositionGetString(POSITION_SYMBOL)==_Symbol &&
         (ulong)PositionGetInteger(POSITION_MAGIC)==InpMagic)
         return ticket;
     }
   return 0;
  }

void ManageTimeExit()
  {
   ulong ticket=OwnPositionTicket();
   if(ticket==0)
     {
      g_timeExitTicket=0;
      g_nextCloseAttempt=0;
      return;
     }
   if(!PositionSelectByTicket(ticket)) return;
   datetime entered=(datetime)PositionGetInteger(POSITION_TIME);
   // This counts existing H1 bars, rather than elapsed wall-clock hours.
   // Entry is at the first tick of an H1 bar; shift 72 means 72 bars completed.
   int completed=iBarShift(_Symbol,PERIOD_H1,entered,false);
   if(completed<InpMaxCompletedBarsHeld) return;
   if(ticket!=g_timeExitTicket)
     {
      g_timeExitTicket=ticket;
      g_nextCloseAttempt=0;
     }
   if(TimeCurrent()<g_nextCloseAttempt) return;
   if(g_trade.PositionClose(ticket,InpDeviationPoints) && AcceptedTradeResult())
     {
      g_timeExits++;
      g_nextCloseAttempt=0;
     }
   else
     {
      g_orderReject++;
      g_nextCloseAttempt=TimeCurrent()+60;
      PrintFormat("GoldBreakout time-exit failed: retcode=%u %s; retry in 60 seconds.",
                  g_trade.ResultRetcode(),g_trade.ResultRetcodeDescription());
     }
  }

double PlannedVolume(const int direction,const double entry,const double stop,
                     const double budget,double &oneLotLoss)
  {
   oneLotLoss=0;
   double outcome=0;
   ENUM_ORDER_TYPE type=direction>0?ORDER_TYPE_BUY:ORDER_TYPE_SELL;
   if(budget<=0 || !OrderCalcProfit(type,_Symbol,1.0,entry,stop,outcome) ||
      !MathIsValidNumber(outcome) || outcome>=0)
      return 0;
   oneLotLoss=-outcome;
   double minVolume=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
   double maxVolume=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX);
   double step=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
   if(step<=0 || minVolume<=0 || maxVolume<minVolume) return 0;
   double raw=MathMin(budget/oneLotLoss,maxVolume);
   if(raw<minVolume) return 0;
   double lots=NormalizeDouble(MathFloor(NormalizeDouble(raw/step,8))*step,8);
   if(lots<minVolume || lots>maxVolume) return 0;
   double check=0;
   if(!OrderCalcProfit(type,_Symbol,lots,entry,stop,check) ||
      !MathIsValidNumber(check) || check>=0 || -check>budget*(1.0+1e-10))
      return 0;
   return lots;
  }

bool StopsAllowed(const int direction,const MqlTick &tick,const double stop,const double target)
  {
   double minimum=SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL)*_Point;
   if(direction>0)
      return stop>0 && stop<tick.bid && target>tick.ask &&
             tick.bid-stop>=minimum && target-tick.bid>=minimum;
   return target>0 && stop>tick.ask && target<tick.bid &&
          stop-tick.ask>=minimum && tick.ask-target>=minimum;
  }

bool LogOpportunity(const datetime time,const int direction,const double atr,const double ema,
                    const MqlTick &tick,const double slDistance,const double tpDistance,
                    const bool spreadEligible,const bool costEligible,
                    const double extraCostsPerLot,const double oneLotLoss)
  {
   if(g_opportunities==INVALID_HANDLE) return false;
   uint bytes=FileWrite(g_opportunities,TimeToString(time,TIME_DATE|TIME_SECONDS),direction,
                       DoubleToString(atr,10),DoubleToString(ema,10),
                       DoubleToString(tick.bid,_Digits),DoubleToString(tick.ask,_Digits),
                       DoubleToString(slDistance,10),DoubleToString(tpDistance,10),
                       spreadEligible?1:0,costEligible?1:0,
                       DoubleToString(extraCostsPerLot,10),DoubleToString(oneLotLoss,10));
   if(bytes==0)
     {
      g_loggingFailed=true;
      PrintFormat("GoldBreakout opportunity write failed: error=%d; new entries stopped.",GetLastError());
      return false;
     }
   g_logRows++;
   return true;
  }

void EvaluateClosedBar()
  {
   g_bars++;
   int need=InpBreakoutBars+2;
   // Tester indicators calculate lazily when CopyBuffer requests values.
   // Check available history here; testing BarsCalculated before the first
   // CopyBuffer can leave every bar permanently in warm-up.
   if(Bars(_Symbol,PERIOD_H1)<MathMax(InpEmaPeriod+2,InpAtrPeriod+2))
     {
      g_warmup++;
      return;
     }
   MqlRates bars[];
   ArraySetAsSeries(bars,true);
   double ema[1],atr[1];
   if(CopyRates(_Symbol,PERIOD_H1,0,need,bars)!=need ||
      CopyBuffer(g_ema,0,1,1,ema)!=1 || CopyBuffer(g_atr,0,1,1,atr)!=1 ||
      !MathIsValidNumber(ema[0]) || !MathIsValidNumber(atr[0]) || atr[0]<=0 ||
      ema[0]==EMPTY_VALUE || atr[0]==EMPTY_VALUE)
     {
      g_warmup++;
      return;
     }
   double highest=bars[2].high,lowest=bars[2].low;
   for(int i=3;i<need;i++)
     {
      highest=MathMax(highest,bars[i].high);
      lowest=MathMin(lowest,bars[i].low);
     }
   int direction=0;
   if(bars[1].close>highest && bars[1].close>ema[0]) direction=1;
   else if(bars[1].close<lowest && bars[1].close<ema[0]) direction=-1;
   if(direction==0) return;
   g_signals++;

   MqlTick tick;
   if(!SymbolInfoTick(_Symbol,tick) || tick.ask<=0 || tick.bid<=0 || tick.ask<tick.bid)
      return;
   double entry=direction>0?tick.ask:tick.bid;
   double stop=direction>0?PriceDown(entry-InpStopAtr*atr[0]):PriceUp(entry+InpStopAtr*atr[0]);
   double target=direction>0?PriceUp(entry+InpTargetAtr*atr[0]):PriceDown(entry-InpTargetAtr*atr[0]);
   double slDistance=MathAbs(entry-stop),tpDistance=MathAbs(target-entry);
   if(stop<=0 || target<=0 || slDistance<=0 || tpDistance<=0) return;
   double spread=tick.ask-tick.bid;
   bool spreadEligible=spread<=MathMin(InpMaxSpreadPrice,InpMaxSpreadToStop*slDistance)+1e-10;
   double budget=AccountInfoDouble(ACCOUNT_EQUITY)*InpRiskPercent/100.0;
   double oneLotLoss=0;
   double lots=PlannedVolume(direction,entry,stop,budget,oneLotLoss);
   double contract=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_CONTRACT_SIZE);
   double extraCostsPerLot=InpRoundtripCommissionPerLot+2.0*InpAdverseSlippagePerSide*contract;
   bool costEligible=lots>0 && contract>0 && extraCostsPerLot*lots<=InpMaxExtraCostsToRisk*budget+1e-10;

   // Retain all raw rule signals, with eligibility flags, before position filtering.
   // Random paths can therefore take later opportunities when their own prior trade exits.
   if(!LogOpportunity(TimeCurrent(),direction,atr[0],ema[0],tick,slDistance,tpDistance,
                      spreadEligible,costEligible,extraCostsPerLot,oneLotLoss))
      return;
   if(!spreadEligible) {g_spreadReject++;return;}
   if(OwnPositionTicket()!=0) {g_busy++;return;}
   if(lots<=0) {g_zeroVolume++;return;}
   if(!costEligible) {g_costReject++;return;}
   if(!StopsAllowed(direction,tick,stop,target)) {g_stopsReject++;return;}
   double margin=0;
   ENUM_ORDER_TYPE type=direction>0?ORDER_TYPE_BUY:ORDER_TYPE_SELL;
   if(!OrderCalcMargin(type,_Symbol,lots,entry,margin) ||
      !MathIsValidNumber(margin) || margin>AccountInfoDouble(ACCOUNT_MARGIN_FREE))
     {
      g_marginReject++;
      return;
     }
   bool sent=direction>0?g_trade.Buy(lots,_Symbol,entry,stop,target,"GoldBreakout frozen v1"):
                         g_trade.Sell(lots,_Symbol,entry,stop,target,"GoldBreakout frozen v1");
   if(sent && AcceptedTradeResult())
      g_entries++;
   else
     {
      g_orderReject++;
      PrintFormat("GoldBreakout entry failed: retcode=%u %s.",
                  g_trade.ResultRetcode(),g_trade.ResultRetcodeDescription());
     }
  }

bool ContainsPosition(const ulong id,const ulong &ids[])
  {
   for(int i=0;i<ArraySize(ids);i++) if(ids[i]==id) return true;
   return false;
  }

void ExportJournal()
  {
   if(!HistorySelect(0,TimeCurrent()))
     {
      PrintFormat("GoldBreakout history selection failed: error=%d.",GetLastError());
      return;
     }
   ulong ownIds[];
   int total=HistoryDealsTotal();
   for(int i=0;i<total;i++)
     {
      ulong deal=HistoryDealGetTicket(i);
      if(deal==0 || HistoryDealGetString(deal,DEAL_SYMBOL)!=_Symbol ||
         (ulong)HistoryDealGetInteger(deal,DEAL_MAGIC)!=InpMagic) continue;
      ulong position=(ulong)HistoryDealGetInteger(deal,DEAL_POSITION_ID);
      if(position==0 || ContainsPosition(position,ownIds)) continue;
      int n=ArraySize(ownIds);
      ArrayResize(ownIds,n+1);
      ownIds[n]=position;
     }
   int file=FileOpen("GoldBreakout_Trades_20261026.csv",FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON,',',CP_UTF8);
   if(file==INVALID_HANDLE)
     {
      PrintFormat("GoldBreakout journal open failed: error=%d.",GetLastError());
      return;
     }
   bool ok=FileWrite(file,"time","type","entry","volume","price","profit","swap","commission","positionid","fee","dealid")>0;
   int written=0;
   for(int i=0;i<total && ok;i++)
     {
      ulong deal=HistoryDealGetTicket(i);
      ulong position=(ulong)HistoryDealGetInteger(deal,DEAL_POSITION_ID);
      if(deal==0 || !ContainsPosition(position,ownIds)) continue;
      ENUM_DEAL_TYPE type=(ENUM_DEAL_TYPE)HistoryDealGetInteger(deal,DEAL_TYPE);
      if(type!=DEAL_TYPE_BUY && type!=DEAL_TYPE_SELL) continue;
      ENUM_DEAL_ENTRY entry=(ENUM_DEAL_ENTRY)HistoryDealGetInteger(deal,DEAL_ENTRY);
      string entryText=entry==DEAL_ENTRY_IN?"in":entry==DEAL_ENTRY_OUT?"out":entry==DEAL_ENTRY_INOUT?"inout":"out_by";
      ok=FileWrite(file,TimeToString((datetime)HistoryDealGetInteger(deal,DEAL_TIME),TIME_DATE|TIME_SECONDS),
                   type==DEAL_TYPE_BUY?"buy":"sell",entryText,
                   DoubleToString(HistoryDealGetDouble(deal,DEAL_VOLUME),8),
                   DoubleToString(HistoryDealGetDouble(deal,DEAL_PRICE),_Digits),
                   DoubleToString(HistoryDealGetDouble(deal,DEAL_PROFIT),8),
                   DoubleToString(HistoryDealGetDouble(deal,DEAL_SWAP),8),
                   DoubleToString(HistoryDealGetDouble(deal,DEAL_COMMISSION),8),position,
                   DoubleToString(HistoryDealGetDouble(deal,DEAL_FEE),8),deal)>0;
      if(ok) written++;
     }
   FileFlush(file);
   FileClose(file);
   PrintFormat("GoldBreakout journal: %d simulated deal rows, %s.",written,ok?"complete":"INCOMPLETE");
  }

int OnInit()
  {
   if(!MQLInfoInteger(MQL_TESTER))
     {
      Print("GoldBreakout is locked to the Strategy Tester and cannot run on a trading chart.");
      return INIT_FAILED;
     }
   if(_Symbol!="XAUUSD" || _Period!=PERIOD_H1 || AccountInfoString(ACCOUNT_CURRENCY)!="USD")
     {
      Print("GoldBreakout requires XAUUSD, H1, and simulated account currency USD.");
      return INIT_PARAMETERS_INCORRECT;
     }
   if(InpBreakoutBars<1 || InpEmaPeriod<2 || InpAtrPeriod<1 || InpStopAtr<=0 ||
      InpTargetAtr<=0 || InpMaxCompletedBarsHeld<1 || InpRiskPercent<=0 ||
      InpMaxSpreadPrice<=0 || InpMaxSpreadToStop<=0 || InpRoundtripCommissionPerLot<0 ||
      InpAdverseSlippagePerSide<0 || InpMaxExtraCostsToRisk<=0)
      return INIT_PARAMETERS_INCORRECT;
   g_trade.SetExpertMagicNumber(InpMagic);
   g_trade.SetDeviationInPoints(InpDeviationPoints);
   g_trade.SetAsyncMode(false);
   if(!g_trade.SetTypeFillingBySymbol(_Symbol))
     {
      Print("GoldBreakout: cannot determine permitted order filling mode.");
      return INIT_FAILED;
     }
   g_ema=iMA(_Symbol,PERIOD_H1,InpEmaPeriod,0,MODE_EMA,PRICE_CLOSE);
   g_atr=iATR(_Symbol,PERIOD_H1,InpAtrPeriod);
   if(g_ema==INVALID_HANDLE || g_atr==INVALID_HANDLE) return INIT_FAILED;
   g_opportunities=FileOpen("GoldBreakout_Opportunities_20261026.csv",FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON,',',CP_UTF8);
   if(g_opportunities==INVALID_HANDLE)
     {
      PrintFormat("GoldBreakout opportunity file open failed: error=%d.",GetLastError());
      return INIT_FAILED;
     }
   if(FileWrite(g_opportunities,"time","dir","ATR","ema","entrybid","ask","SLdistance","TPdistance",
                "spread_eligible","cost_eligible","extra_costs_per_lot_usd","one_lot_stop_loss_usd")==0)
     {
      FileClose(g_opportunities);
      g_opportunities=INVALID_HANDLE;
      return INIT_FAILED;
     }
   g_lastBar=iTime(_Symbol,PERIOD_H1,0);
   g_ready=true;
   Print("GoldBreakout v1: frozen H1 rules; timestamps are broker-server time; tester-only, no grid or martingale.");
   return INIT_SUCCEEDED;
  }

void OnTick()
  {
   if(!g_ready) return;
   ManageTimeExit();
   if(g_loggingFailed) return;
   datetime current=iTime(_Symbol,PERIOD_H1,0);
   if(current<=0 || current==g_lastBar) return;
   g_lastBar=current;
   EvaluateClosedBar();
  }

void OnDeinit(const int reason)
  {
   if(g_opportunities!=INVALID_HANDLE)
     {
      FileFlush(g_opportunities);
      FileClose(g_opportunities);
      g_opportunities=INVALID_HANDLE;
     }
   if(g_ema!=INVALID_HANDLE) IndicatorRelease(g_ema);
   if(g_atr!=INVALID_HANDLE) IndicatorRelease(g_atr);
   if(!g_ready || !MQLInfoInteger(MQL_TESTER)) return;
   ExportJournal();
   PrintFormat("GoldBreakout diagnostics: bars=%I64u warmup=%I64u signals=%I64u opportunity_rows=%I64u busy=%I64u spread_rejected=%I64u zero_volume=%I64u cost_rejected=%I64u invalid_stops=%I64u margin_rejected=%I64u order_rejected=%I64u entries=%I64u time_exits=%I64u",
               g_bars,g_warmup,g_signals,g_logRows,g_busy,g_spreadReject,g_zeroVolume,g_costReject,
               g_stopsReject,g_marginReject,g_orderReject,g_entries,g_timeExits);
  }
