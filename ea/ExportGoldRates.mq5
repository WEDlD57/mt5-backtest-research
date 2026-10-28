// Original research utility. Exports broker bars; never submits orders.
#property strict
#property version "1.00"
#property description "Strategy Tester only: export closed gold M1 bars and contract metadata."

input string   InpSymbol = "XAUUSD";
input datetime InpFrom   = D'2026.01.12 00:00';
input datetime InpUntil  = D'2026.10.24 00:00';

bool g_ready=false;

int OnInit()
  {
   if(!MQLInfoInteger(MQL_TESTER))
     {
      Print("ExportGoldRates is restricted to the Strategy Tester.");
      return INIT_FAILED;
     }
   if(_Symbol!=InpSymbol || InpFrom>=InpUntil)
     {
      Print("ExportGoldRates: test symbol must match InpSymbol and date range must be valid.");
      return INIT_PARAMETERS_INCORRECT;
     }
   g_ready=true;
   PrintFormat("Gold export specification: point=%.10f digits=%I64d tick_size=%.10f contract_size=%.4f volume_min=%.8f volume_step=%.8f swap_long=%.8f swap_short=%.8f swap_mode=%I64d calc_mode=%I64d",
               SymbolInfoDouble(InpSymbol,SYMBOL_POINT),
               SymbolInfoInteger(InpSymbol,SYMBOL_DIGITS),
               SymbolInfoDouble(InpSymbol,SYMBOL_TRADE_TICK_SIZE),
               SymbolInfoDouble(InpSymbol,SYMBOL_TRADE_CONTRACT_SIZE),
               SymbolInfoDouble(InpSymbol,SYMBOL_VOLUME_MIN),
               SymbolInfoDouble(InpSymbol,SYMBOL_VOLUME_STEP),
               SymbolInfoDouble(InpSymbol,SYMBOL_SWAP_LONG),
               SymbolInfoDouble(InpSymbol,SYMBOL_SWAP_SHORT),
               SymbolInfoInteger(InpSymbol,SYMBOL_SWAP_MODE),
               SymbolInfoInteger(InpSymbol,SYMBOL_TRADE_CALC_MODE));
   Print("Gold swap mode name: ",EnumToString((ENUM_SYMBOL_SWAP_MODE)SymbolInfoInteger(InpSymbol,SYMBOL_SWAP_MODE)));
   Print("Gold export time basis: broker server time; UTC offset is not inferred in the Strategy Tester.");
   return INIT_SUCCEEDED;
  }

void OnTick() {}

bool WriteSpec(const int handle,const string key,const string value)
  {
   return FileWrite(handle,key,value)>0;
  }

void OnDeinit(const int reason)
  {
   if(!g_ready || !MQLInfoInteger(MQL_TESTER))
      return;

   datetime availableUntil=TimeCurrent();
   if(availableUntil>InpUntil)
      availableUntil=InpUntil;
   // Exclude the currently forming minute, even when the final tick is at :59.
   datetime lastClosedOpen=(datetime)(((long)availableUntil/60)*60-60);
   if(lastClosedOpen<InpFrom)
     {
      Print("Gold export: no closed bars inside the requested test interval.");
      return;
     }

   MqlRates rates[];
   ArraySetAsSeries(rates,false);
   ResetLastError();
   int count=CopyRates(InpSymbol,PERIOD_M1,InpFrom,lastClosedOpen,rates);
   if(count<=0)
     {
      PrintFormat("Gold export: CopyRates failed, count=%d error=%d.",count,GetLastError());
      return;
     }

   string ratesName="CodexGold_M1_20261026.csv";
   ResetLastError();
   int file=FileOpen(ratesName,FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON,',',CP_UTF8);
   if(file==INVALID_HANDLE)
     {
      PrintFormat("Gold export: cannot open rates file, error=%d.",GetLastError());
      return;
     }
   bool ok=FileWrite(file,"time","open","high","low","close","tick_volume","spread","real_volume")>0;
   int digits=(int)SymbolInfoInteger(InpSymbol,SYMBOL_DIGITS);
   int written=0;
   datetime previous=0;
   for(int i=0;i<count && ok;i++)
     {
      if(rates[i].time<InpFrom || rates[i].time>lastClosedOpen)
         continue;
      if(previous!=0 && rates[i].time<=previous)
        {
         Print("Gold export: non-increasing bar timestamps; export stopped.");
         ok=false;
         break;
        }
      if(FileWrite(file,TimeToString(rates[i].time,TIME_DATE|TIME_MINUTES),
                   DoubleToString(rates[i].open,digits),DoubleToString(rates[i].high,digits),
                   DoubleToString(rates[i].low,digits),DoubleToString(rates[i].close,digits),
                   rates[i].tick_volume,rates[i].spread,rates[i].real_volume)==0)
        {
         ok=false;
         PrintFormat("Gold export: rates write failed at row %d, error=%d.",i,GetLastError());
         break;
        }
      previous=rates[i].time;
      written++;
     }
   FileFlush(file);
   FileClose(file);
   if(!ok || written==0)
     {
      Print("Gold export: rates file is incomplete; do not use it.");
      return;
     }

   string specsName="CodexGold_specs_20261026.csv";
   int specs=FileOpen(specsName,FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON,',',CP_UTF8);
   if(specs==INVALID_HANDLE)
     {
      PrintFormat("Gold export: rates saved but specification file failed, error=%d.",GetLastError());
      return;
     }
   ok=WriteSpec(specs,"key","value");
   ok=WriteSpec(specs,"symbol",InpSymbol) && ok;
   ok=WriteSpec(specs,"time_basis","broker server time; UTC offset unknown") && ok;
   ok=WriteSpec(specs,"spread_basis","MqlRates.spread in points; not an intrabar spread path") && ok;
   ok=WriteSpec(specs,"first_bar",TimeToString(rates[0].time,TIME_DATE|TIME_MINUTES)) && ok;
   ok=WriteSpec(specs,"last_closed_bar",TimeToString(previous,TIME_DATE|TIME_MINUTES)) && ok;
   ok=WriteSpec(specs,"bars_written",IntegerToString(written)) && ok;
   ok=WriteSpec(specs,"point",DoubleToString(SymbolInfoDouble(InpSymbol,SYMBOL_POINT),10)) && ok;
   ok=WriteSpec(specs,"digits",IntegerToString(digits)) && ok;
   ok=WriteSpec(specs,"tick_size",DoubleToString(SymbolInfoDouble(InpSymbol,SYMBOL_TRADE_TICK_SIZE),10)) && ok;
   ok=WriteSpec(specs,"tick_value",DoubleToString(SymbolInfoDouble(InpSymbol,SYMBOL_TRADE_TICK_VALUE),10)) && ok;
   ok=WriteSpec(specs,"tick_value_profit",DoubleToString(SymbolInfoDouble(InpSymbol,SYMBOL_TRADE_TICK_VALUE_PROFIT),10)) && ok;
   ok=WriteSpec(specs,"tick_value_loss",DoubleToString(SymbolInfoDouble(InpSymbol,SYMBOL_TRADE_TICK_VALUE_LOSS),10)) && ok;
   ok=WriteSpec(specs,"contract_size",DoubleToString(SymbolInfoDouble(InpSymbol,SYMBOL_TRADE_CONTRACT_SIZE),8)) && ok;
   ok=WriteSpec(specs,"volume_min",DoubleToString(SymbolInfoDouble(InpSymbol,SYMBOL_VOLUME_MIN),8)) && ok;
   ok=WriteSpec(specs,"volume_step",DoubleToString(SymbolInfoDouble(InpSymbol,SYMBOL_VOLUME_STEP),8)) && ok;
   ok=WriteSpec(specs,"volume_max",DoubleToString(SymbolInfoDouble(InpSymbol,SYMBOL_VOLUME_MAX),8)) && ok;
   ok=WriteSpec(specs,"stops_level_points",IntegerToString(SymbolInfoInteger(InpSymbol,SYMBOL_TRADE_STOPS_LEVEL))) && ok;
   ok=WriteSpec(specs,"trade_calc_mode",IntegerToString(SymbolInfoInteger(InpSymbol,SYMBOL_TRADE_CALC_MODE))) && ok;
   ok=WriteSpec(specs,"chart_mode",IntegerToString(SymbolInfoInteger(InpSymbol,SYMBOL_CHART_MODE))) && ok;
   ok=WriteSpec(specs,"currency_profit",SymbolInfoString(InpSymbol,SYMBOL_CURRENCY_PROFIT)) && ok;
   ok=WriteSpec(specs,"currency_margin",SymbolInfoString(InpSymbol,SYMBOL_CURRENCY_MARGIN)) && ok;
   ok=WriteSpec(specs,"account_currency",AccountInfoString(ACCOUNT_CURRENCY)) && ok;
   ok=WriteSpec(specs,"swap_mode_name",EnumToString((ENUM_SYMBOL_SWAP_MODE)SymbolInfoInteger(InpSymbol,SYMBOL_SWAP_MODE))) && ok;
   ok=WriteSpec(specs,"swap_mode",IntegerToString(SymbolInfoInteger(InpSymbol,SYMBOL_SWAP_MODE))) && ok;
   ok=WriteSpec(specs,"swap_long",DoubleToString(SymbolInfoDouble(InpSymbol,SYMBOL_SWAP_LONG),8)) && ok;
   ok=WriteSpec(specs,"swap_short",DoubleToString(SymbolInfoDouble(InpSymbol,SYMBOL_SWAP_SHORT),8)) && ok;
   ok=WriteSpec(specs,"swap_rollover3days",IntegerToString(SymbolInfoInteger(InpSymbol,SYMBOL_SWAP_ROLLOVER3DAYS))) && ok;
   ok=WriteSpec(specs,"swap_sunday",DoubleToString(SymbolInfoDouble(InpSymbol,SYMBOL_SWAP_SUNDAY),4)) && ok;
   ok=WriteSpec(specs,"swap_monday",DoubleToString(SymbolInfoDouble(InpSymbol,SYMBOL_SWAP_MONDAY),4)) && ok;
   ok=WriteSpec(specs,"swap_tuesday",DoubleToString(SymbolInfoDouble(InpSymbol,SYMBOL_SWAP_TUESDAY),4)) && ok;
   ok=WriteSpec(specs,"swap_wednesday",DoubleToString(SymbolInfoDouble(InpSymbol,SYMBOL_SWAP_WEDNESDAY),4)) && ok;
   ok=WriteSpec(specs,"swap_thursday",DoubleToString(SymbolInfoDouble(InpSymbol,SYMBOL_SWAP_THURSDAY),4)) && ok;
   ok=WriteSpec(specs,"swap_friday",DoubleToString(SymbolInfoDouble(InpSymbol,SYMBOL_SWAP_FRIDAY),4)) && ok;
   ok=WriteSpec(specs,"swap_saturday",DoubleToString(SymbolInfoDouble(InpSymbol,SYMBOL_SWAP_SATURDAY),4)) && ok;
   FileFlush(specs);
   FileClose(specs);
   PrintFormat("Gold export: %s; %d closed M1 bars; first=%s last=%s; files=%s and %s in FILE_COMMON.",
               ok?"complete":"specification file incomplete",written,
               TimeToString(rates[0].time,TIME_DATE|TIME_MINUTES),
               TimeToString(previous,TIME_DATE|TIME_MINUTES),ratesName,specsName);
  }
