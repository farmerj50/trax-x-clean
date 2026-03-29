/* eslint-disable react-hooks/exhaustive-deps */
import React, { useEffect, useMemo, useRef, useState } from "react";
import { apiFetch } from "../apiClient";
import "./OptionsPage.css";

const POLYGON_WS_URL = "wss://delayed.polygon.io/stocks";
const POLYGON_API_KEY = process.env.REACT_APP_POLYGON_API_KEY;

const fallbackChain = [
  { type: "call", strike: 280, bid: 1.9, ask: 2.1, expiry: "2026-03-20", delta: 0.42, iv: 0.36, oi: 1200, volume: 380 },
  { type: "call", strike: 300, bid: 1.1, ask: 1.3, expiry: "2026-03-20", delta: 0.31, iv: 0.39, oi: 980, volume: 260 },
  { type: "call", strike: 320, bid: 0.7, ask: 0.9, expiry: "2026-03-20", delta: 0.23, iv: 0.42, oi: 760, volume: 180 },
  { type: "put", strike: 250, bid: 2.2, ask: 2.5, expiry: "2026-03-20", delta: -0.37, iv: 0.34, oi: 1100, volume: 300 },
  { type: "put", strike: 230, bid: 1.4, ask: 1.6, expiry: "2026-03-20", delta: -0.28, iv: 0.31, oi: 860, volume: 220 },
  { type: "put", strike: 210, bid: 1.0, ask: 1.2, expiry: "2026-03-20", delta: -0.21, iv: 0.29, oi: 700, volume: 170 },
];

const clamp = (n, lo, hi) => Math.max(lo, Math.min(hi, n));
const mid = (bid, ask) => Number(((bid + ask) / 2).toFixed(2));
const fmtPrice = (value) => (Number.isFinite(Number(value)) ? Number(value).toFixed(2) : "-");
const fmtPct = (value) => `${Number(value || 0).toFixed(2)}%`;

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
  const isCompression = rangePct < 0.012 && Math.abs(ema9 - ema21) / Math.max(last.c, 1e-6) < 0.002 && last.c >= high20 * 0.99;
  const isEarlyExpansion = last.c > high20 && volumeSpike && last.c > vwapVal && ema9 > ema21;
  const isTrend = ema9 > ema21 && last.c > vwapVal && distanceFromVWAP < 0.05;
  const isExhaustion = distanceFromVWAP > 0.05 && volumeSpike && r > 78;
  let phase = "Neutral / Chop";
  if (isExhaustion) phase = "Exhaustion";
  else if (isEarlyExpansion) phase = "Early Expansion";
  else if (isTrend) phase = "Trend Expansion";
  else if (isCompression) phase = "Compression";
  return { phase, ema9, ema21, distanceFromVWAP };
};

const swingLow = (candles, lookback = 10) => Math.min(...candles.slice(-lookback).map((c) => c.l));
const pctOf = (value, pct) => value * (pct / 100);

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
  const buffer = Math.max(0.01, pctOf(price, 0.05));
  const pullbackBand = Math.max(ema9, vwap);
  const cleanPullback = phase === "Trend Expansion" && price >= pullbackBand * 0.998 && price <= pullbackBand * 1.01;
  const tooLate = (distanceFromVwap > 0.06 || moveTodayPct > 35) && !cleanPullback;
  let entry = null;
  let stop = null;
  let planLabel = "No Plan";
  if (tooLate) planLabel = "No New Long (Too Late)";
  else if (phase === "Compression") {
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
    return { planLabel, entry, stop, targets: null, live: { price, rMultiple: null, guidance: "WAIT" }, tooLate };
  }
  const risk = entry - stop;
  const target1 = entry + risk;
  const target2 = entry + risk * 2;
  const target3 = entry + risk * 3;
  const rMultiple = (price - entry) / risk;
  let guidance = "WAIT";
  if (price < entry) guidance = "WAIT";
  else if (price < target1) guidance = "HOLD";
  else if (price < target2) guidance = "TAKE_PARTIAL";
  else guidance = "TRAIL";
  if (price <= stop || phase === "Exhaustion") guidance = "EXIT";
  return { planLabel, entry, stop, targets: { target1, target2, target3 }, live: { price, rMultiple: clamp(rMultiple, -5, 10), guidance }, tooLate };
};

const normalizeExpiry = (expiry) => {
  if (expiry === null || expiry === undefined) return "";
  const raw = String(expiry).trim();
  if (!raw) return "";
  if (/^\d+$/.test(raw)) {
    const num = Number(raw);
    if (!Number.isFinite(num) || num <= 0) return "";
    const ts = num > 2_000_000_000 ? num : num * 1000;
    return new Date(ts).toISOString().slice(0, 10);
  }
  const ts = Date.parse(raw);
  if (Number.isNaN(ts)) return "";
  return new Date(ts).toISOString().slice(0, 10);
};

const parseDte = (expiry) => {
  const normalized = normalizeExpiry(expiry);
  if (!normalized) return 999;
  const ts = Date.parse(normalized);
  if (Number.isNaN(ts)) return 999;
  const days = Math.ceil((ts - Date.now()) / (24 * 60 * 60 * 1000));
  return Math.max(days, 0);
};

const saneStrikeForSpot = (strike, spot) => {
  if (!Number.isFinite(strike) || strike <= 0 || !Number.isFinite(spot) || spot <= 0) return false;
  return Math.abs(strike - spot) / spot < 0.5;
};

const buildSpotFallbackChain = (spot) => {
  const s = Number.isFinite(spot) && spot > 0 ? spot : 45;
  const steps = [-2, -1, -0.5, 0, 0.5, 1, 2];
  const callRows = steps.filter((x) => x >= 0).map((x, idx) => ({
    type: "call",
    strike: Number((s + x).toFixed(2)),
    bid: Math.max(0.15, Number((1.25 - x * 0.45).toFixed(2))),
    ask: Number((Math.max(0.15, Number((1.25 - x * 0.45).toFixed(2))) * 1.12).toFixed(2)),
    expiry: "2026-03-20",
    delta: clamp(0.55 - x * 0.18, 0.1, 0.75),
    iv: 0.22 + idx * 0.01,
    oi: 200 + idx * 60,
    volume: 80 + idx * 20,
  }));
  const putRows = steps.filter((x) => x <= 0).map((x, idx) => ({
    type: "put",
    strike: Number((s + x).toFixed(2)),
    bid: Math.max(0.15, Number((1.15 - Math.abs(x) * 0.35).toFixed(2))),
    ask: Number((Math.max(0.15, Number((1.15 - Math.abs(x) * 0.35).toFixed(2))) * 1.12).toFixed(2)),
    expiry: "2026-03-20",
    delta: -clamp(0.55 - Math.abs(x) * 0.18, 0.1, 0.75),
    iv: 0.22 + idx * 0.01,
    oi: 200 + idx * 60,
    volume: 80 + idx * 20,
  }));
  return [...callRows, ...putRows];
};

const estimateDelta = (type, strike, spot) => {
  if (!spot || !strike) return type === "put" ? -0.3 : 0.3;
  const moneyness = (strike - spot) / spot;
  if (type === "call") return clamp(0.5 - moneyness * 3, 0.05, 0.95);
  return -clamp(0.5 + moneyness * 3, 0.05, 0.95);
};

const pickContracts = (chain, side, targetDelta, minDte, maxDte) => {
  const scored = chain
    .filter((c) => c.type === side)
    .filter((c) => c.bid > 0 && c.ask > 0)
    .filter((c) => c.dte >= minDte && c.dte <= maxDte)
    .map((c) => {
      const m = mid(c.bid, c.ask);
      const spreadPct = m > 0 ? (c.ask - c.bid) / m : 999;
      const deltaDiff = Math.abs(Math.abs(c.delta) - targetDelta);
      const liquidityScore = (c.oi || 0) + (c.volume || 0) * 2;
      return { ...c, mid: m, spreadPct, deltaDiff, liquidityScore };
    });
  const preferred = scored
    .filter((c) => c.spreadPct <= 0.2)
    .filter((c) => c.oi >= 100 && c.volume >= 20)
    .filter((c) => c.iv > 0.3 && c.iv <= 2.5)
    .sort((a, b) => a.deltaDiff - b.deltaDiff || b.liquidityScore - a.liquidityScore || a.spreadPct - b.spreadPct)
    .slice(0, 3);
  if (preferred.length) return preferred;
  return scored
    .filter((c) => c.spreadPct <= 0.12)
    .filter((c) => c.volume > 0 || c.oi > 0)
    .sort((a, b) => a.deltaDiff - b.deltaDiff || b.liquidityScore - a.liquidityScore || a.spreadPct - b.spreadPct)
    .slice(0, 3);
};

const OptionsPage = () => {
  const [ticker, setTicker] = useState("AAPL");
  const [underlying, setUnderlying] = useState(180);
  const [chain, setChain] = useState(fallbackChain);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [connectionState, setConnectionState] = useState("idle");
  const [lastChecked, setLastChecked] = useState("");
  const [feedState, setFeedState] = useState("disconnected");
  const [liveCandles, setLiveCandles] = useState([]);
  const [liveSignal, setLiveSignal] = useState(null);
  const [lastFeedUpdate, setLastFeedUpdate] = useState("");
  const [preSignal, setPreSignal] = useState(null);
  const [preError, setPreError] = useState("");
  const [preLoading, setPreLoading] = useState(false);
  const [sniperCandidates, setSniperCandidates] = useState([]);
  const [sniperLoading, setSniperLoading] = useState(false);
  const [sniperError, setSniperError] = useState("");

  const wsRef = useRef(null);
  const tickerRef = useRef(ticker);
  const reconnectTimeoutRef = useRef(null);
  const isMountedRef = useRef(false);

  const fetchChain = async () => {
    try {
      setLoading(true);
      setError("");
      setConnectionState("connecting");
      setLastChecked("");
      setChain([]);
      const res = await apiFetch(`/api/options-strategies?ticker=${ticker}&underlying=${underlying || ""}`);
      if (res.ok) {
        const data = await res.json();
        const uiSpot = Number(underlying || 0);
        const apiSpot = Number(data?.underlying || 0);
        const spot = uiSpot > 0 ? uiSpot : apiSpot;
        const shouldTrustApiSpot =
          apiSpot > 0 && (uiSpot <= 0 || Math.abs(apiSpot - uiSpot) / Math.max(uiSpot, 1) < 0.5);
        if (shouldTrustApiSpot) setUnderlying(apiSpot);
        const mapped = (data?.strategies || []).map((s) => {
          const strike = Number(s.strike || s.lower_strike || spot || 0);
          const bid = Number(s.bid || s.premium || 0);
          const ask = Number(s.ask || (s.premium ? s.premium * 1.1 : 0));
          const type = s.type === "cash_secured_put" || s.type === "put" ? "put" : "call";
          const delta = Number.isFinite(Number(s.delta))
            ? Number(s.delta)
            : estimateDelta(type, strike, spot);
          return {
            type,
            strike,
            expiry: normalizeExpiry(s.expiry || s.exp) || "2026-03-20",
            bid,
            ask,
            delta,
            iv: Number(s.iv || 0),
            oi: Number(s.oi || 0),
            volume: Number(s.volume || 0),
          };
        });
        const saneMapped = mapped.filter((c) => saneStrikeForSpot(c.strike, Math.max(spot, 1)));
        if (saneMapped.length) {
          setChain(saneMapped);
          setConnectionState("connected");
          return;
        }
        if (mapped.length && !saneMapped.length) {
          setChain(buildSpotFallbackChain(spot));
          setConnectionState("error");
          setError("Dropped mismatched chain rows; using spot-centered fallback contracts.");
          return;
        }
      }
      setChain(buildSpotFallbackChain(Number(underlying || 45)));
      setConnectionState("error");
      setError("Using fallback chain; no live data returned.");
    } catch (err) {
      console.warn("Options chain fetch failed, using fallback.", err);
      setChain(buildSpotFallbackChain(Number(underlying || 45)));
      setConnectionState("error");
      setError("Using fallback chain; backend not available.");
    } finally {
      setLoading(false);
      setLastChecked(new Date().toLocaleTimeString());
    }
  };

  const fetchPreBreakout = async () => {
    try {
      setPreLoading(true);
      setPreError("");
      setPreSignal(null);
      const params = new URLSearchParams({
        mode: "pre_breakout",
        limit: "60",
        qualified_only: "false",
        min_day_notional: "3000000000",
        min_price: "5",
        min_move_pct: "0",
        max_move_pct: "10",
        min_rvol: "0",
        pool_limit: "140",
      });
      const res = await apiFetch(`/api/market-signals/qualified-targets?${params}`);
      if (!res.ok) throw new Error("pre-breakout fetch failed");
      const data = await res.json();
      const sym = String(ticker || "").toUpperCase();
      const found =
        (Array.isArray(data?.targets) ? data.targets : []).find(
          (t) => String(t.symbol || "").toUpperCase() === sym
        ) || null;
      setPreSignal(found);
      if (!found) setPreError("No pre-breakout read on this ticker yet.");
    } catch (err) {
      setPreError("Pre-breakout data unavailable");
      setPreSignal(null);
    } finally {
      setPreLoading(false);
    }
  };

  const fetchSniperCandidates = async (symbol = ticker) => {
    try {
      setSniperLoading(true);
      setSniperError("");
      setSniperCandidates([]);
      const activeTicker = String(symbol || "").toUpperCase().trim();
      if (!activeTicker) {
        setSniperError("Enter a ticker first.");
        return;
      }
      const response = await apiFetch(
        `/api/options/sniper/${encodeURIComponent(activeTicker)}?top_contracts_per_ticker=5`
      );
      const data = await response.json();
      const candidates = Array.isArray(data?.candidates) ? data.candidates : [];
      setSniperCandidates(candidates);
      if (candidates.length === 0) {
        setSniperError(
          data?.message || data?.error || "No sniper contracts passed the stock + option filters."
        );
      }
    } catch (err) {
      setSniperCandidates([]);
      setSniperError("Options sniper unavailable.");
    } finally {
      setSniperLoading(false);
    }
  };

  const setupUnderlyingFeed = () => {
    const existing = wsRef.current;
    if (existing) {
      existing.onclose = null;
      existing.close();
      wsRef.current = null;
    }
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (!POLYGON_API_KEY) {
      setFeedState("error");
      return;
    }
    setFeedState("connecting");
    const websocket = new WebSocket(POLYGON_WS_URL);
    websocket.onopen = () => {
      websocket.send(JSON.stringify({ action: "auth", params: POLYGON_API_KEY }));
      websocket.send(JSON.stringify({ action: "subscribe", params: `AM.${tickerRef.current}` }));
      setFeedState("connected");
    };
    websocket.onmessage = (event) => {
      const data = JSON.parse(event.data);
      data.forEach((update) => {
        if (update.ev !== "AM" || update.sym !== tickerRef.current) return;
        const close = Number(update.c);
        const high = Number(update.h ?? close);
        const low = Number(update.l ?? close);
        const open = Number(update.o ?? close);
        const vol = Number(update.v ?? 0);
        const vw = Number(update.vw ?? NaN);
        if (!Number.isFinite(close) || close <= 0) return;
        setUnderlying(close);
        setLastFeedUpdate(new Date().toLocaleTimeString());
        const candle = {
          t: Number(update.s || update.e || Date.now()),
          o: Number.isFinite(open) ? open : close,
          h: Number.isFinite(high) ? high : close,
          l: Number.isFinite(low) ? low : close,
          c: close,
          v: Number.isFinite(vol) ? vol : 0,
          vw: Number.isFinite(vw) ? vw : null,
        };
        setLiveCandles((prev) => {
          if (!prev.length) return [candle];
          const last = prev[prev.length - 1];
          const jumpRatio = last.c > 0 ? Math.abs(candle.c - last.c) / last.c : 0;
          if (jumpRatio > 0.5) return prev;
          if (last.t === candle.t) return [...prev.slice(0, -1), candle];
          return [...prev, candle].slice(-250);
        });
      });
    };
    websocket.onerror = () => setFeedState("error");
    websocket.onclose = () => {
      setFeedState("disconnected");
      if (!isMountedRef.current) return;
      reconnectTimeoutRef.current = setTimeout(() => {
        if (isMountedRef.current && tickerRef.current) setupUnderlyingFeed();
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
    tickerRef.current = ticker;
  }, [ticker]);

  useEffect(() => {
    setChain([]);
    setError("");
    setConnectionState("idle");
    setLiveCandles([]);
    setLiveSignal(null);
    setPreSignal(null);
    setPreError("");
    setPreLoading(false);
    setSniperCandidates([]);
    setSniperError("");
    setSniperLoading(false);
    setupUnderlyingFeed();
    fetchChain();
    fetchPreBreakout();
    fetchSniperCandidates(ticker);
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
  }, [ticker]);

  useEffect(() => {
    if (!liveCandles || liveCandles.length < 30) {
      setLiveSignal({
        phase: "Insufficient Data",
        continuation: 50,
        pullbackRisk: 50,
        plan: { planLabel: "No Plan", live: { guidance: "WAIT", rMultiple: null } },
        reason: "Need more live candles",
        rvol: 0,
        moveTodayPct: 0,
      });
      return;
    }
    const closes = liveCandles.map((c) => c.c);
    const volumes = liveCandles.map((c) => c.v || 0);
    const last = liveCandles[liveCandles.length - 1];
    const rawVwap = last.vw && Number.isFinite(last.vw) ? last.vw : last.c;
    const vwapVal = rawVwap > 0 && Math.abs(rawVwap - last.c) / last.c < 0.25 ? rawVwap : last.c;
    const ema9 = ema(closes.slice(-60), 9);
    const ema21 = ema(closes.slice(-80), 21);
    const phaseInfo = computePhase(liveCandles, vwapVal);
    const distFromVwap = vwapVal > 0 ? (last.c - vwapVal) / vwapVal : 0;
    const recentVol = volumes.slice(-10).reduce((a, b) => a + b, 0) / 10;
    const baseVol = volumes.slice(-30).reduce((a, b) => a + b, 0) / 30;
    const rvol = baseVol > 0 ? recentVol / baseVol : 1;
    const recent = liveCandles.slice(-8);
    const hh = recent[recent.length - 1].h > recent[0].h;
    const hl = recent[recent.length - 1].l > recent[0].l;
    const r = rsi(closes, 14);
    const moveTodayPct = closes[0] > 0 ? ((last.c - closes[0]) / closes[0]) * 100 : 0;

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
    if (last.c < ema9) pullbackRisk += 10;
    if (last.c < vwapVal) pullbackRisk += 10;

    continuation = clamp(continuation, 0, 100);
    pullbackRisk = clamp(pullbackRisk, 0, 100);

    const plan = computeTradePlan({
      candles: liveCandles,
      vwap: vwapVal,
      ema9,
      ema21,
      phase: phaseInfo.phase,
      moveTodayPct,
      distanceFromVwap: distFromVwap,
    });

    setLiveSignal({
      phase: phaseInfo.phase,
      continuation,
      pullbackRisk,
      vwap: vwapVal,
      distFromVwap,
      ema9,
      ema21,
      rvol,
      moveTodayPct,
      plan,
      reason: [
        `Phase ${phaseInfo.phase}`,
        last.c > vwapVal ? "Above VWAP" : "Below VWAP",
        ema9 > ema21 ? "EMA9>EMA21" : "EMA9<=EMA21",
        `RVOL ${rvol.toFixed(2)}`,
        `RSI ${r.toFixed(0)}`,
      ].join(" | "),
    });
  }, [liveCandles]);

  const normalizedChain = useMemo(
    () =>
      chain
        .map((c) => {
          const strike = Number(c.strike || 0);
          const type = c.type === "put" ? "put" : "call";
          const expiry = normalizeExpiry(c.expiry) || "2026-03-20";
          const delta = Number.isFinite(Number(c.delta))
            ? Number(c.delta)
            : estimateDelta(type, strike, underlying);
          return {
            ...c,
            strike,
            type,
            bid: Number(c.bid || 0),
            ask: Number(c.ask || 0),
            delta,
            iv: Number(c.iv || 0),
            oi: Number(c.oi || 0),
            volume: Number(c.volume || 0),
            expiry,
            dte: parseDte(expiry),
          };
        })
        .filter((c) => saneStrikeForSpot(c.strike, Math.max(underlying, 1))),
    [chain, underlying]
  );

  const contractMode = useMemo(() => {
    if (!liveSignal) return { side: "call", targetDelta: 0.45, minDte: 3, maxDte: 21 };
    if (
      liveSignal.phase === "Exhaustion" ||
      liveSignal.pullbackRisk > liveSignal.continuation + 12
    ) {
      return { side: "put", targetDelta: 0.4, minDte: 3, maxDte: 21 };
    }
    if (liveSignal.phase === "Trend Expansion") {
      return { side: "call", targetDelta: 0.35, minDte: 3, maxDte: 21 };
    }
    return { side: "call", targetDelta: 0.45, minDte: 3, maxDte: 21 };
  }, [liveSignal]);

  const suggestedContracts = useMemo(
    () =>
      pickContracts(
        normalizedChain,
        contractMode.side,
        contractMode.targetDelta,
        contractMode.minDte,
        contractMode.maxDte
      ),
    [normalizedChain, contractMode]
  );

  const coveredCalls = normalizedChain
    .filter((o) => saneStrikeForSpot(o.strike, Math.max(underlying, 1)))
    .filter((o) => o.type === "call" && o.strike > underlying)
    .slice(0, 3)
    .map((o) => ({
      ...o,
      premium: mid(o.bid, o.ask),
      roi: ((mid(o.bid, o.ask) / Math.max(underlying, 1)) * 100).toFixed(2),
      breakeven: (underlying - mid(o.bid, o.ask)).toFixed(2),
    }));

  const cashSecuredPuts = normalizedChain
    .filter((o) => saneStrikeForSpot(o.strike, Math.max(underlying, 1)))
    .filter((o) => o.type === "put" && o.strike < underlying)
    .slice(0, 3)
    .map((o) => ({
      ...o,
      premium: mid(o.bid, o.ask),
      roi: ((mid(o.bid, o.ask) / Math.max(o.strike * 100, 1)) * 100).toFixed(2),
      breakeven: (o.strike - mid(o.bid, o.ask)).toFixed(2),
    }));

  const debitSpreads = (() => {
    const calls = normalizedChain.filter((o) => o.type === "call").sort((a, b) => a.strike - b.strike);
    if (calls.length < 2) return [];
    const lower = calls[0];
    const upper = calls[1];
    const cost = mid(lower.bid, lower.ask) - mid(upper.bid, upper.ask);
    const width = upper.strike - lower.strike;
    const maxProfit = width - cost;
    if (cost <= 0) return [];
    return [{ lower, upper, cost: cost.toFixed(2), maxProfit: maxProfit.toFixed(2), rr: (maxProfit / cost).toFixed(2) }];
  })();

  const connectionToneClass =
    connectionState === "connected"
      ? "is-positive"
      : connectionState === "connecting"
      ? "is-warning"
      : connectionState === "error"
      ? "is-negative"
      : "is-muted";
  const feedToneClass =
    feedState === "connected"
      ? "is-positive"
      : feedState === "connecting"
      ? "is-warning"
      : feedState === "error"
      ? "is-negative"
      : "is-muted";
  const continuationClass = Number(liveSignal?.continuation || 0) >= 65 ? "is-positive" : "is-muted";
  const riskClass = Number(liveSignal?.pullbackRisk || 0) >= 65 ? "is-negative" : "is-muted";
  const tooLateClass = liveSignal?.plan?.tooLate ? "is-negative" : "is-muted";

  return (
    <div className="options-page">
      <div className="options-page__shell">
        <div className="options-page__hero">
          <div>
            <div className="options-page__kicker">Derivatives Intelligence</div>
            <h2 className="options-page__title">Options Terminal</h2>
            <p className="options-page__subtitle">
              Rank contract ideas off the underlying tape, live signal quality, and basic chain
              liquidity instead of browsing raw option rows.
            </p>
          </div>
          <div className="options-page__badges">
            <span className={`options-status-pill ${connectionToneClass}`}>
              Chain:{" "}
              <strong>
                {connectionState === "idle"
                  ? "idle"
                  : connectionState === "connecting"
                  ? "checking"
                  : connectionState === "connected"
                  ? "live"
                  : "offline"}
              </strong>
            </span>
            <span className={`options-status-pill ${feedToneClass}`}>
              Underlying Feed: <strong>{feedState}</strong>
            </span>
            {lastChecked && (
              <span className="options-status-pill is-muted">
                Chain Checked: <strong>{lastChecked}</strong>
              </span>
            )}
            {lastFeedUpdate && (
              <span className="options-status-pill is-muted">
                Last Feed Tick: <strong>{lastFeedUpdate}</strong>
              </span>
            )}
          </div>
        </div>

        <div className="options-controls-card">
          <div className="options-controls-card__header">
            <div>
              <h3>Scanner Controls</h3>
              <p>Update the underlying, rerun the chain, and refresh contract rankings.</p>
            </div>
          </div>
          <div className="options-controls-grid">
            <label className="options-field">
              <span className="options-field__label">Ticker</span>
              <input className="options-input" value={ticker} onChange={(e) => setTicker(e.target.value.toUpperCase())} />
            </label>
            <label className="options-field">
              <span className="options-field__label">Underlying Price</span>
              <input className="options-input" type="number" value={underlying} onChange={(e) => setUnderlying(Number(e.target.value))} />
            </label>
            <div className="options-actions">
              <button className="options-btn" onClick={fetchChain} disabled={loading}>{loading ? "Loading..." : "Refresh Chain"}</button>
              <button className="options-btn secondary" onClick={fetchPreBreakout} disabled={preLoading}>{preLoading ? "Scanning..." : "Pre-Breakout Pulse"}</button>
              <button className="options-btn secondary" onClick={() => fetchSniperCandidates(ticker)} disabled={sniperLoading}>{sniperLoading ? "Ranking..." : "Refresh Sniper"}</button>
            </div>
          </div>
          {error && <div className="options-inline-alert">{error}</div>}
        </div>

        <div className="options-page__grid">
          <div className="options-page__main">
            <section className="options-panel options-panel--engine">
              <div className="options-panel__header">
                <div>
                  <h3>Underlying Engine</h3>
                  <p>Spot, phase, pre-breakout pressure, and live trade-plan context.</p>
                </div>
              </div>
              <div className="options-metric-grid">
                <div className="options-metric-card">
                  <span className="options-metric-card__label">Spot</span>
                  <strong>${fmtPrice(underlying)}</strong>
                </div>
                <div className="options-metric-card">
                  <span className="options-metric-card__label">Phase</span>
                  <strong>{liveSignal?.phase || "Insufficient Data"}</strong>
                </div>
                <div className={`options-metric-card ${continuationClass}`}>
                  <span className="options-metric-card__label">Continuation</span>
                  <strong>{Number(liveSignal?.continuation || 0).toFixed(0)}</strong>
                </div>
                <div className={`options-metric-card ${riskClass}`}>
                  <span className="options-metric-card__label">Pullback Risk</span>
                  <strong>{Number(liveSignal?.pullbackRisk || 0).toFixed(0)}</strong>
                </div>
                <div className="options-metric-card">
                  <span className="options-metric-card__label">Plan</span>
                  <strong>{liveSignal?.plan?.planLabel || "No Plan"}</strong>
                </div>
                <div className={`options-metric-card ${tooLateClass}`}>
                  <span className="options-metric-card__label">Too Late</span>
                  <strong>{liveSignal?.plan?.tooLate ? "Yes" : "No"}</strong>
                </div>
              </div>

              <div className="options-engine-note">
                <span className="options-engine-note__label">Pre-Breakout Pressure</span>
                <p>
                  {preLoading
                    ? "Loading..."
                    : preSignal
                    ? `${preSignal.engines?.pre?.state || "Watch"} (${Number(preSignal.engines?.pre?.score || 0).toFixed(0)})`
                    : "n/a"}
                  {preSignal?.engines?.pre?.triggerLevel ? ` | Trigger ${Number(preSignal.engines.pre.triggerLevel).toFixed(2)}` : ""}
                  {preSignal?.engines?.pre?.reasons?.length ? ` | ${preSignal.engines.pre.reasons.slice(0, 3).join(" | ")}` : ""}
                  {preError && !preLoading ? ` (${preError})` : ""}
                </p>
              </div>

              <div className="options-plan-grid">
                <div className="options-plan-chip"><span>Entry</span><strong>{fmtPrice(liveSignal?.plan?.entry)}</strong></div>
                <div className="options-plan-chip"><span>Stop</span><strong>{fmtPrice(liveSignal?.plan?.stop)}</strong></div>
                <div className="options-plan-chip"><span>Target 1R</span><strong>{fmtPrice(liveSignal?.plan?.targets?.target1)}</strong></div>
                <div className="options-plan-chip"><span>Target 2R</span><strong>{fmtPrice(liveSignal?.plan?.targets?.target2)}</strong></div>
                <div className="options-plan-chip"><span>Target 3R</span><strong>{fmtPrice(liveSignal?.plan?.targets?.target3)}</strong></div>
                <div className="options-plan-chip">
                  <span>Live R / Guidance</span>
                  <strong>
                    {liveSignal?.plan?.live?.rMultiple !== null && liveSignal?.plan?.live?.rMultiple !== undefined
                      ? `${liveSignal.plan.live.rMultiple.toFixed(2)}R`
                      : "-"}{" "}
                    / {liveSignal?.plan?.live?.guidance || "WAIT"}
                  </strong>
                </div>
              </div>

              <div className="options-footnote">{liveSignal?.reason || "Waiting for underlying candles..."}</div>
            </section>

            <section className="options-panel">
              <div className="options-panel__header">
                <div>
                  <h3>Suggested Contracts ({contractMode.side.toUpperCase()})</h3>
                  <p>
                    Target delta ~{contractMode.targetDelta.toFixed(2)} | DTE {contractMode.minDte}-{contractMode.maxDte} | spread &lt;= 20%, OI &gt;= 100, Vol &gt;= 20, IV 30-250%
                  </p>
                </div>
              </div>
              {suggestedContracts.length === 0 ? (
                <div className="options-empty-state">No liquid contracts matched the current delta, spread, and liquidity filters.</div>
              ) : (
                <div className="options-list">
                  {suggestedContracts.map((c, idx) => (
                    <article key={`${c.type}-${c.strike}-${c.expiry}-${idx}`} className="options-row-card">
                      <div className="options-row-card__top">
                        <strong>{c.type.toUpperCase()} ${c.strike}</strong>
                        <span>{c.expiry} | {c.dte} DTE</span>
                      </div>
                      <div className="options-row-card__stats">
                        <span>Bid/Ask ${c.bid.toFixed(2)} / ${c.ask.toFixed(2)}</span>
                        <span>Mid ${c.mid.toFixed(2)}</span>
                        <span>Spread {(c.spreadPct * 100).toFixed(1)}%</span>
                        <span>Delta {Number(c.delta).toFixed(2)}</span>
                        <span>IV {(Number(c.iv || 0) * 100).toFixed(1)}%</span>
                        <span>OI {c.oi}</span>
                        <span>Vol {c.volume}</span>
                      </div>
                    </article>
                  ))}
                </div>
              )}
            </section>

            <section className="options-panel">
              <div className="options-panel__header">
                <div>
                  <h3>Option Sniper</h3>
                  <p>Breakout-ready stock filter plus cheap call selector for smaller contracts.</p>
                </div>
              </div>
              {sniperLoading ? (
                <div className="options-empty-state">Scoring sniper candidates...</div>
              ) : sniperCandidates.length === 0 ? (
                <div className="options-empty-state">{sniperError || "No sniper candidates yet."}</div>
              ) : (
                <div className="options-list">
                  {sniperCandidates.map((c, idx) => (
                    <article key={`sniper-${c.ticker}-${c.strike}-${c.expiry}-${idx}`} className="options-row-card">
                      <div className="options-row-card__top">
                        <strong>{c.ticker} | {String(c.type || "").toUpperCase()} ${Number(c.strike || 0).toFixed(2)}</strong>
                        <span>{c.expiry}</span>
                      </div>
                      <div className="options-row-card__stats">
                        <span>Stock ${Number(c.stock_price || 0).toFixed(2)}</span>
                        <span>Combined {Number(c.combined_score || 0).toFixed(2)}</span>
                        <span>Breakout Dist {fmtPct(c.dist_to_breakout_pct || 0)}</span>
                        <span>Bid/Ask ${Number(c.bid || 0).toFixed(2)} / ${Number(c.ask || 0).toFixed(2)}</span>
                        <span>Delta {Number(c.delta || 0).toFixed(2)}</span>
                        <span>Spread {(Number(c.spread_pct || 0) * 100).toFixed(1)}%</span>
                        <span>OI {Number(c.open_interest || 0).toLocaleString()} | Vol {Number(c.volume || 0).toLocaleString()}</span>
                        <span>Setup {Number(c.setup_score || 0).toFixed(2)} | Contract {Number(c.contract_score || 0).toFixed(2)}</span>
                      </div>
                    </article>
                  ))}
                </div>
              )}
            </section>
          </div>

          <aside className="options-page__side">
            <section className="options-panel options-panel--compact">
              <div className="options-panel__header"><div><h3>Covered Calls</h3><p>Out-of-the-money income ideas above spot.</p></div></div>
              {coveredCalls.length === 0 ? <div className="options-empty-state">No OTM calls found.</div> : <div className="options-side-list">{coveredCalls.map((c, idx) => <div key={idx} className="options-side-item"><strong>${c.strike}</strong><span>{c.expiry}</span><p>Premium ${c.premium} | ROI {c.roi}% | Breakeven ${c.breakeven}</p></div>)}</div>}
            </section>
            <section className="options-panel options-panel--compact">
              <div className="options-panel__header"><div><h3>Cash-Secured Puts</h3><p>Put income levels beneath current spot.</p></div></div>
              {cashSecuredPuts.length === 0 ? <div className="options-empty-state">No puts below spot found.</div> : <div className="options-side-list">{cashSecuredPuts.map((p, idx) => <div key={idx} className="options-side-item"><strong>${p.strike}</strong><span>{p.expiry}</span><p>Premium ${p.premium} | ROI {p.roi}% | Breakeven ${p.breakeven}</p></div>)}</div>}
            </section>
            <section className="options-panel options-panel--compact">
              <div className="options-panel__header"><div><h3>Debit Call Spread</h3><p>Simple vertical for directional continuation.</p></div></div>
              {debitSpreads.length === 0 ? <div className="options-empty-state">Not enough call strikes.</div> : <div className="options-side-list">{debitSpreads.map((s, idx) => <div key={idx} className="options-side-item"><strong>Long ${s.lower.strike} / Short ${s.upper.strike}</strong><span>{s.lower.expiry}</span><p>Cost ${s.cost} | Max Profit ${s.maxProfit} | R/R {s.rr}x</p></div>)}</div>}
            </section>
          </aside>
        </div>
      </div>
    </div>
  );
};

export default OptionsPage;
