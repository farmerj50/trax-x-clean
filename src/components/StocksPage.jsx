/* eslint-disable no-template-curly-in-string, react-hooks/exhaustive-deps */
import React, { useEffect, useMemo, useRef, useState } from "react";
import LiveStockUpdate from "./LiveStockUpdate";
import AddTicker from "./AddTicker";
import MarketSignalsFeed from "./MarketSignalsFeed";
import "./StocksPage.css";
import { apiFetch } from "../apiClient";

import {
  StockChartComponent,
  StockChartSeriesCollectionDirective,
  StockChartSeriesDirective,
  Inject,
  DateTime,
  Tooltip,
  RangeTooltip,
  Crosshair,
  LineSeries,
  CandleSeries,
  Legend,
  Export,
  MacdIndicator,
  RsiIndicator,
  ScatterSeries
} from "@syncfusion/ej2-react-charts";

const POLYGON_WS_URL = "wss://delayed.polygon.io/stocks"; // 15-min delayed data
const POLYGON_API_KEY = process.env.REACT_APP_POLYGON_API_KEY;

const clamp = (n, lo, hi) => Math.max(lo, Math.min(hi, n));
const fmtPrice = (value) => (Number.isFinite(Number(value)) ? Number(value).toFixed(2) : "-");
const fmtPct = (value) => `${Number(value || 0).toFixed(2)}%`;
const fmtVolume = (value) => {
  const n = Number(value || 0);
  if (!Number.isFinite(n)) return "-";
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(2)}B`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return `${Math.round(n)}`;
};

const ema = (values, period) => {
  if (!values.length) return 0;
  const k = 2 / (period + 1);
  let e = values[0];
  for (let i = 1; i < values.length; i += 1) e = values[i] * k + e * (1 - k);
  return e;
};

const rsi = (closes, period = 14) => {
  if (closes.length < period + 1) return 50;
  let gains = 0;
  let losses = 0;
  for (let i = closes.length - period; i < closes.length; i += 1) {
    const diff = closes[i] - closes[i - 1];
    if (diff >= 0) gains += diff;
    else losses -= diff;
  }
  const rs = losses === 0 ? 999 : gains / losses;
  return 100 - 100 / (1 + rs);
};

const computePhase = (candles, vwapVal) => {
  if (!candles || candles.length < 30) return { phase: "Insufficient Data" };

  const closes = candles.map((c) => c.c);
  const highs = candles.map((c) => c.h);
  const lows = candles.map((c) => c.l);
  const volumes = candles.map((c) => c.v || 0);
  const last = candles[candles.length - 1];

  const high20 = Math.max(...highs.slice(-20));
  const low20 = Math.min(...lows.slice(-20));
  const rangePct = last.c > 0 ? (high20 - low20) / last.c : 999;
  const avgVol10 = volumes.slice(-10).reduce((a, b) => a + b, 0) / 10;
  const volumeSpike = (last.v || 0) > avgVol10 * 1.5;
  const ema9 = ema(closes.slice(-30), 9);
  const ema21 = ema(closes.slice(-50), 21);
  const distanceFromVWAP = vwapVal > 0 ? (last.c - vwapVal) / vwapVal : 0;
  const r = rsi(closes, 14);

  const isCompression =
    rangePct < 0.012 &&
    Math.abs(ema9 - ema21) / Math.max(last.c, 1e-6) < 0.002 &&
    last.c >= high20 * 0.99;

  const isEarlyExpansion =
    last.c > high20 &&
    volumeSpike &&
    last.c > vwapVal &&
    ema9 > ema21;

  const isTrend =
    ema9 > ema21 &&
    last.c > vwapVal &&
    distanceFromVWAP < 0.05;

  const isExhaustion =
    distanceFromVWAP > 0.05 &&
    volumeSpike &&
    r > 78;

  let phase = "Neutral / Chop";
  if (isExhaustion) phase = "Exhaustion";
  else if (isEarlyExpansion) phase = "Early Expansion";
  else if (isTrend) phase = "Trend Expansion";
  else if (isCompression) phase = "Compression";

  return { phase, high20, low20, rangePct, volumeSpike, ema9, ema21, distanceFromVWAP };
};

const swingLow = (candles, lookback = 10) => {
  const slice = candles.slice(-lookback);
  return Math.min(...slice.map((c) => c.l));
};

const swingHigh = (candles, lookback = 10) => {
  const slice = candles.slice(-lookback);
  return Math.max(...slice.map((c) => c.h));
};

const percentOf = (value, pct) => value * (pct / 100);

const computeTradePlan = ({ candles, vwap, ema9, ema21, phase, moveTodayPct = 0, distanceFromVwap = 0 }) => {
  if (!candles || candles.length < 20) {
    return {
      planLabel: "No Plan",
      entry: null,
      stop: null,
      targets: null,
      live: { price: candles?.[candles.length - 1]?.c ?? null, rMultiple: null, guidance: "WAIT" },
      tooLate: false,
    };
  }

  const last = candles[candles.length - 1];
  const price = last.c;
  const high20 = Math.max(...candles.slice(-20).map((c) => c.h));
  const low20 = Math.min(...candles.slice(-20).map((c) => c.l));
  const buffer = Math.max(0.01, percentOf(price, 0.05));
  const pullbackReclaimBand = Math.max(ema9, vwap);
  const cleanPullbackReclaim = phase === "Trend Expansion" && price >= pullbackReclaimBand * 0.998 && price <= pullbackReclaimBand * 1.01;
  const tooLate = (distanceFromVwap > 0.06 || moveTodayPct > 35) && !cleanPullbackReclaim;

  let entry = null;
  let stop = null;
  let planLabel = "No Plan";

  if (tooLate) {
    planLabel = "No New Long (Too Late)";
  } else if (phase === "Compression") {
    entry = high20 + buffer;
    stop = Math.min(low20 - buffer, vwap - buffer);
    planLabel = "Breakout Trigger";
  } else if (phase === "Early Expansion") {
    entry = Math.max(ema9, high20) + buffer;
    stop = Math.min(vwap - buffer, swingLow(candles, 8) - buffer);
    planLabel = "Early Expansion Entry";
  } else if (phase === "Trend Expansion") {
    entry = Math.max(ema9, vwap) + buffer;
    stop = Math.min(vwap - buffer, swingLow(candles, 10) - buffer);
    planLabel = "Trend Pullback Entry";
  } else if (phase === "Exhaustion") {
    planLabel = "No New Long (Exhaustion)";
  }

  if (!entry || !stop || entry <= stop) {
    return {
      planLabel,
      entry,
      stop,
      targets: null,
      live: { price, rMultiple: null, guidance: "WAIT" },
      tooLate,
      context: { vwap, ema9, ema21, high20, low20, swingHigh10: swingHigh(candles, 10) },
    };
  }

  const risk = entry - stop;
  const target1 = entry + risk;
  const target2 = entry + risk * 2;
  const target3 = entry + risk * 3;
  const rMultiple = (price - entry) / risk;

  let guidance = "WAIT";
  if (price < entry) guidance = "WAIT";
  else if (price >= entry && price < target1) guidance = "HOLD";
  else if (price >= target1 && price < target2) guidance = "TAKE_PARTIAL";
  else if (price >= target2) guidance = "TRAIL";
  if (price <= stop || phase === "Exhaustion") guidance = "EXIT";

  return {
    planLabel,
    entry,
    stop,
    targets: { target1, target2, target3 },
    live: { price, rMultiple: clamp(rMultiple, -5, 10), guidance },
    tooLate,
    context: { vwap, ema9, ema21, high20, low20, swingHigh10: swingHigh(candles, 10) },
  };
};

const computeLiveSignals = (candles) => {
  if (!candles || candles.length < 30) {
    return {
      continuation: 50,
      pullbackRisk: 50,
      reason: "Need more live candles",
      state: "Neutral/Chop",
      phase: "Insufficient Data",
    };
  }

  const closes = candles.map((c) => c.c);
  const volumes = candles.map((c) => c.v || 0);
  const last = candles[candles.length - 1];
  const ema9 = ema(closes.slice(-60), 9);
  const ema21 = ema(closes.slice(-80), 21);
  const r = rsi(closes, 14);
  const rawVwap = last.vw && Number.isFinite(last.vw) ? last.vw : last.c;
  const vwapVal = rawVwap > 0 && Math.abs(rawVwap - last.c) / last.c < 0.25 ? rawVwap : last.c;
  const distFromVwap = vwapVal > 0 ? (last.c - vwapVal) / vwapVal : 0;
  const recentVol = volumes.slice(-10).reduce((a, b) => a + b, 0) / 10;
  const baseVol = volumes.slice(-30).reduce((a, b) => a + b, 0) / 30;
  const rvol = baseVol > 0 ? recentVol / baseVol : 1;
  const recent = candles.slice(-8);
  const hh = recent[recent.length - 1].h > recent[0].h;
  const hl = recent[recent.length - 1].l > recent[0].l;

  const body = Math.abs(last.c - last.o);
  const upperWick = last.h - Math.max(last.o, last.c);
  const wickiness = body > 0 ? upperWick / body : 0;
  const climax = rvol >= 2;

  let continuation = 50;
  if (last.c > vwapVal) continuation += 12;
  if (ema9 > ema21) continuation += 10;
  if (last.c > ema9) continuation += 8;
  if (hh && hl) continuation += 10;
  if (rvol >= 1.5) continuation += 8;
  if (r < 80) continuation += 4;

  let pullbackRisk = 35;
  if (distFromVwap > 0.03) pullbackRisk += 15;
  if (distFromVwap > 0.06) pullbackRisk += 10;
  if (r > 75) pullbackRisk += 12;
  if (wickiness > 1.2) pullbackRisk += 10;
  if (climax) pullbackRisk += 8;
  if (last.c < ema9) pullbackRisk += 10;
  if (last.c < vwapVal) pullbackRisk += 10;

  continuation = clamp(continuation, 0, 100);
  pullbackRisk = clamp(pullbackRisk, 0, 100);
  const biasDelta = continuation - pullbackRisk;
  const state = biasDelta >= 15 ? "Continuation Bias" : biasDelta <= -15 ? "Pullback Risk" : "Neutral/Chop";
  const range = candles.slice(-20);
  const rangeHigh = Math.max(...range.map((c) => c.h));
  const rangeLow = Math.min(...range.map((c) => c.l));
  const phaseInfo = computePhase(candles, vwapVal);
  const moveTodayPct = closes[0] > 0 ? ((last.c - closes[0]) / closes[0]) * 100 : 0;
  const tradePlan = computeTradePlan({
    candles,
    vwap: vwapVal,
    ema9,
    ema21,
    phase: phaseInfo.phase,
    moveTodayPct,
    distanceFromVwap: distFromVwap,
  });

  const reason = [
    `Phase ${phaseInfo.phase}`,
    last.c > vwapVal ? "Above VWAP" : "Below VWAP",
    ema9 > ema21 ? "EMA9>EMA21" : "EMA9<=EMA21",
    `RVOL ${rvol.toFixed(2)}`,
    `RSI ${r.toFixed(0)}`,
    `${(distFromVwap * 100).toFixed(1)}% vs VWAP`,
  ].join(" | ");

  return {
    continuation,
    pullbackRisk,
    reason,
    state,
    phase: phaseInfo.phase,
    vwap: vwapVal,
    rangeHigh,
    rangeLow,
    plan: tradePlan,
    tooLate: tradePlan.tooLate,
  };
};
const StocksPage = () => {
  const [ticker, setTicker] = useState("");
  const [selectedTicker, setSelectedTicker] = useState("AAPL");
  const [chartData, setChartData] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [livePrice, setLivePrice] = useState(null);
  const [entryPoint, setEntryPoint] = useState(null);
  const [exitPoint, setExitPoint] = useState(null);
  const [stopLoss, setStopLoss] = useState(null);
  const [connectionStatus, setConnectionStatus] = useState("disconnected");
  const [lastUpdate, setLastUpdate] = useState("");
  const [, setLastFetchedClose] = useState(null);
  const [prevTicker, setPrevTicker] = useState(null);
  const [liveCandles, setLiveCandles] = useState([]);
  const [liveSignal, setLiveSignal] = useState(null);
  const wsRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  const isMountedRef = useRef(false);
  const selectedTickerRef = useRef(selectedTicker);

  const periods = [
    { intervalType: "Months", interval: 1, text: "1M" },
    { intervalType: "Months", interval: 3, text: "3M" },
    { intervalType: "Months", interval: 6, text: "6M" },
    { intervalType: "Years", interval: 1, text: "YTD" },
    { intervalType: "Years", interval: 3, text: "All" },
  ];

  /** Ã°Å¸â€â€ž Fetch Historical Chart Data */
  const fetchStockData = async (tickerSymbol, showSpinner = true) => {
    if (showSpinner) setLoading(true);
    console.log(`Ã°Å¸â€œÂ¡ Fetching stock data for: ${tickerSymbol}`);

    try {
      const data = await apiFetch(`/api/stock-data?ticker=${tickerSymbol}`);
      console.log("API Response:", data);

      if (data && data.dates && data.dates.length > 0) {
        const formattedData = data.dates.map((date, index) => ({
          x: new Date(date),
          open: data.open[index],
          high: data.high[index],
          low: data.low[index],
          close: data.close[index],
        }));

        setChartData(formattedData);
        const lastClose = formattedData[formattedData.length - 1]?.close || null;
        setLastFetchedClose(lastClose);
        if (lastClose !== null) {
          setLivePrice(lastClose); // seed with latest close until websocket update arrives
        }
        setEntryPoint(data.entry_point ? data.entry_point : null);
        setExitPoint(data.exit_point ? data.exit_point : null);
        setError("");
      } else {
        setChartData([]);
        setError("No data available for the selected ticker.");
      }
    } catch (err) {
      console.error("Ã¢ÂÅ’ Error fetching stock data:", err);
      setChartData([]);
      setError(err.message || "Failed to load stock data.");
    } finally {
      if (showSpinner) setLoading(false);
    }
  };
  // derive entry/exit/stop from recent bars when data updates
  useEffect(() => {
    if (!chartData || chartData.length < 2) return;
    const tail = chartData.slice(-15);
    const trs = tail.map((d, idx) => {
      if (idx === 0) return d.high - d.low;
      const prevClose = tail[idx - 1].close;
      return Math.max(
        d.high - d.low,
        Math.abs(d.high - prevClose),
        Math.abs(d.low - prevClose)
      );
    });
    const atr = trs.reduce((a, b) => a + b, 0) / trs.length;
    const lastClose = tail[tail.length - 1].close;
    setEntryPoint(lastClose);
    setExitPoint(lastClose + atr * 2);
    setStopLoss(lastClose - atr * 1);
  }, [chartData]);

  /** Ã°Å¸â€â€ž Handle Live WebSocket Updates */
  const handleWebSocketMessage = (event) => {
    const data = JSON.parse(event.data);

    data.forEach((update) => {
      if (update.ev === "AM" && update.sym === selectedTickerRef.current) {
        console.log("Ã°Å¸â€œÂ¡ Received WebSocket Update:", update);
        const close = Number(update.c);
        const high = Number(update.h ?? update.c);
        const low = Number(update.l ?? update.c);
        const open = Number(update.o ?? update.c);
        const vol = Number(update.v ?? 0);
        const vwap = Number(update.vw ?? NaN);
        if (!Number.isFinite(close) || close <= 0) return;

        setLivePrice(close);
        setLastUpdate(new Date().toLocaleTimeString());
        const candleTs = update.s || update.e || Date.now();
        const candle = {
          t: candleTs,
          o: Number.isFinite(open) ? open : close,
          h: Number.isFinite(high) ? high : close,
          l: Number.isFinite(low) ? low : close,
          c: close,
          v: Number.isFinite(vol) ? vol : 0,
          vw: Number.isFinite(vwap) ? vwap : null,
        };
        setLiveCandles((prev) => {
          if (!prev.length) return [candle];
          const last = prev[prev.length - 1];
          const jumpRatio = last.c > 0 ? Math.abs(candle.c - last.c) / last.c : 0;
          if (jumpRatio > 0.5) return prev;
          if (last.t === candle.t) return [...prev.slice(0, -1), candle];
          return [...prev, candle].slice(-250);
        });

        // Update chart with latest minute aggregate close price
        setChartData((prevData) => {
          if (prevData.length === 0) return prevData;
          const newData = [...prevData];
          newData[newData.length - 1] = {
            ...newData[newData.length - 1],
            close, // Update only close price
          };
          return newData;
        });
      }
    });
  };

  /** Ã°Å¸â€â€ž Setup WebSocket Connection */
  const setupWebSocket = () => {
    const existing = wsRef.current;
    if (existing) {
      if (prevTicker && existing.readyState === WebSocket.OPEN) {
        existing.send(JSON.stringify({ action: "unsubscribe", params: `AM.${prevTicker}` }));
      }
      existing.onclose = null;
      existing.close();
      wsRef.current = null;
    }

    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    if (!POLYGON_API_KEY) {
      setConnectionStatus("error");
      setError("Missing REACT_APP_POLYGON_API_KEY for live feed.");
      return;
    }

    setConnectionStatus("connecting");
    const websocket = new WebSocket(POLYGON_WS_URL);
    websocket.onopen = () => {
      console.log("Ã¢Å“â€¦ Connected to Polygon.io WebSocket");
      websocket.send(JSON.stringify({ action: "auth", params: POLYGON_API_KEY }));
      websocket.send(JSON.stringify({ action: "subscribe", params: `AM.${selectedTicker}` }));
      setPrevTicker(selectedTicker);
      setConnectionStatus("connected");
    };

    websocket.onmessage = handleWebSocketMessage;
    websocket.onerror = (err) => {
      console.error("Ã¢ÂÅ’ WebSocket Error:", err);
      setConnectionStatus("error");
    };
    websocket.onclose = () => {
      console.log("Ã¢Å¡Â  WebSocket Disconnected");
      setConnectionStatus("disconnected");
      if (!isMountedRef.current) {
        return;
      }
      reconnectTimeoutRef.current = setTimeout(() => {
        if (isMountedRef.current) {
          setupWebSocket();
        }
      }, 5000);
    };

    wsRef.current = websocket;
  };

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    selectedTickerRef.current = selectedTicker;
  }, [selectedTicker]);

  /** Ã°Å¸â€â€ž Effect: Fetch Chart Data on Ticker Change */
  useEffect(() => {
    // reset live values on ticker change
    setLivePrice(null);
    setLastUpdate("");
    setLiveCandles([]);
    setLiveSignal(null);
    setConnectionStatus("connecting");
    fetchStockData(selectedTicker);
    setupWebSocket();
    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }
      if (wsRef.current) {
        wsRef.current.onclose = null;
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [selectedTicker]);

  // Polling fallback to refresh data every 30s
  useEffect(() => {
    const interval = setInterval(() => {
      fetchStockData(selectedTicker, false);
    }, 30000);
    return () => clearInterval(interval);
  }, [selectedTicker]);

  useEffect(() => {
    setLiveSignal(computeLiveSignals(liveCandles));
  }, [liveCandles]);

  const safeChartData = Array.isArray(chartData)
    ? chartData.filter(
        (row) =>
          row &&
          row.x instanceof Date &&
          !Number.isNaN(row.x.getTime()) &&
          [row.open, row.high, row.low, row.close].every((value) => Number.isFinite(Number(value)))
      )
    : [];

  const chartMeta = useMemo(() => {
    const last = safeChartData[safeChartData.length - 1];
    const prev = safeChartData[safeChartData.length - 2];
    const price = livePrice ?? last?.close ?? null;
    const prevClose = prev?.close ?? last?.open ?? null;
    const movePct = price && prevClose ? ((price - prevClose) / prevClose) * 100 : 0;
    const setupLabel = liveSignal?.plan?.planLabel || liveSignal?.state || "No active setup";
    const headerTone = movePct > 0 ? "#22c55e" : movePct < 0 ? "#ef4444" : "#e5e7eb";
    return {
      price,
      movePct,
      setupLabel,
      headerTone,
      lastVolume: liveCandles[liveCandles.length - 1]?.v || 0,
    };
  }, [safeChartData, livePrice, liveSignal, liveCandles]);

  const volumeBars = useMemo(() => {
    const source = liveCandles.length ? liveCandles.slice(-32) : [];
    const maxVolume = Math.max(...source.map((c) => Number(c.v || 0)), 1);
    return source.map((c, index) => {
      const rising = Number(c.c || 0) >= Number(c.o || 0);
      return {
        key: `${c.t || index}`,
        height: `${Math.max(8, (Number(c.v || 0) / maxVolume) * 100)}%`,
        color: rising ? "#22c55e" : "#ef4444",
      };
    });
  }, [liveCandles]);

  /** Ã°Å¸â€Å½ Handle Search */
  const handleSearch = () => {
    if (ticker.trim() !== "") {
      const newTicker = ticker.toUpperCase();
      setSelectedTicker(newTicker);
      fetchStockData(newTicker); // Ã¢Å“â€¦ Fetch new data on search
    }
  };

  const sectionCardStyle = {
    border: "1px solid #243041",
    borderRadius: "14px",
    background: "linear-gradient(180deg, rgba(15,23,42,0.88), rgba(11,15,25,0.9))",
    boxShadow: "0 18px 50px rgba(0,0,0,0.18)",
  };

  const pillStyle = {
    fontSize: "12px",
    color: "#cbd5e1",
    padding: "6px 10px",
    borderRadius: "999px",
    border: "1px solid #243041",
    background: "rgba(15,23,42,0.92)",
  };

  const inputStyle = {
    minHeight: "40px",
    padding: "0 12px",
    borderRadius: "10px",
    border: "1px solid #334155",
    background: "#0f172a",
    color: "#f8fafc",
  };

  const buttonStyle = {
    minHeight: "40px",
    padding: "0 16px",
    borderRadius: "10px",
    border: "1px solid #1d4ed8",
    background: "#172554",
    color: "#dbeafe",
    fontWeight: 600,
    cursor: "pointer",
  };

  return (
    <div className="stocks-page" style={{ padding: "20px" }}>
      <div style={{ ...sectionCardStyle, padding: "18px", marginBottom: "16px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "16px", flexWrap: "wrap" }}>
          <div>
            <div style={{ fontSize: "28px", fontWeight: 800, color: "#f8fafc" }}>{selectedTicker} Stock Analysis</div>
            <div style={{ marginTop: "6px", fontSize: "14px", color: chartMeta.headerTone }}>
              {livePrice !== null ? `Live Price: $${livePrice.toFixed(2)}  ${chartMeta.movePct >= 0 ? "+" : ""}${fmtPct(chartMeta.movePct)}` : "Waiting for live price..."}
            </div>
            <div style={{ marginTop: "8px", display: "flex", gap: "8px", flexWrap: "wrap" }}>
              <span style={pillStyle}>Feed: {connectionStatus}</span>
              <span style={pillStyle}>Last update: {lastUpdate || "-"}</span>
              <span style={pillStyle}>Phase: {liveSignal?.phase || "Insufficient Data"}</span>
            </div>
          </div>

          <div style={{ display: "flex", gap: "10px", flexWrap: "wrap", alignItems: "flex-end" }}>
            <div style={{ display: "flex", flexDirection: "column", gap: "4px", fontSize: "12px", color: "#94a3b8" }}>
              <span>Ticker Search</span>
              <input
                type="text"
                placeholder="Enter stock ticker (e.g., AAPL)"
                value={ticker}
                onChange={(e) => setTicker(e.target.value)}
                style={{ ...inputStyle, minWidth: "240px" }}
              />
            </div>
            <button onClick={handleSearch} style={buttonStyle}>Search</button>
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "minmax(320px, 420px) minmax(0, 1fr)", gap: "16px", marginTop: "16px" }}>
          <div style={{ border: "1px solid #243041", borderRadius: "12px", padding: "14px", background: "rgba(15,23,42,0.76)" }}>
            <div style={{ fontSize: "20px", fontWeight: 700, color: "#f8fafc", marginBottom: "10px" }}>Live Candle Signal</div>
            <div style={{ display: "grid", gap: "6px", fontSize: "14px" }}>
              <div style={{ color: liveSignal?.continuation >= 65 ? "#22c55e" : "#d1d5db" }}>Continuation: {liveSignal?.continuation?.toFixed?.(0) ?? "-"}</div>
              <div style={{ color: liveSignal?.pullbackRisk >= 65 ? "#ef4444" : "#d1d5db" }}>Pullback Risk: {liveSignal?.pullbackRisk?.toFixed?.(0) ?? "-"}</div>
              <div style={{ color: "#93c5fd" }}>State: {liveSignal?.state || "Neutral/Chop"}</div>
              <div style={{ color: "#a7f3d0" }}>Phase: {liveSignal?.phase || "Insufficient Data"}</div>
              <div style={{ color: liveSignal?.tooLate ? "#ef4444" : "#d1d5db" }}>{liveSignal?.tooLate ? "Too Late: Yes" : "Too Late: No"}</div>
              <div style={{ color: "#fcd34d" }}>Plan: {liveSignal?.plan?.planLabel || "No Plan"}</div>
              <div style={{ fontSize: "12px", color: "#cbd5e1" }}>Entry: {liveSignal?.plan?.entry ? liveSignal.plan.entry.toFixed(2) : "-"} | Stop: {liveSignal?.plan?.stop ? liveSignal.plan.stop.toFixed(2) : "-"}</div>
              <div style={{ fontSize: "12px", color: "#cbd5e1" }}>Targets: 1R {liveSignal?.plan?.targets?.target1 ? liveSignal.plan.targets.target1.toFixed(2) : "-"} | 2R {liveSignal?.plan?.targets?.target2 ? liveSignal.plan.targets.target2.toFixed(2) : "-"} | 3R {liveSignal?.plan?.targets?.target3 ? liveSignal.plan.targets.target3.toFixed(2) : "-"}</div>
              <div style={{ color: "#93c5fd" }}>Live R: {liveSignal?.plan?.live?.rMultiple !== null && liveSignal?.plan?.live?.rMultiple !== undefined ? `${liveSignal.plan.live.rMultiple.toFixed(2)}R` : "-"} | Guidance: {liveSignal?.plan?.live?.guidance || "WAIT"}</div>
              <div style={{ fontSize: "12px", color: "#9ca3af" }}>{liveSignal?.reason || "Waiting for live candles..."}</div>
              <div style={{ fontSize: "12px", color: "#9ca3af" }}>
                VWAP: {liveSignal?.vwap ? liveSignal.vwap.toFixed(2) : "-"} | Range(20): {liveSignal?.rangeLow ? liveSignal.rangeLow.toFixed(2) : "-"} - {liveSignal?.rangeHigh ? liveSignal.rangeHigh.toFixed(2) : "-"}
              </div>
            </div>
          </div>

          <div style={{ display: "grid", gap: "12px", alignContent: "start" }}>
            <div style={{ border: "1px solid #243041", borderRadius: "12px", padding: "14px", background: "rgba(15,23,42,0.76)" }}>
              <div style={{ fontSize: "13px", color: "#94a3b8", marginBottom: "8px" }}>Workflow</div>
              <div style={{ fontSize: "18px", fontWeight: 700, color: "#f8fafc" }}>{liveSignal?.plan?.planLabel || "No Plan"}</div>
              <div style={{ marginTop: "8px", display: "flex", gap: "8px", flexWrap: "wrap" }}>
                <span style={pillStyle}>Entry {fmtPrice(liveSignal?.plan?.entry)}</span>
                <span style={pillStyle}>Stop {fmtPrice(liveSignal?.plan?.stop)}</span>
                <span style={pillStyle}>T1 {fmtPrice(liveSignal?.plan?.targets?.target1)}</span>
              </div>
            </div>
            <div style={{ border: "1px solid #243041", borderRadius: "12px", padding: "14px", background: "rgba(15,23,42,0.76)" }}>
              <div style={{ fontSize: "13px", color: "#94a3b8", marginBottom: "8px" }}>Watchlist</div>
              <AddTicker />
            </div>
            <div style={{ border: "1px solid #243041", borderRadius: "12px", padding: "14px", background: "rgba(15,23,42,0.76)" }}>
              <div style={{ fontSize: "13px", color: "#94a3b8", marginBottom: "8px" }}>Live Price Feed</div>
              <LiveStockUpdate ticker={selectedTicker} />
            </div>
          </div>
        </div>
      </div>
      <MarketSignalsFeed selectedTicker={selectedTicker} />

      {(safeChartData.length > 1 || loading || error || (!loading && safeChartData.length === 0)) && (
        <div className="stock-chart-card">
          <div className="stock-chart-card__header">
            <div className="stock-chart-card__header-main">
              <div className="stock-chart-card__title-row">
                <div className="stock-chart-card__symbol">{selectedTicker}</div>
                <div className="stock-chart-card__price" style={{ color: chartMeta.headerTone }}>
                  ${fmtPrice(chartMeta.price)}
                </div>
                <div className="stock-chart-card__change" style={{ color: chartMeta.headerTone }}>
                  {chartMeta.movePct >= 0 ? "+" : ""}{fmtPct(chartMeta.movePct)}
                </div>
              </div>
              <div className="stock-chart-card__subtitle">
                {chartMeta.setupLabel}
              </div>
            </div>

            <div className="stock-chart-card__badges">
              <span className="stock-chart-pill stock-chart-pill--phase">
                Phase: {liveSignal?.phase || "Insufficient Data"}
              </span>
              <span className="stock-chart-pill stock-chart-pill--entry">
                Entry {fmtPrice(liveSignal?.plan?.entry)}
              </span>
              <span className="stock-chart-pill stock-chart-pill--stop">
                Stop {fmtPrice(liveSignal?.plan?.stop)}
              </span>
              <span className="stock-chart-pill stock-chart-pill--target">
                Target {fmtPrice(liveSignal?.plan?.targets?.target1)}
              </span>
            </div>
          </div>

          <div className="stock-chart-card__body">
            {safeChartData.length > 1 ? (
              <StockChartComponent
                id="stockchart"
                height="520px"
                width="100%"
                background="transparent"
                chartArea={{ border: { width: 0 } }}
                margin={{ left: 8, right: 24, top: 8, bottom: 0 }}
                primaryXAxis={{
                  valueType: "DateTime",
                  labelFormat: "MMM dd",
                  labelStyle: { color: "#dbe7ff", size: "12px" },
                  majorGridLines: { width: 1, color: "rgba(148,163,184,0.18)" },
                  minorGridLines: { width: 0.5, color: "rgba(148,163,184,0.08)" },
                  lineStyle: { width: 1, color: "rgba(148,163,184,0.28)" },
                  majorTickLines: { width: 0 },
                }}
                primaryYAxis={{
                  labelFormat: "${value}",
                  labelStyle: { color: "#dbe7ff", size: "12px" },
                  majorGridLines: { width: 1, color: "rgba(148,163,184,0.18)" },
                  minorGridLines: { width: 0.5, color: "rgba(148,163,184,0.08)" },
                  lineStyle: { width: 1, color: "rgba(148,163,184,0.28)" },
                  majorTickLines: { width: 0 },
                }}
                tooltip={{ enable: true }}
                crosshair={{ enable: true }}
                periods={periods}
                key={`${selectedTicker}-${safeChartData.length}`}
              >
                <Inject services={[
                  DateTime, Tooltip, RangeTooltip, Crosshair, LineSeries, CandleSeries,
                  Legend, Export, RsiIndicator, MacdIndicator, ScatterSeries
                ]} />
                <StockChartSeriesCollectionDirective>
                  <StockChartSeriesDirective
                    dataSource={safeChartData}
                    xName="x"
                    open="open"
                    high="high"
                    low="low"
                    close="close"
                    type="Candle"
                    bullFillColor="#16c784"
                    bearFillColor="#ef5350"
                    animation={{ enable: true }}
                  />
                  {entryPoint !== null && (
                    <StockChartSeriesDirective
                      dataSource={[{ x: safeChartData[0]?.x || new Date(), y: entryPoint }]}
                      xName="x"
                      yName="y"
                      type="Scatter"
                      marker={{ visible: true, shape: "Triangle", fill: "#22c55e", size: 10 }}
                      name="Entry Point"
                    />
                  )}
                  {exitPoint !== null && (
                    <StockChartSeriesDirective
                      dataSource={[{ x: safeChartData[safeChartData.length - 1]?.x || new Date(), y: exitPoint }]}
                      xName="x"
                      yName="y"
                      type="Scatter"
                      marker={{ visible: true, shape: "InvertedTriangle", fill: "#facc15", size: 10 }}
                      name="Target"
                    />
                  )}
                  {stopLoss !== null && (
                    <StockChartSeriesDirective
                      dataSource={[{ x: safeChartData[safeChartData.length - 1]?.x || new Date(), y: stopLoss }]}
                      xName="x"
                      yName="y"
                      type="Scatter"
                      marker={{ visible: true, shape: "Diamond", fill: "#ef4444", size: 10 }}
                      name="Stop"
                    />
                  )}
                </StockChartSeriesCollectionDirective>
              </StockChartComponent>
            ) : (
              <div
                className="stock-chart-card__empty"
                style={{ color: error ? "#fca5a5" : "#94a3b8" }}
              >
                {loading ? "Loading chart data..." : error || `No historical chart data for ${selectedTicker}.`}
              </div>
            )}

            <div className="stock-chart-card__volume">
              <div className="stock-chart-card__volume-header">
                <div className="stock-chart-card__volume-title">Volume</div>
                <div className="stock-chart-card__volume-last">Last: {fmtVolume(chartMeta.lastVolume)}</div>
              </div>
              <div className="stock-chart-card__volume-bars">
                {volumeBars.length === 0 ? (
                  <div style={{ fontSize: "12px", color: "#64748b" }}>No live volume bars yet.</div>
                ) : (
                  volumeBars.map((bar) => (
                    <div key={bar.key} style={{ flex: 1, height: bar.height, background: bar.color, borderRadius: "3px 3px 0 0", opacity: 0.85 }} />
                  ))
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default StocksPage;
























