/* eslint-disable no-template-curly-in-string, react-hooks/exhaustive-deps */
import React, { useEffect, useMemo, useRef, useState } from "react";
import LiveStockUpdate from "./LiveStockUpdate";
import AddTicker from "./AddTicker";
import MarketSignalsFeed from "./MarketSignalsFeed";
import "./StocksPage.css";
import { apiFetch } from "../apiClient";
import { computeLiveSignalsFromBars } from "../lib/stockSignalEngine";

import {
  ChartComponent,
  SeriesCollectionDirective,
  SeriesDirective,
  Inject,
  DateTime,
  Tooltip,
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
const BUILD_MARKER = "TRAX BUILD 2026-03-30 v3";
const STOCK_ALERTS_STORAGE_KEY = "stockPageAlerts";
const AI_TOP_PICKS_REFRESH_MS = 5 * 60 * 1000;
const AI_TOP_PICKS_TIMEOUT_MS = 60000;

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

const loadStoredStockAlerts = () => {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STOCK_ALERTS_STORAGE_KEY);
    const parsed = JSON.parse(raw || "[]");
    return Array.isArray(parsed) ? parsed : [];
  } catch (error) {
    return [];
  }
};

const deriveAiConfidence = (score) => {
  const numericScore = Number(score || 0);
  if (numericScore > 80) return "High";
  if (numericScore > 60) return "Medium";
  return "Low";
};

const formatTimeLabel = (value) => {
  if (!value) return "-";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "-" : parsed.toLocaleTimeString();
};

const StocksPage = ({ theme = "dark" }) => {
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
  const [topPickUniverse, setTopPickUniverse] = useState([]);
  const [topPicksGeneratedAt, setTopPicksGeneratedAt] = useState("");
  const [topPicksLoading, setTopPicksLoading] = useState(false);
  const [topPicksError, setTopPicksError] = useState("");
  const [alerts, setAlerts] = useState(loadStoredStockAlerts);
  const [latestAlertMessage, setLatestAlertMessage] = useState("");
  const wsRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  const isMountedRef = useRef(false);
  const selectedTickerRef = useRef(selectedTicker);

  useEffect(() => {
    console.log(BUILD_MARKER);
  }, []);

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
    setLiveSignal(computeLiveSignalsFromBars(liveCandles));
  }, [liveCandles]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(STOCK_ALERTS_STORAGE_KEY, JSON.stringify(alerts));
  }, [alerts]);

  const loadTopPicks = async () => {
    try {
      setTopPicksLoading(true);
      setTopPicksError("");
      const params = new URLSearchParams({
        limit: "8",
        pool_limit: "120",
      });
      const data = await apiFetch(`/api/ai-picks?${params}`, { timeoutMs: AI_TOP_PICKS_TIMEOUT_MS });
      setTopPickUniverse(Array.isArray(data?.picks) ? data.picks : []);
      setTopPicksGeneratedAt(String(data?.generated_at || ""));
    } catch (err) {
      setTopPickUniverse([]);
      setTopPicksGeneratedAt("");
      setTopPicksError(err.message || "AI picks unavailable");
    } finally {
      setTopPicksLoading(false);
    }
  };

  useEffect(() => {
    loadTopPicks();
    const interval = setInterval(() => {
      loadTopPicks();
    }, AI_TOP_PICKS_REFRESH_MS);
    return () => clearInterval(interval);
  }, []);

  const topPicks = useMemo(() => topPickUniverse.slice(0, 3), [topPickUniverse]);
  const activeAlerts = useMemo(() => alerts.filter((item) => !item.triggeredAt), [alerts]);
  const triggeredAlerts = useMemo(() => alerts.filter((item) => item.triggeredAt), [alerts]);

  const armAlert = ({ symbol, entry, target = null, source = "manual" }) => {
    const normalizedSymbol = String(symbol || "").toUpperCase();
    const numericEntry = Number(entry);
    const numericTarget = Number(target);
    if (!normalizedSymbol || !Number.isFinite(numericEntry) || numericEntry <= 0) {
      setLatestAlertMessage("No valid entry level available for this alert.");
      return;
    }

    let message = "";
    setAlerts((prev) => {
      const duplicate = prev.find(
        (item) =>
          !item.triggeredAt &&
          item.symbol === normalizedSymbol &&
          Math.abs(Number(item.entry || 0) - numericEntry) < 0.01
      );
      if (duplicate) {
        message = `${normalizedSymbol} alert is already armed near ${fmtPrice(numericEntry)}.`;
        return prev;
      }
      message = `${normalizedSymbol} alert armed at ${fmtPrice(numericEntry)}.`;
      return [
        {
          id: `${normalizedSymbol}-${Date.now()}`,
          symbol: normalizedSymbol,
          entry: numericEntry,
          target: Number.isFinite(numericTarget) ? numericTarget : null,
          source,
          createdAt: new Date().toISOString(),
          triggeredAt: null,
          triggerPrice: null,
        },
        ...prev,
      ].slice(0, 24);
    });
    if (message) setLatestAlertMessage(message);
  };

  const triggerAlertsForSymbol = (symbol, price) => {
    const normalizedSymbol = String(symbol || "").toUpperCase();
    const numericPrice = Number(price);
    if (!normalizedSymbol || !Number.isFinite(numericPrice) || numericPrice <= 0) return;

    let fired = [];
    setAlerts((prev) =>
      prev.map((item) => {
        if (item.triggeredAt || item.symbol !== normalizedSymbol || numericPrice < Number(item.entry || 0)) {
          return item;
        }
        const triggered = {
          ...item,
          triggeredAt: new Date().toISOString(),
          triggerPrice: numericPrice,
        };
        fired.push(triggered);
        return triggered;
      })
    );

    if (fired.length > 0) {
      const first = fired[0];
      setLatestAlertMessage(`${first.symbol} hit entry ${fmtPrice(first.entry)} at ${fmtPrice(first.triggerPrice)}.`);
    }
  };

  useEffect(() => {
    triggerAlertsForSymbol(selectedTicker, livePrice);
  }, [selectedTicker, livePrice]);

  useEffect(() => {
    topPickUniverse.forEach((item) => {
      triggerAlertsForSymbol(item.symbol, item.price);
    });
  }, [topPickUniverse]);

  const clearTriggeredAlerts = () => {
    setAlerts((prev) => prev.filter((item) => !item.triggeredAt));
    setLatestAlertMessage("Triggered alerts cleared.");
  };

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

  const isDark = theme === "dark";
  const themeColors = {
    border: isDark ? "#243041" : "#c9d7eb",
    cardBackground: isDark
      ? "linear-gradient(180deg, rgba(15,23,42,0.88), rgba(11,15,25,0.9))"
      : "linear-gradient(180deg, rgba(255,255,255,0.96), rgba(238,244,255,0.96))",
    panelBackground: isDark ? "rgba(15,23,42,0.76)" : "rgba(255,255,255,0.9)",
    pillBackground: isDark ? "rgba(15,23,42,0.92)" : "rgba(244,247,252,0.95)",
    inputBackground: isDark ? "#0f172a" : "#ffffff",
    inputBorder: isDark ? "#334155" : "#b8cae2",
    inputText: isDark ? "#f8fafc" : "#102038",
    buttonBackground: isDark ? "#172554" : "#dbeafe",
    buttonBorder: isDark ? "#1d4ed8" : "#60a5fa",
    buttonText: isDark ? "#dbeafe" : "#0f172a",
    heading: isDark ? "#f8fafc" : "#102038",
    mutedText: isDark ? "#94a3b8" : "#52637a",
    subtleText: isDark ? "#9ca3af" : "#64748b",
    neutralText: isDark ? "#cbd5e1" : "#334155",
  };

  const sectionCardStyle = {
    border: `1px solid ${themeColors.border}`,
    borderRadius: "14px",
    background: themeColors.cardBackground,
    boxShadow: isDark ? "0 18px 50px rgba(0,0,0,0.18)" : "0 18px 50px rgba(15,23,42,0.08)",
  };

  const pillStyle = {
    fontSize: "12px",
    color: themeColors.neutralText,
    padding: "6px 10px",
    borderRadius: "999px",
    border: `1px solid ${themeColors.border}`,
    background: themeColors.pillBackground,
  };

  const inputStyle = {
    minHeight: "40px",
    padding: "0 12px",
    borderRadius: "10px",
    border: `1px solid ${themeColors.inputBorder}`,
    background: themeColors.inputBackground,
    color: themeColors.inputText,
  };

  const buttonStyle = {
    minHeight: "40px",
    padding: "0 16px",
    borderRadius: "10px",
    border: `1px solid ${themeColors.buttonBorder}`,
    background: themeColors.buttonBackground,
    color: themeColors.buttonText,
    fontWeight: 600,
    cursor: "pointer",
  };

  return (
    <div className="stocks-page" style={{ padding: "20px" }}>
      <div style={{ ...sectionCardStyle, padding: "18px", marginBottom: "16px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "16px", flexWrap: "wrap" }}>
          <div>
            <div style={{ fontSize: "28px", fontWeight: 800, color: themeColors.heading }}>{selectedTicker} Stock Analysis</div>
            <div style={{ marginTop: "6px", fontSize: "14px", color: chartMeta.headerTone }}>
              {livePrice !== null ? `Live Price: $${livePrice.toFixed(2)}  ${chartMeta.movePct >= 0 ? "+" : ""}${fmtPct(chartMeta.movePct)}` : "Waiting for live price..."}
            </div>
            <div style={{ marginTop: "8px", display: "flex", gap: "8px", flexWrap: "wrap" }}>
              <span style={pillStyle}>{BUILD_MARKER}</span>
              <span style={pillStyle}>Feed: {connectionStatus}</span>
              <span style={pillStyle}>Last update: {lastUpdate || "-"}</span>
              <span style={pillStyle}>Phase: {liveSignal?.phase || "Insufficient Data"}</span>
              <span style={pillStyle}>Confidence: {liveSignal?.confidence || "Low"}</span>
              <span style={pillStyle}>Alerts: {activeAlerts.length} armed / {triggeredAlerts.length} hit</span>
            </div>
          </div>

          <div style={{ display: "flex", gap: "10px", flexWrap: "wrap", alignItems: "flex-end" }}>
            <div style={{ display: "flex", flexDirection: "column", gap: "4px", fontSize: "12px", color: themeColors.mutedText }}>
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

        <div style={{ marginTop: "16px", border: `1px solid ${themeColors.border}`, borderRadius: "12px", padding: "14px", background: themeColors.panelBackground }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: "12px", alignItems: "center", flexWrap: "wrap", marginBottom: "10px" }}>
            <div>
              <div style={{ fontSize: "20px", fontWeight: 700, color: themeColors.heading }}>Top 3 AI Picks</div>
              <div style={{ fontSize: "12px", color: themeColors.mutedText }}>
                {topPicksGeneratedAt ? `Last scan ${formatTimeLabel(topPicksGeneratedAt)}` : "Auto-refresh every 5 minutes"}
              </div>
            </div>
            {topPicksLoading && <div style={{ fontSize: "12px", color: themeColors.mutedText }}>Refreshing AI picks...</div>}
          </div>

          {topPicks.length === 0 ? (
            <div style={{ fontSize: "13px", color: themeColors.subtleText }}>
              {topPicksError || "No AI picks available right now."}
            </div>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(220px, 1fr))", gap: "12px" }}>
              {topPicks.map((item) => (
                <div key={`top-pick-${item.symbol}`} style={{ border: `1px solid ${themeColors.border}`, borderRadius: "12px", padding: "14px", background: themeColors.pillBackground }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: "10px", alignItems: "flex-start" }}>
                    <div>
                      <div style={{ fontSize: "20px", fontWeight: 800, color: themeColors.heading }}>{item.symbol}</div>
                      <div style={{ fontSize: "12px", color: themeColors.mutedText }}>Score {Number(item.score || 0).toFixed(0)} • Confidence {deriveAiConfidence(item.score)}</div>
                    </div>
                    <button
                      onClick={() => armAlert({ symbol: item.symbol, entry: item.plan?.entry || item.plan?.trigger, target: item.plan?.target1, source: "ai-pick" })}
                      style={{ ...buttonStyle, minHeight: "34px", padding: "0 12px" }}
                    >
                      Alert me
                    </button>
                  </div>

                  <div style={{ marginTop: "10px", display: "grid", gap: "6px", fontSize: "13px", color: themeColors.neutralText }}>
                    <div>Entry: {fmtPrice(item.plan?.entry || item.plan?.trigger)}</div>
                    <div>Target: {fmtPrice(item.plan?.target1)}</div>
                    <div>Price: {fmtPrice(item.price)}</div>
                    <div style={{ color: themeColors.subtleText }}>{Array.isArray(item.reasons) ? item.reasons.join(" | ") : "No reason provided."}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "minmax(320px, 420px) minmax(0, 1fr)", gap: "16px", marginTop: "16px" }}>
          <div style={{ border: `1px solid ${themeColors.border}`, borderRadius: "12px", padding: "14px", background: themeColors.panelBackground }}>
            <div style={{ fontSize: "20px", fontWeight: 700, color: themeColors.heading, marginBottom: "10px" }}>Live Candle Signal</div>
            <div style={{ display: "grid", gap: "6px", fontSize: "14px" }}>
              <div style={{ color: "#fcd34d" }}>Score: {liveSignal?.score?.toFixed?.(0) ?? "-"}</div>
              <div style={{ color: liveSignal?.confidence === "High" ? "#22c55e" : liveSignal?.confidence === "Medium" ? "#93c5fd" : "#d1d5db" }}>Confidence: {liveSignal?.confidence || "Low"}</div>
              <div style={{ color: liveSignal?.continuation >= 65 ? "#22c55e" : "#d1d5db" }}>Continuation: {liveSignal?.continuation?.toFixed?.(0) ?? "-"}</div>
              <div style={{ color: liveSignal?.pullbackRisk >= 65 ? "#ef4444" : "#d1d5db" }}>Pullback Risk: {liveSignal?.pullbackRisk?.toFixed?.(0) ?? "-"}</div>
              <div style={{ color: "#93c5fd" }}>State: {liveSignal?.state || "Neutral/Chop"}</div>
              <div style={{ color: "#a7f3d0" }}>Phase: {liveSignal?.phase || "Insufficient Data"}</div>
              <div style={{ color: liveSignal?.tooLate ? "#ef4444" : "#d1d5db" }}>{liveSignal?.tooLate ? "Too Late: Yes" : "Too Late: No"}</div>
              <div style={{ color: "#fcd34d" }}>Plan: {liveSignal?.plan?.planLabel || "No Plan"}</div>
              <div style={{ fontSize: "12px", color: themeColors.neutralText }}>Entry: {liveSignal?.plan?.entry ? liveSignal.plan.entry.toFixed(2) : "-"} | Stop: {liveSignal?.plan?.stop ? liveSignal.plan.stop.toFixed(2) : "-"}</div>
              <div style={{ fontSize: "12px", color: themeColors.neutralText }}>Targets: 1R {liveSignal?.plan?.targets?.target1 ? liveSignal.plan.targets.target1.toFixed(2) : "-"} | 2R {liveSignal?.plan?.targets?.target2 ? liveSignal.plan.targets.target2.toFixed(2) : "-"} | 3R {liveSignal?.plan?.targets?.target3 ? liveSignal.plan.targets.target3.toFixed(2) : "-"}</div>
              <div style={{ color: "#93c5fd" }}>Live R: {liveSignal?.plan?.live?.rMultiple !== null && liveSignal?.plan?.live?.rMultiple !== undefined ? `${liveSignal.plan.live.rMultiple.toFixed(2)}R` : "-"} | Guidance: {liveSignal?.plan?.live?.guidance || "WAIT"}</div>
              <div style={{ fontSize: "12px", color: themeColors.subtleText }}>{liveSignal?.reason || "Waiting for live candles..."}</div>
              <div style={{ fontSize: "12px", color: themeColors.subtleText }}>
                VWAP: {liveSignal?.vwap ? liveSignal.vwap.toFixed(2) : "-"} | Range(20): {liveSignal?.rangeLow ? liveSignal.rangeLow.toFixed(2) : "-"} - {liveSignal?.rangeHigh ? liveSignal.rangeHigh.toFixed(2) : "-"}
              </div>
            </div>
          </div>

          <div style={{ display: "grid", gap: "12px", alignContent: "start" }}>
            <div style={{ border: `1px solid ${themeColors.border}`, borderRadius: "12px", padding: "14px", background: themeColors.panelBackground }}>
              <div style={{ fontSize: "13px", color: themeColors.mutedText, marginBottom: "8px" }}>Workflow</div>
              <div style={{ fontSize: "18px", fontWeight: 700, color: themeColors.heading }}>{liveSignal?.plan?.planLabel || "No Plan"}</div>
              <div style={{ marginTop: "8px", display: "flex", gap: "8px", flexWrap: "wrap" }}>
                <span style={pillStyle}>Entry {fmtPrice(liveSignal?.plan?.entry)}</span>
                <span style={pillStyle}>Stop {fmtPrice(liveSignal?.plan?.stop)}</span>
                <span style={pillStyle}>T1 {fmtPrice(liveSignal?.plan?.targets?.target1)}</span>
              </div>
              <div style={{ marginTop: "10px", display: "flex", gap: "8px", flexWrap: "wrap" }}>
                <button
                  onClick={() => armAlert({ symbol: selectedTicker, entry: liveSignal?.plan?.entry, target: liveSignal?.plan?.targets?.target1, source: "selected-ticker" })}
                  style={{ ...buttonStyle, minHeight: "34px", padding: "0 12px" }}
                >
                  Alert me
                </button>
                {triggeredAlerts.length > 0 && (
                  <button onClick={clearTriggeredAlerts} style={{ ...buttonStyle, minHeight: "34px", padding: "0 12px" }}>
                    Clear triggered
                  </button>
                )}
              </div>
              <div style={{ marginTop: "10px", fontSize: "12px", color: themeColors.subtleText }}>
                {latestAlertMessage || "Alerts persist locally and trigger when price reaches entry."}
              </div>
            </div>
            <div style={{ border: `1px solid ${themeColors.border}`, borderRadius: "12px", padding: "14px", background: themeColors.panelBackground }}>
              <div style={{ fontSize: "13px", color: themeColors.mutedText, marginBottom: "8px" }}>Watchlist</div>
              <AddTicker />
            </div>
            <div style={{ border: `1px solid ${themeColors.border}`, borderRadius: "12px", padding: "14px", background: themeColors.panelBackground }}>
              <div style={{ fontSize: "13px", color: themeColors.mutedText, marginBottom: "8px" }}>Alerts</div>
              {alerts.length === 0 ? (
                <div style={{ fontSize: "12px", color: themeColors.subtleText }}>No alerts armed yet.</div>
              ) : (
                <div style={{ display: "grid", gap: "8px" }}>
                  {alerts.slice(0, 4).map((item) => (
                    <div key={item.id} style={{ border: `1px solid ${themeColors.border}`, borderRadius: "10px", padding: "10px", background: themeColors.pillBackground }}>
                      <div style={{ display: "flex", justifyContent: "space-between", gap: "10px", fontSize: "12px" }}>
                        <strong style={{ color: themeColors.heading }}>{item.symbol}</strong>
                        <span style={{ color: item.triggeredAt ? "#22c55e" : themeColors.mutedText }}>{item.triggeredAt ? "Triggered" : "Armed"}</span>
                      </div>
                      <div style={{ marginTop: "4px", fontSize: "12px", color: themeColors.neutralText }}>
                        Entry {fmtPrice(item.entry)}{item.target ? ` | Target ${fmtPrice(item.target)}` : ""}
                      </div>
                      <div style={{ marginTop: "4px", fontSize: "11px", color: themeColors.subtleText }}>
                        {item.triggeredAt ? `Hit at ${fmtPrice(item.triggerPrice)} on ${formatTimeLabel(item.triggeredAt)}` : `Created ${formatTimeLabel(item.createdAt)}`}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div style={{ border: `1px solid ${themeColors.border}`, borderRadius: "12px", padding: "14px", background: themeColors.panelBackground }}>
              <div style={{ fontSize: "13px", color: themeColors.mutedText, marginBottom: "8px" }}>Live Price Feed</div>
              <LiveStockUpdate ticker={selectedTicker} />
            </div>
          </div>
        </div>
      </div>
      <MarketSignalsFeed selectedTicker={selectedTicker} theme={theme} />

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
              <ChartComponent
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
                key={`${selectedTicker}-${safeChartData.length}`}
                legendSettings={{ visible: true }}
              >
                <Inject services={[
                  DateTime, Tooltip, Crosshair, LineSeries, CandleSeries,
                  Legend, Export, RsiIndicator, MacdIndicator, ScatterSeries
                ]} />
                <SeriesCollectionDirective>
                  <SeriesDirective
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
                    <SeriesDirective
                      dataSource={[{ x: safeChartData[0]?.x || new Date(), y: entryPoint }]}
                      xName="x"
                      yName="y"
                      type="Scatter"
                      marker={{ visible: true, shape: "Triangle", fill: "#22c55e", size: 10 }}
                      name="Entry Point"
                    />
                  )}
                  {exitPoint !== null && (
                    <SeriesDirective
                      dataSource={[{ x: safeChartData[safeChartData.length - 1]?.x || new Date(), y: exitPoint }]}
                      xName="x"
                      yName="y"
                      type="Scatter"
                      marker={{ visible: true, shape: "InvertedTriangle", fill: "#facc15", size: 10 }}
                      name="Target"
                    />
                  )}
                  {stopLoss !== null && (
                    <SeriesDirective
                      dataSource={[{ x: safeChartData[safeChartData.length - 1]?.x || new Date(), y: stopLoss }]}
                      xName="x"
                      yName="y"
                      type="Scatter"
                      marker={{ visible: true, shape: "Diamond", fill: "#ef4444", size: 10 }}
                      name="Stop"
                    />
                  )}
                </SeriesCollectionDirective>
              </ChartComponent>
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
























