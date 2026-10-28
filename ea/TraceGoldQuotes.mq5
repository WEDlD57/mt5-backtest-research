// Original non-trading utility: compress the tester's bid/ask tick stream.
#property strict
#property version "1.00"

int g_file=INVALID_HANDLE;
datetime g_minute=0,g_lastTick=0;
double g_bo=0,g_bh=0,g_bl=0,g_bc=0,g_ao=0,g_ah=0,g_al=0,g_ac=0;
long g_ticks=0,g_rows=0,g_total=0;
int g_minSpread=0;
bool g_ok=true;

void FlushMinute()
  {
   if(g_minute==0 || g_file==INVALID_HANDLE || g_ticks==0) return;
   if(FileWrite(g_file,TimeToString(g_minute,TIME_DATE|TIME_MINUTES),
                DoubleToString(g_bo,_Digits),DoubleToString(g_bh,_Digits),
                DoubleToString(g_bl,_Digits),DoubleToString(g_bc,_Digits),
                DoubleToString(g_ao,_Digits),DoubleToString(g_ah,_Digits),
                DoubleToString(g_al,_Digits),DoubleToString(g_ac,_Digits),
                g_ticks,g_minSpread,TimeToString(g_lastTick,TIME_DATE|TIME_SECONDS))==0)
      g_ok=false;
   g_rows++;
  }

bool ExportSessions()
  {
   int file=FileOpen("CodexGold_trade_sessions_20261028.csv",FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON,',',CP_UTF8);
   if(file==INVALID_HANDLE) return false;
   bool ok=FileWrite(file,"day","index","from_seconds","to_seconds")>0;
   for(int day=0;day<7;day++)
     {
      for(uint index=0;index<20;index++)
        {
         datetime from,to;
         if(!SymbolInfoSessionTrade(_Symbol,(ENUM_DAY_OF_WEEK)day,index,from,to)) break;
         long begin=(long)from,end=(long)to;
         // Session times are seconds from midnight. Preserve 86400, unlike a modulo operation.
         if(begin>86400) begin%=86400;
         if(end>86400) end%=86400;
         if(FileWrite(file,day,index,begin,end)==0) ok=false;
        }
     }
   FileFlush(file);FileClose(file);
   return ok;
  }

int OnInit()
  {
   if(!MQLInfoInteger(MQL_TESTER) || _Symbol!="XAUUSD") return INIT_FAILED;
   if(!ExportSessions()) return INIT_FAILED;
   g_file=FileOpen("CodexGold_QuoteM1_20261028.csv",FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON,',',CP_UTF8);
   if(g_file==INVALID_HANDLE) return INIT_FAILED;
   if(FileWrite(g_file,"time","open","high","low","close","ask_open","ask_high","ask_low","ask_close","tick_volume","spread","last_tick_time")==0) return INIT_FAILED;
   return INIT_SUCCEEDED;
  }

void OnTick()
  {
   MqlTick tick;
   if(!g_ok || !SymbolInfoTick(_Symbol,tick) || tick.bid<=0 || tick.ask<tick.bid) return;
   datetime minute=(datetime)(((long)tick.time/60)*60);
   int spread=(int)MathRound((tick.ask-tick.bid)/_Point);
   if(minute!=g_minute)
     {
      FlushMinute();
      g_minute=minute;g_bo=tick.bid;g_bh=tick.bid;g_bl=tick.bid;
      g_ao=tick.ask;g_ah=tick.ask;g_al=tick.ask;g_ticks=0;g_minSpread=spread;
     }
   g_bh=MathMax(g_bh,tick.bid);g_bl=MathMin(g_bl,tick.bid);g_bc=tick.bid;
   g_ah=MathMax(g_ah,tick.ask);g_al=MathMin(g_al,tick.ask);g_ac=tick.ask;
   g_minSpread=MathMin(g_minSpread,spread);g_lastTick=tick.time;g_ticks++;g_total++;
  }

void OnDeinit(const int reason)
  {
   if(g_file==INVALID_HANDLE) return;
   FlushMinute();FileFlush(g_file);FileClose(g_file);
   PrintFormat("Quote trace %s: %I64d minutes, %I64d ticks; actual tester bid/ask OHLC, broker-server time.",g_ok?"complete":"INCOMPLETE",g_rows,g_total);
  }
