import { useState } from "react";

const screens = ["chart", "screener", "portfolio", "alerts", "news"];

const mockCandles = [
  { o: 60, h: 75, l: 55, c: 70 }, { o: 70, h: 80, l: 65, c: 72 },
  { o: 72, h: 85, l: 68, c: 80 }, { o: 80, h: 88, l: 70, c: 68 },
  { o: 68, h: 74, l: 60, c: 65 }, { o: 65, h: 72, l: 58, c: 71 },
  { o: 71, h: 82, l: 69, c: 79 }, { o: 79, h: 90, l: 75, c: 88 },
  { o: 88, h: 95, l: 82, c: 85 }, { o: 85, h: 92, l: 78, c: 76 },
  { o: 76, h: 80, l: 68, c: 73 }, { o: 73, h: 82, l: 70, c: 81 },
  { o: 81, h: 89, l: 78, c: 87 }, { o: 87, h: 94, l: 84, c: 91 },
  { o: 91, h: 98, l: 86, c: 83 }, { o: 83, h: 88, l: 75, c: 78 },
  { o: 78, h: 85, l: 72, c: 84 }, { o: 84, h: 93, l: 81, c: 92 },
  { o: 92, h: 100, l: 88, c: 96 }, { o: 96, h: 104, l: 90, c: 88 },
];

const watchlist = [
  { sym: "PTT.BK", name: "ปตท.", price: "35.50", chg: "+1.20", pct: "+3.5%", up: true },
  { sym: "CPALL.BK", name: "ซีพีออลล์", price: "58.25", chg: "-0.75", pct: "-1.3%", up: false },
  { sym: "AAPL", name: "Apple Inc.", price: "187.42", chg: "+2.18", pct: "+1.2%", up: true },
  { sym: "NVDA", name: "NVIDIA", price: "824.15", chg: "+12.30", pct: "+1.5%", up: true },
  { sym: "TSLA", name: "Tesla", price: "195.60", chg: "-4.40", pct: "-2.2%", up: false },
  { sym: "SCB.BK", name: "ไทยพาณิชย์", price: "108.00", chg: "+0.50", pct: "+0.5%", up: true },
];

const indicators = ["MA 20", "EMA 50", "RSI 14", "MACD", "BB"];
const timeframes = ["1m", "5m", "15m", "1h", "4h", "1D", "1W", "1M"];
const drawingTools = ["✏️ Trend", "📐 Fib", "⬜ Rect", "➡️ Arrow", "📏 H-Line", "🔀 Fork"];

const news = [
  { tag: "SET", title: "ตลาดหุ้นไทยปิดบวก 8 จุด หลังต่างชาติซื้อสุทธิ", time: "10 นาทีที่แล้ว", sentiment: "positive" },
  { tag: "US", title: "Fed signals rate cut possible in Q2 2026", time: "25 นาทีที่แล้ว", sentiment: "positive" },
  { tag: "PTT", title: "ปตท.ประกาศปันผลระหว่างกาล 1.50 บาท/หุ้น", time: "1 ชม.ที่แล้ว", sentiment: "positive" },
  { tag: "TSLA", title: "Tesla misses Q4 delivery estimates by 5%", time: "2 ชม.ที่แล้ว", sentiment: "negative" },
  { tag: "NVDA", title: "NVIDIA announces next-gen GPU with 3x performance gain", time: "3 ชม.ที่แล้ว", sentiment: "positive" },
];

const portfolio = [
  { sym: "PTT.BK", qty: 2000, avg: 32.00, curr: 35.50, pl: "+7,000", plPct: "+10.9%", up: true },
  { sym: "CPALL.BK", qty: 500, avg: 60.00, curr: 58.25, pl: "-875", plPct: "-2.9%", up: false },
  { sym: "AAPL", qty: 10, avg: 175.00, curr: 187.42, pl: "+1,242", plPct: "+7.1%", up: true },
  { sym: "NVDA", qty: 5, avg: 700.00, curr: 824.15, pl: "+621", plPct: "+17.7%", up: true },
];

const screenerResults = [
  { sym: "ADVANC.BK", name: "แอดวานซ์ฯ", rsi: 28, macd: "Buy", vol: "3.2x", price: "195.00", signal: "Strong Buy" },
  { sym: "TRUE.BK", name: "ทรู คอร์ปฯ", rsi: 31, macd: "Buy", vol: "2.1x", price: "8.45", signal: "Buy" },
  { sym: "META", name: "Meta Platforms", rsi: 29, macd: "Buy", vol: "1.8x", price: "502.30", signal: "Strong Buy" },
  { sym: "GOOGL", name: "Alphabet", rsi: 33, macd: "Neutral", vol: "1.5x", price: "174.20", signal: "Buy" },
];

const alerts = [
  { sym: "PTT.BK", type: "Price Above", value: "38.00", status: "active", method: "Telegram" },
  { sym: "NVDA", type: "RSI Below", value: "30", status: "active", method: "Telegram" },
  { sym: "AAPL", type: "Golden Cross", value: "MA20 × MA50", status: "triggered", method: "Telegram" },
];

function CandleChart({ compact }) {
  const h = compact ? 100 : 180;
  const maxH = 104, minL = 55, range = maxH - minL;
  const w = 560, candleW = compact ? 16 : 22, gap = compact ? 4 : 6;
  return (
    <svg width="100%" height={h} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
      {/* Grid lines */}
      {[0.2, 0.4, 0.6, 0.8].map(r => (
        <line key={r} x1="0" y1={h * r} x2={w} y2={h * r} stroke="#ffffff08" strokeWidth="1" />
      ))}
      {/* MA line (mock) */}
      <polyline
        points={mockCandles.map((c, i) => {
          const x = i * (candleW + gap) + candleW / 2 + 10;
          const y = h - ((c.c - minL) / range) * (h - 20) - 10;
          return `${x},${y}`;
        }).join(" ")}
        fill="none" stroke="#60a5fa" strokeWidth="1.5" opacity="0.7"
      />
      {/* Candles */}
      {mockCandles.map((c, i) => {
        const x = i * (candleW + gap) + 10;
        const up = c.c >= c.o;
        const col = up ? "#34d399" : "#f87171";
        const top = h - ((Math.max(c.o, c.c) - minL) / range) * (h - 20) - 10;
        const bot = h - ((Math.min(c.o, c.c) - minL) / range) * (h - 20) - 10;
        const hTop = h - ((c.h - minL) / range) * (h - 20) - 10;
        const lBot = h - ((c.l - minL) / range) * (h - 20) - 10;
        return (
          <g key={i}>
            <line x1={x + candleW / 2} y1={hTop} x2={x + candleW / 2} y2={lBot} stroke={col} strokeWidth="1" />
            <rect x={x} y={top} width={candleW} height={Math.max(bot - top, 1)} fill={col} rx="1" />
          </g>
        );
      })}
    </svg>
  );
}

function VolumeBar({ compact }) {
  const h = compact ? 30 : 45;
  const vols = [60, 80, 55, 90, 45, 70, 85, 40, 95, 65, 50, 75, 88, 60, 72, 55, 80, 92, 100, 68];
  const colors = mockCandles.map(c => c.c >= c.o ? "#34d39966" : "#f8717166");
  const w = 560, bw = 22, gap = 6;
  return (
    <svg width="100%" height={h} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
      {vols.map((v, i) => (
        <rect key={i} x={i * (bw + gap) + 10} y={h - (v / 100) * h} width={bw} height={(v / 100) * h} fill={colors[i]} rx="1" />
      ))}
    </svg>
  );
}

export default function Wireframe() {
  const [screen, setScreen] = useState("chart");
  const [selectedTF, setSelectedTF] = useState("1D");
  const [selectedDraw, setSelectedDraw] = useState(null);
  const [activeTab, setActiveTab] = useState("news");
  const [darkMode, setDarkMode] = useState(true);
  const [selectedStock, setSelectedStock] = useState(watchlist[0]);
  const [showModal, setShowModal] = useState(false);

  const bg = darkMode ? "bg-[#0d0f17]" : "bg-gray-100";
  const panel = darkMode ? "bg-[#131620]" : "bg-white";
  const border = darkMode ? "border-[#1e2235]" : "border-gray-200";
  const text = darkMode ? "text-gray-100" : "text-gray-800";
  const sub = darkMode ? "text-gray-400" : "text-gray-500";
  const hover = darkMode ? "hover:bg-[#1e2235]" : "hover:bg-gray-50";

  return (
    <div className={`${bg} ${text} h-screen flex flex-col overflow-hidden font-sans`} style={{ fontFamily: "'Inter', sans-serif" }}>

      {/* TOP NAV */}
      <nav className={`${panel} border-b ${border} flex items-center justify-between px-4 py-2 z-50`} style={{ height: 52 }}>
        <div className="flex items-center gap-6">
          {/* Logo */}
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg flex items-center justify-center text-white text-sm font-bold" style={{ background: "linear-gradient(135deg,#6366f1,#8b5cf6)" }}>S</div>
            <span className="font-bold text-sm tracking-wide">StockViz</span>
            <span className="text-xs px-1.5 py-0.5 rounded bg-violet-500/20 text-violet-400 font-medium">BETA</span>
          </div>

          {/* Nav links */}
          {[
            { id: "chart", label: "📈 Chart" },
            { id: "screener", label: "🔍 Screener" },
            { id: "portfolio", label: "💼 Portfolio" },
            { id: "alerts", label: "🔔 Alerts" },
            { id: "news", label: "📰 News" },
          ].map(n => (
            <button key={n.id} onClick={() => setScreen(n.id)}
              className={`text-xs px-3 py-1.5 rounded-lg font-medium transition-all ${screen === n.id ? "bg-violet-600 text-white" : `${sub} ${hover}`}`}>
              {n.label}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-3">
          {/* Search */}
          <div className={`flex items-center gap-2 px-3 py-1.5 rounded-xl border ${border} ${darkMode ? "bg-[#1a1d2e]" : "bg-gray-50"}`} style={{ width: 220 }}>
            <span className="text-gray-500 text-xs">🔍</span>
            <span className={`text-xs ${sub}`}>ค้นหา PTT, AAPL...</span>
            <span className={`ml-auto text-xs ${sub} opacity-60`}>⌘K</span>
          </div>

          {/* Market status */}
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-green-500/10">
            <div className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
            <span className="text-xs text-green-400 font-medium">SET Open</span>
          </div>

          {/* Dark mode */}
          <button onClick={() => setDarkMode(!darkMode)}
            className={`w-8 h-8 rounded-lg flex items-center justify-center ${hover} text-sm`}>
            {darkMode ? "☀️" : "🌙"}
          </button>

          {/* User avatar */}
          <div className="w-8 h-8 rounded-full flex items-center justify-center text-white text-xs font-bold" style={{ background: "linear-gradient(135deg,#6366f1,#8b5cf6)" }}>S</div>
        </div>
      </nav>

      {/* BODY */}
      <div className="flex flex-1 overflow-hidden">

        {/* SIDEBAR — Watchlist */}
        <aside className={`${panel} border-r ${border} flex flex-col overflow-hidden`} style={{ width: 220, minWidth: 220 }}>
          <div className={`flex items-center justify-between px-3 py-2.5 border-b ${border}`}>
            <span className="text-xs font-semibold tracking-wider text-gray-500 uppercase">Watchlist</span>
            <button className="text-violet-400 text-lg leading-none">+</button>
          </div>

          {/* Market indices */}
          <div className={`px-3 py-2 border-b ${border}`}>
            {[
              { name: "SET", val: "1,485.20", chg: "+8.30", up: true },
              { name: "S&P500", val: "5,234.10", chg: "+12.40", up: true },
              { name: "NASDAQ", val: "16,420.50", chg: "-45.20", up: false },
            ].map(idx => (
              <div key={idx.name} className="flex justify-between items-center py-0.5">
                <span className="text-xs font-medium text-gray-500">{idx.name}</span>
                <div className="text-right">
                  <div className="text-xs font-medium">{idx.val}</div>
                  <div className={`text-xs ${idx.up ? "text-green-400" : "text-red-400"}`}>{idx.chg}</div>
                </div>
              </div>
            ))}
          </div>

          {/* Stock list */}
          <div className="flex-1 overflow-y-auto">
            {watchlist.map(s => (
              <button key={s.sym} onClick={() => { setSelectedStock(s); setScreen("chart"); }}
                className={`w-full flex items-center justify-between px-3 py-2.5 ${hover} transition-all ${selectedStock.sym === s.sym && screen === "chart" ? (darkMode ? "bg-violet-900/30 border-r-2 border-violet-500" : "bg-violet-50 border-r-2 border-violet-500") : ""}`}>
                <div className="text-left">
                  <div className="text-xs font-semibold">{s.sym.replace(".BK", "")}</div>
                  <div className={`text-xs ${sub} truncate`} style={{ maxWidth: 90 }}>{s.name}</div>
                </div>
                <div className="text-right">
                  <div className="text-xs font-medium">{s.price}</div>
                  <div className={`text-xs font-medium ${s.up ? "text-green-400" : "text-red-400"}`}>{s.pct}</div>
                </div>
              </button>
            ))}
          </div>

          {/* Add stock button */}
          <div className={`p-3 border-t ${border}`}>
            <button className={`w-full py-2 text-xs text-violet-400 border border-violet-500/30 rounded-xl hover:bg-violet-500/10 transition-all`}>
              + เพิ่มหุ้น
            </button>
          </div>
        </aside>

        {/* MAIN CONTENT */}
        <main className="flex-1 flex flex-col overflow-hidden">

          {/* ─── CHART SCREEN ─── */}
          {screen === "chart" && (
            <div className="flex flex-1 overflow-hidden">
              <div className="flex-1 flex flex-col overflow-hidden">

                {/* Chart toolbar */}
                <div className={`${panel} border-b ${border} flex items-center gap-3 px-4 py-2 flex-wrap`}>
                  {/* Stock info */}
                  <div className="flex items-center gap-2 mr-2">
                    <span className="font-bold text-sm">{selectedStock.sym}</span>
                    <span className={`text-sm font-bold ${selectedStock.up ? "text-green-400" : "text-red-400"}`}>{selectedStock.price}</span>
                    <span className={`text-xs px-2 py-0.5 rounded-full ${selectedStock.up ? "bg-green-500/15 text-green-400" : "bg-red-500/15 text-red-400"}`}>
                      {selectedStock.chg} {selectedStock.pct}
                    </span>
                  </div>

                  <div className={`h-4 w-px ${border} mx-1`} />

                  {/* Timeframes */}
                  <div className="flex gap-1">
                    {timeframes.map(tf => (
                      <button key={tf} onClick={() => setSelectedTF(tf)}
                        className={`text-xs px-2 py-1 rounded-lg font-medium transition-all ${selectedTF === tf ? "bg-violet-600 text-white" : `${sub} ${hover}`}`}>
                        {tf}
                      </button>
                    ))}
                  </div>

                  <div className={`h-4 w-px ${border} mx-1`} />

                  {/* Chart type */}
                  <div className="flex gap-1">
                    {["🕯️", "📉", "▬"].map((t, i) => (
                      <button key={i} className={`text-sm px-2 py-1 rounded-lg ${i === 0 ? "bg-violet-600" : hover}`}>{t}</button>
                    ))}
                  </div>

                  <div className={`h-4 w-px ${border} mx-1`} />

                  {/* Indicators */}
                  <div className="flex gap-1">
                    {indicators.map(ind => (
                      <button key={ind} className={`text-xs px-2 py-0.5 rounded-full border ${border} ${sub} ${hover} transition-all`}>{ind}</button>
                    ))}
                    <button className="text-xs px-2 py-0.5 rounded-full bg-violet-500/20 text-violet-400">+ Add</button>
                  </div>
                </div>

                {/* Drawing toolbar */}
                <div className={`${panel} border-b ${border} flex items-center gap-2 px-4 py-1.5`}>
                  <span className={`text-xs ${sub} mr-1`}>Drawing:</span>
                  {drawingTools.map(d => (
                    <button key={d} onClick={() => setSelectedDraw(selectedDraw === d ? null : d)}
                      className={`text-xs px-2.5 py-1 rounded-lg transition-all ${selectedDraw === d ? "bg-yellow-500/20 text-yellow-400 border border-yellow-500/30" : `${sub} ${hover}`}`}>
                      {d}
                    </button>
                  ))}
                  <div className="ml-auto flex gap-2">
                    <button className={`text-xs px-2.5 py-1 rounded-lg ${sub} ${hover}`}>🗑️ Clear</button>
                    <button className={`text-xs px-2.5 py-1 rounded-lg ${sub} ${hover}`}>💾 Save</button>
                  </div>
                </div>

                {/* Chart area */}
                <div className="flex-1 overflow-hidden relative" style={{ background: darkMode ? "#0d0f17" : "#f8f9fc" }}>
                  {/* Price labels */}
                  <div className={`absolute right-0 top-0 bottom-0 flex flex-col justify-between py-2 pr-2 ${sub} text-xs`} style={{ width: 55 }}>
                    {["104", "93", "82", "71", "60"].map(p => <span key={p}>{p}</span>)}
                  </div>

                  {/* Main chart */}
                  <div className="absolute inset-0 pr-14 pt-2">
                    <CandleChart />
                    {/* Mock drawn line */}
                    <svg className="absolute inset-0 w-full h-full pointer-events-none">
                      <line x1="5%" y1="35%" x2="90%" y2="20%" stroke="#f59e0b" strokeWidth="1.5" strokeDasharray="4,2" opacity="0.8" />
                      <line x1="5%" y1="55%" x2="90%" y2="55%" stroke="#60a5fa" strokeWidth="1" strokeDasharray="6,3" opacity="0.6" />
                      <text x="91%" y="20%" fill="#f59e0b" fontSize="9" opacity="0.8">Trend</text>
                      <text x="91%" y="55%" fill="#60a5fa" fontSize="9" opacity="0.6">Support</text>
                    </svg>

                    {/* Volume */}
                    <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, height: 50 }}>
                      <VolumeBar />
                    </div>
                  </div>

                  {/* Crosshair info box */}
                  <div className={`absolute top-4 left-4 ${darkMode ? "bg-[#1e2235]" : "bg-white"} border ${border} rounded-xl px-3 py-2 text-xs`}>
                    <div className="flex gap-3">
                      <span>O: <span className="text-green-400">88.00</span></span>
                      <span>H: <span className="text-green-400">104.00</span></span>
                      <span>L: <span className="text-red-400">86.00</span></span>
                      <span>C: <span className="text-green-400">96.00</span></span>
                      <span className={sub}>Vol: 2.4M</span>
                    </div>
                  </div>

                  {/* XD marker (Thai specific) */}
                  <div className="absolute" style={{ left: "72%", top: 10 }}>
                    <div className="text-xs bg-yellow-500/20 text-yellow-400 px-1.5 py-0.5 rounded border border-yellow-500/30">XD 1.50฿</div>
                    <div className="w-px bg-yellow-400/30 mx-auto" style={{ height: 140 }} />
                  </div>
                </div>

                {/* Bottom panel */}
                <div className={`${panel} border-t ${border}`} style={{ height: 160 }}>
                  <div className={`flex border-b ${border}`}>
                    {["📰 News", "💼 Portfolio", "📊 Fundamentals"].map(t => (
                      <button key={t} onClick={() => setActiveTab(t.split(" ")[1].toLowerCase())}
                        className={`text-xs px-4 py-2 font-medium transition-all ${activeTab === t.split(" ")[1].toLowerCase() ? "border-b-2 border-violet-500 text-violet-400" : sub}`}>
                        {t}
                      </button>
                    ))}
                  </div>

                  <div className="overflow-y-auto p-3" style={{ height: 120 }}>
                    {activeTab === "news" && (
                      <div className="flex flex-col gap-1.5">
                        {news.slice(0, 3).map((n, i) => (
                          <div key={i} className={`flex items-start gap-2 p-2 rounded-lg ${hover} cursor-pointer`}>
                            <span className={`text-xs px-1.5 py-0.5 rounded font-medium flex-shrink-0 ${n.sentiment === "positive" ? "bg-green-500/15 text-green-400" : "bg-red-500/15 text-red-400"}`}>{n.tag}</span>
                            <span className="text-xs flex-1">{n.title}</span>
                            <span className={`text-xs ${sub} flex-shrink-0`}>{n.time}</span>
                          </div>
                        ))}
                      </div>
                    )}
                    {activeTab === "portfolio" && (
                      <div className={`text-xs ${sub} text-center py-4`}>เข้าสู่ระบบเพื่อดูพอร์ต</div>
                    )}
                    {activeTab === "fundamentals" && (
                      <div className="grid grid-cols-4 gap-3">
                        {[["P/E", "18.5x"], ["P/BV", "1.2x"], ["Div Yield", "4.8%"], ["Mkt Cap", "450B"]].map(([k, v]) => (
                          <div key={k} className={`${darkMode ? "bg-[#1a1d2e]" : "bg-gray-50"} rounded-xl p-2`}>
                            <div className={`text-xs ${sub}`}>{k}</div>
                            <div className="text-sm font-bold mt-0.5">{v}</div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </div>

              {/* Right panel */}
              <aside className={`${panel} border-l ${border} overflow-y-auto`} style={{ width: 200 }}>
                {/* Alert shortcut */}
                <div className="p-3 border-b border-[#1e2235]">
                  <div className={`text-xs ${sub} mb-2 font-semibold uppercase tracking-wider`}>Quick Alert</div>
                  <div className={`flex items-center gap-2 px-3 py-2 rounded-xl border ${border} ${darkMode ? "bg-[#1a1d2e]" : "bg-gray-50"} text-xs mb-2`}>
                    <span className={sub}>฿</span>
                    <span className={sub}>Target price...</span>
                  </div>
                  <button className="w-full py-1.5 text-xs bg-violet-600 hover:bg-violet-700 text-white rounded-xl transition-all">+ Set Alert</button>
                </div>

                {/* Stats */}
                <div className="p-3">
                  <div className={`text-xs ${sub} mb-2 font-semibold uppercase tracking-wider`}>Stats</div>
                  {[
                    ["52W High", "42.75"],
                    ["52W Low", "28.50"],
                    ["Avg Vol", "5.2M"],
                    ["Beta", "0.85"],
                    ["EPS", "2.15"],
                  ].map(([k, v]) => (
                    <div key={k} className="flex justify-between py-1.5 border-b border-[#ffffff06]">
                      <span className={`text-xs ${sub}`}>{k}</span>
                      <span className="text-xs font-medium">{v}</span>
                    </div>
                  ))}
                </div>

                {/* RSI gauge */}
                <div className="px-3 pb-3">
                  <div className={`text-xs ${sub} mb-2 font-semibold uppercase tracking-wider`}>RSI (14)</div>
                  <div className="relative">
                    <div className="h-2 rounded-full overflow-hidden" style={{ background: "linear-gradient(to right, #f87171, #facc15, #34d399)" }}>
                      <div className="absolute top-1/2 -translate-y-1/2 w-3 h-3 rounded-full bg-white border-2 border-violet-500 shadow" style={{ left: "58%" }} />
                    </div>
                    <div className="flex justify-between mt-1">
                      <span className="text-xs text-red-400">Oversold</span>
                      <span className="text-xs font-bold text-yellow-400">58.2</span>
                      <span className="text-xs text-green-400">Overbought</span>
                    </div>
                  </div>
                </div>
              </aside>
            </div>
          )}

          {/* ─── SCREENER SCREEN ─── */}
          {screen === "screener" && (
            <div className="flex-1 overflow-auto p-6">
              <div className="max-w-5xl mx-auto">
                <div className="flex items-center justify-between mb-4">
                  <div>
                    <h2 className="text-lg font-bold">🔍 Stock Screener</h2>
                    <p className={`text-xs ${sub}`}>กรองหุ้นด้วยเงื่อนไขที่ต้องการ</p>
                  </div>
                  <div className="flex gap-2">
                    <button className={`text-xs px-3 py-1.5 rounded-xl border ${border} ${sub} ${hover}`}>💾 Save Filter</button>
                    <button className="text-xs px-3 py-1.5 rounded-xl bg-violet-600 text-white hover:bg-violet-700">▶ Run Screen</button>
                  </div>
                </div>

                {/* Filters */}
                <div className={`${panel} rounded-2xl border ${border} p-4 mb-4`}>
                  <div className="grid grid-cols-3 gap-3">
                    {[
                      ["Market", "SET + US"],
                      ["RSI", "< 30 (Oversold)"],
                      ["Volume", "> 2x Average"],
                      ["MACD", "Buy Signal"],
                      ["Price", "> MA200"],
                      ["Market Cap", "> 10B"],
                    ].map(([label, val]) => (
                      <div key={label} className={`${darkMode ? "bg-[#1a1d2e]" : "bg-gray-50"} rounded-xl p-3`}>
                        <div className={`text-xs ${sub} mb-1`}>{label}</div>
                        <div className="text-xs font-semibold text-violet-400">{val}</div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Results table */}
                <div className={`${panel} rounded-2xl border ${border} overflow-hidden`}>
                  <div className={`px-4 py-3 border-b ${border} flex items-center justify-between`}>
                    <span className="text-xs font-semibold">ผลลัพธ์ {screenerResults.length} หุ้น</span>
                    <button className={`text-xs ${sub} ${hover} px-2 py-1 rounded-lg`}>📥 Export CSV</button>
                  </div>
                  <table className="w-full">
                    <thead>
                      <tr className={`text-xs ${sub} border-b ${border}`}>
                        {["Symbol", "ชื่อบริษัท", "ราคา", "RSI", "MACD", "Volume", "Signal"].map(h => (
                          <th key={h} className="text-left px-4 py-2 font-medium">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {screenerResults.map(r => (
                        <tr key={r.sym} className={`border-b ${border} ${hover} cursor-pointer text-xs`}
                          onClick={() => { setSelectedStock({ sym: r.sym, name: r.name, price: r.price, chg: "+2.5", pct: "+1.3%", up: true }); setScreen("chart"); }}>
                          <td className="px-4 py-3 font-semibold text-violet-400">{r.sym}</td>
                          <td className={`px-4 py-3 ${sub}`}>{r.name}</td>
                          <td className="px-4 py-3 font-medium">{r.price}</td>
                          <td className="px-4 py-3 text-green-400 font-medium">{r.rsi}</td>
                          <td className="px-4 py-3 text-green-400">{r.macd}</td>
                          <td className="px-4 py-3 text-yellow-400">{r.vol}</td>
                          <td className="px-4 py-3">
                            <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${r.signal === "Strong Buy" ? "bg-green-500/20 text-green-400" : "bg-blue-500/20 text-blue-400"}`}>
                              {r.signal}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* ─── PORTFOLIO SCREEN ─── */}
          {screen === "portfolio" && (
            <div className="flex-1 overflow-auto p-6">
              <div className="max-w-5xl mx-auto">
                <h2 className="text-lg font-bold mb-4">💼 Portfolio</h2>

                {/* Summary cards */}
                <div className="grid grid-cols-4 gap-4 mb-6">
                  {[
                    { label: "มูลค่าพอร์ต", val: "฿284,520", sub: "ราคาตลาด", color: "text-white" },
                    { label: "กำไร/ขาดทุน", val: "+฿7,988", sub: "+2.89%", color: "text-green-400" },
                    { label: "วันนี้", val: "+฿1,240", sub: "+0.44%", color: "text-green-400" },
                    { label: "Sharpe Ratio", val: "1.24", sub: "ดี (> 1.0)", color: "text-blue-400" },
                  ].map(c => (
                    <div key={c.label} className={`${panel} rounded-2xl border ${border} p-4`}>
                      <div className={`text-xs ${sub} mb-1`}>{c.label}</div>
                      <div className={`text-xl font-bold ${c.color}`}>{c.val}</div>
                      <div className={`text-xs ${sub} mt-0.5`}>{c.sub}</div>
                    </div>
                  ))}
                </div>

                {/* Holdings */}
                <div className={`${panel} rounded-2xl border ${border} overflow-hidden`}>
                  <div className={`px-4 py-3 border-b ${border}`}>
                    <span className="text-xs font-semibold">Holdings ({portfolio.length} ตัว)</span>
                  </div>
                  <table className="w-full">
                    <thead>
                      <tr className={`text-xs ${sub} border-b ${border}`}>
                        {["Symbol", "จำนวน", "ราคาเฉลี่ย", "ราคาปัจจุบัน", "P&L", "%"].map(h => (
                          <th key={h} className="text-left px-4 py-2 font-medium">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {portfolio.map(p => (
                        <tr key={p.sym} className={`border-b ${border} ${hover} text-xs cursor-pointer`}
                          onClick={() => { setSelectedStock(watchlist.find(w => w.sym === p.sym) || watchlist[0]); setScreen("chart"); }}>
                          <td className="px-4 py-3 font-semibold text-violet-400">{p.sym}</td>
                          <td className="px-4 py-3">{p.qty.toLocaleString()}</td>
                          <td className={`px-4 py-3 ${sub}`}>{p.avg.toFixed(2)}</td>
                          <td className="px-4 py-3 font-medium">{p.curr}</td>
                          <td className={`px-4 py-3 font-medium ${p.up ? "text-green-400" : "text-red-400"}`}>{p.pl}</td>
                          <td className={`px-4 py-3 font-medium ${p.up ? "text-green-400" : "text-red-400"}`}>{p.plPct}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* ─── ALERTS SCREEN ─── */}
          {screen === "alerts" && (
            <div className="flex-1 overflow-auto p-6">
              <div className="max-w-3xl mx-auto">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-lg font-bold">🔔 Price Alerts</h2>
                  <button onClick={() => setShowModal(true)} className="text-xs px-4 py-2 bg-violet-600 hover:bg-violet-700 text-white rounded-xl">+ สร้าง Alert</button>
                </div>

                <div className="flex flex-col gap-3">
                  {alerts.map((a, i) => (
                    <div key={i} className={`${panel} border ${border} rounded-2xl px-4 py-3 flex items-center gap-4`}>
                      <div className={`w-2 h-2 rounded-full flex-shrink-0 ${a.status === "active" ? "bg-green-400 animate-pulse" : "bg-yellow-400"}`} />
                      <div className="flex-1">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-bold text-violet-400">{a.sym}</span>
                          <span className={`text-xs px-2 py-0.5 rounded-full border ${border} ${sub}`}>{a.type}</span>
                        </div>
                        <div className={`text-xs ${sub} mt-0.5`}>เงื่อนไข: {a.value}</div>
                      </div>
                      <div className="text-right">
                        <div className={`text-xs mb-1 ${a.status === "triggered" ? "text-yellow-400" : "text-green-400"}`}>
                          {a.status === "triggered" ? "✅ Triggered" : "● Active"}
                        </div>
                        <div className={`text-xs ${sub}`}>via {a.method}</div>
                      </div>
                      <button className={`text-xs px-3 py-1 rounded-lg ${hover} ${sub}`}>✕</button>
                    </div>
                  ))}
                </div>
              </div>

              {/* Modal */}
              {showModal && (
                <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
                  <div className={`${panel} rounded-2xl border ${border} p-6 w-96`}>
                    <h3 className="font-bold mb-4">สร้าง Alert ใหม่</h3>
                    <div className="flex flex-col gap-3">
                      {[["Symbol", "เช่น PTT.BK"], ["Alert Type", "Price / RSI / Pattern"], ["Value", "เช่น 40.00"]].map(([l, ph]) => (
                        <div key={l}>
                          <div className={`text-xs ${sub} mb-1`}>{l}</div>
                          <div className={`px-3 py-2 rounded-xl border ${border} ${darkMode ? "bg-[#1a1d2e]" : "bg-gray-50"} text-xs ${sub}`}>{ph}</div>
                        </div>
                      ))}
                      <div className="flex gap-2 mt-2">
                        <button onClick={() => setShowModal(false)} className={`flex-1 py-2 text-xs rounded-xl border ${border} ${sub} ${hover}`}>ยกเลิก</button>
                        <button onClick={() => setShowModal(false)} className="flex-1 py-2 text-xs bg-violet-600 text-white rounded-xl hover:bg-violet-700">สร้าง Alert</button>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* ─── NEWS SCREEN ─── */}
          {screen === "news" && (
            <div className="flex-1 overflow-auto p-6">
              <div className="max-w-4xl mx-auto">
                <h2 className="text-lg font-bold mb-4">📰 ข่าวและบทวิเคราะห์</h2>
                <div className="flex gap-2 mb-4">
                  {["ทั้งหมด", "SET", "US", "Watchlist"].map(tag => (
                    <button key={tag} className={`text-xs px-3 py-1.5 rounded-xl border ${border} ${sub} ${hover}`}>{tag}</button>
                  ))}
                </div>
                <div className="flex flex-col gap-3">
                  {[...news, ...news].slice(0, 7).map((n, i) => (
                    <div key={i} className={`${panel} border ${border} rounded-2xl p-4 ${hover} cursor-pointer`}>
                      <div className="flex items-start gap-3">
                        <span className={`text-xs px-2 py-0.5 rounded font-medium flex-shrink-0 mt-0.5 ${n.sentiment === "positive" ? "bg-green-500/15 text-green-400" : "bg-red-500/15 text-red-400"}`}>{n.tag}</span>
                        <div className="flex-1">
                          <div className="text-sm font-medium mb-1">{n.title}</div>
                          <div className={`text-xs ${sub}`}>{n.time}</div>
                        </div>
                        <div className={`text-xs px-2 py-0.5 rounded-full flex-shrink-0 ${n.sentiment === "positive" ? "bg-green-500/10 text-green-400" : "bg-red-500/10 text-red-400"}`}>
                          {n.sentiment === "positive" ? "😊 Positive" : "😟 Negative"}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </main>
      </div>

      {/* Status bar */}
      <div className={`${panel} border-t ${border} flex items-center justify-between px-4 py-1`}>
        <div className="flex items-center gap-4">
          <span className="text-xs text-green-400">● Live</span>
          <span className={`text-xs ${sub}`}>อัปเดตล่าสุด: 13:42:05</span>
        </div>
        <div className={`text-xs ${sub}`}>StockViz v0.1 · Data: yfinance + Finnhub · Delayed 15min (Guest)</div>
      </div>
    </div>
  );
}
