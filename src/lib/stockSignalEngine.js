const clamp = (n, lo, hi) => Math.max(lo, Math.min(hi, n));

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

export const computeLiveSignalsFromBars = (candles) => {
  if (!candles || candles.length < 30) {
    return {
      score: 50,
      confidence: "Low",
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
  const score = clamp(
    Math.round(
      continuation * 0.65 +
      (100 - pullbackRisk) * 0.35 +
      (biasDelta >= 15 ? 8 : 0) -
      (biasDelta <= -15 ? 8 : 0)
    ),
    0,
    100
  );
  let confidence = "Low";
  if (score > 80) confidence = "High";
  else if (score > 60) confidence = "Medium";
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
    score,
    confidence,
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
