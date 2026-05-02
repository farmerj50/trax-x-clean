/* eslint-disable react-hooks/exhaustive-deps */
import React, { useEffect, useMemo, useState } from "react";
import { apiFetch } from "../apiClient";
import "./PremarketIntelligencePage.css";

const formatPct = (value) => {
  const number = Number(value || 0);
  const prefix = number > 0 ? "+" : "";
  return `${prefix}${number.toFixed(2)}%`;
};

const formatVolume = (value) => {
  const number = Number(value || 0);
  if (!Number.isFinite(number)) return "-";
  if (number >= 1_000_000_000) return `${(number / 1_000_000_000).toFixed(2)}B`;
  if (number >= 1_000_000) return `${(number / 1_000_000).toFixed(2)}M`;
  if (number >= 1_000) return `${(number / 1_000).toFixed(1)}K`;
  return `${Math.round(number)}`;
};

const formatMoney = (value) => {
  const number = Number(value || 0);
  if (!Number.isFinite(number) || number <= 0) return "-";
  if (number >= 1_000_000_000_000) return `$${(number / 1_000_000_000_000).toFixed(2)}T`;
  if (number >= 1_000_000_000) return `$${(number / 1_000_000_000).toFixed(2)}B`;
  if (number >= 1_000_000) return `$${(number / 1_000_000).toFixed(2)}M`;
  return `$${number.toFixed(0)}`;
};

const formatTradeMoney = (value) => {
  if (value === "" || value === null || value === undefined) return "-";
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  return `$${number.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};

const parsePositiveNumber = (value) => {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : 0;
};

const firstPositive = (...values) => {
  for (const value of values) {
    const number = parsePositiveNumber(value);
    if (number > 0) return number;
  }
  return 0;
};

const formatPressureState = (value) => {
  const normalized = String(value || "").replace(/_/g, " ").trim();
  if (!normalized) return "early watch";
  return normalized.charAt(0).toUpperCase() + normalized.slice(1);
};

const formatTriggerFlag = (value) => {
  const normalized = String(value || "").replace(/_/g, " ").trim();
  if (!normalized) return "";
  return normalized
    .split(" ")
    .map((part) => (part ? part.charAt(0).toUpperCase() + part.slice(1) : ""))
    .join(" ");
};

const getDisplayScore = (stock) => Number(stock?.detectorScore ?? stock?.earlyPressureScore ?? stock?.score ?? 0);

const getDisplayState = (stock) =>
  String(
    stock?.detectorState ??
      stock?.earlyPressureState ??
      stock?.setupType ??
      stock?.conviction ??
      "watch"
  ).replace(/_/g, " ");

const getDisplaySummary = (stock) => {
  const state = String(stock?.detectorState || stock?.earlyPressureState || "").toLowerCase();
  if (state === "triggered") return "Triggered";
  if (state === "arming") return "Arming";
  if (state === "watch") return "Watch";
  if (state === "near_breakout") return "Near breakout";
  if (state === "building_pressure") return "Building pressure";
  return formatPressureState(getDisplayState(stock));
};

const scoreColor = (score) => {
  if (score >= 85) return "#22c55e";
  if (score >= 70) return "#f59e0b";
  return "#93c5fd";
};

const toneColor = (value) => {
  if (value > 0.1) return "#22c55e";
  if (value < -0.1) return "#ef4444";
  return "#e2e8f0";
};

const tileAccent = (row) => {
  const sentiment = Number(row?.colorMetric ?? row?.sentiment ?? 0);
  if (sentiment >= 0.15) return "rgba(34,197,94,0.28)";
  if (sentiment <= -0.15) return "rgba(239,68,68,0.28)";
  return "rgba(56,189,248,0.24)";
};

const tileBackground = (row) => {
  const score = getDisplayScore(row);
  if (score >= 85) return "linear-gradient(180deg, rgba(22,101,52,0.68), rgba(6,78,59,0.92))";
  if (score >= 70) return "linear-gradient(180deg, rgba(146,64,14,0.68), rgba(120,53,15,0.92))";
  return "linear-gradient(180deg, rgba(30,41,59,0.74), rgba(15,23,42,0.96))";
};

const tileSpan = (sizeMetric) => {
  const size = Number(sizeMetric || 0);
  if (size >= 8_000_000) return { gridColumn: "span 2", gridRow: "span 2" };
  if (size >= 2_000_000) return { gridColumn: "span 2", gridRow: "span 1" };
  return { gridColumn: "span 1", gridRow: "span 1" };
};

const graphNodeColor = (type) => {
  if (type === "stock") return "#67e8f9";
  if (type === "sector") return "#f59e0b";
  if (type === "peer") return "#22c55e";
  if (type === "headline") return "#c084fc";
  return "#94a3b8";
};

const RelationshipGraph = ({ graph }) => {
  const nodes = Array.isArray(graph?.nodes) ? graph.nodes : [];
  if (nodes.length === 0) {
    return <div className="premarket-empty">Relationship graph is not available for this ticker yet.</div>;
  }

  const centerNode = nodes.find((node) => node.type === "stock") || nodes[0];
  const orbitNodes = nodes.filter((node) => node.id !== centerNode.id);
  const center = { x: 172, y: 118 };
  const radius = 84;
  const positioned = orbitNodes.map((node, index) => {
    const angle = (Math.PI * 2 * index) / Math.max(orbitNodes.length, 1) - Math.PI / 2;
    return {
      ...node,
      x: center.x + radius * Math.cos(angle),
      y: center.y + radius * Math.sin(angle),
    };
  });

  return (
    <div className="premarket-graph">
      <svg viewBox="0 0 344 236" width="100%" height="236" role="img" aria-label="Relationship graph">
        <defs>
          <filter id="glow">
            <feGaussianBlur stdDeviation="5" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {positioned.map((node) => (
          <line
            key={`edge-${centerNode.id}-${node.id}`}
            x1={center.x}
            y1={center.y}
            x2={node.x}
            y2={node.y}
            stroke="rgba(148,163,184,0.35)"
            strokeWidth="1.2"
          />
        ))}

        <circle cx={center.x} cy={center.y} r="28" fill="#0f172a" stroke={graphNodeColor(centerNode.type)} strokeWidth="2.5" filter="url(#glow)" />
        <text x={center.x} y={center.y + 5} textAnchor="middle" fill="#f8fafc" fontSize="14" fontWeight="700">
          {centerNode.label}
        </text>

        {positioned.map((node) => (
          <g key={node.id}>
            <circle cx={node.x} cy={node.y} r="18" fill="#0f172a" stroke={graphNodeColor(node.type)} strokeWidth="2" />
            <text x={node.x} y={node.y + 4} textAnchor="middle" fill="#e2e8f0" fontSize="9">
              {String(node.label || "").slice(0, 10)}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
};

const ScoreBreakdown = ({ breakdown }) => {
  const rows = useMemo(() => {
    if (!breakdown) return [];
    return [
      ["Premarket volume", breakdown.premarketVolumeScore],
      ["Gap strength", breakdown.gapStrengthScore],
      ["Catalyst quality", breakdown.catalystScore],
      ["Sentiment", breakdown.sentimentScore],
      ["Liquidity", breakdown.liquidityScore],
      ["Float pressure", breakdown.floatPressureScore],
      ["Sector strength", breakdown.sectorStrengthScore],
      ["Options proxy", breakdown.optionsScore],
      ["Contract signal", breakdown.contractScore],
      ["Political signal", breakdown.politicalSignalScore],
    ];
  }, [breakdown]);

  if (rows.length === 0) {
    return null;
  }

  return (
    <div className="premarket-breakdown">
      {rows.map(([label, value]) => (
        <div key={label} className="premarket-breakdown-row">
          <div>
            <div style={{ fontSize: "12px", color: "#cbd5e1", marginBottom: "6px" }}>{label}</div>
            <div className="premarket-breakdown-track">
              <div className="premarket-breakdown-bar" style={{ width: `${Math.max(0, Math.min(100, Number(value || 0)))}%` }} />
            </div>
          </div>
          <div style={{ textAlign: "right", fontSize: "12px", color: "#f8fafc", fontWeight: 700 }}>{Number(value || 0).toFixed(0)}</div>
        </div>
      ))}
    </div>
  );
};

const getSuggestedTradePrices = (stock, side) => {
  const price = firstPositive(
    stock?.premarketPrice,
    stock?.price,
    stock?.lastPrice,
    stock?.close,
    stock?.previousClose
  );
  const high = firstPositive(stock?.premarketHigh, price);
  const low = firstPositive(stock?.premarketLow, price ? price * 0.97 : 0);

  if (side === "short") {
    const entry = low || price;
    const stop = high > entry ? high : entry * 1.03;
    return { entry, stop };
  }

  const entry = high || price;
  const stop = low > 0 && low < entry ? low : entry * 0.97;
  return { entry, stop };
};

const TradeRiskCalculator = ({ selectedStock }) => {
  const [calculator, setCalculator] = useState({
    accountSize: "10000",
    riskPercent: "1",
    side: "long",
    entryPrice: "",
    stopPrice: "",
    rewardMultiple: "2",
  });

  const symbol = selectedStock?.ticker || "Selected ticker";

  const updateCalculator = (key, value) => {
    setCalculator((current) => ({ ...current, [key]: value }));
  };

  const applySelectedSetupPrices = () => {
    if (!selectedStock) return;
    const { entry, stop } = getSuggestedTradePrices(selectedStock, calculator.side);
    setCalculator((current) => ({
      ...current,
      entryPrice: entry ? entry.toFixed(2) : current.entryPrice,
      stopPrice: stop ? stop.toFixed(2) : current.stopPrice,
    }));
  };

  const result = useMemo(() => {
    const accountSize = parsePositiveNumber(calculator.accountSize);
    const riskPercent = parsePositiveNumber(calculator.riskPercent);
    const entryPrice = parsePositiveNumber(calculator.entryPrice);
    const stopPrice = parsePositiveNumber(calculator.stopPrice);
    const rewardMultiple = parsePositiveNumber(calculator.rewardMultiple);
    const isShort = calculator.side === "short";
    const riskPerShare = isShort ? stopPrice - entryPrice : entryPrice - stopPrice;
    const riskBudget = accountSize * (riskPercent / 100);

    if (!accountSize || !riskPercent || !entryPrice || !stopPrice || !rewardMultiple || riskPerShare <= 0) {
      return {
        valid: false,
        riskBudget,
        riskPerShare,
        shares: 0,
        positionValue: 0,
        stopExit: stopPrice,
        targetExit: 0,
        maxLoss: 0,
        potentialGain: 0,
      };
    }

    const shares = Math.floor(riskBudget / riskPerShare);
    const positionValue = shares * entryPrice;
    const targetExit = isShort
      ? entryPrice - riskPerShare * rewardMultiple
      : entryPrice + riskPerShare * rewardMultiple;
    const maxLoss = shares * riskPerShare;
    const potentialGain = shares * Math.abs(targetExit - entryPrice);

    return {
      valid: shares > 0,
      riskBudget,
      riskPerShare,
      shares,
      positionValue,
      stopExit: stopPrice,
      targetExit,
      maxLoss,
      potentialGain,
    };
  }, [calculator]);

  return (
    <section className="risk-calculator-panel">
      <div className="premarket-heatmap-header">
        <div>
          <h3 className="panel-title" style={{ marginBottom: "6px" }}>Entry / Exit Calculator</h3>
          <div className="panel-subtitle">Position size based on account value, risk percent, entry, and stop.</div>
        </div>
        <div className="top-badges">
          <span className="premarket-mini-chip">{symbol}</span>
          <button className="btn-secondary risk-use-selected" type="button" onClick={applySelectedSetupPrices} disabled={!selectedStock}>
            Use selected setup
          </button>
        </div>
      </div>

      <div className="risk-calculator-grid">
        <div className="risk-inputs">
          <label className="risk-field">
            <span>Account Size</span>
            <input
              type="number"
              min="0"
              step="100"
              value={calculator.accountSize}
              onChange={(event) => updateCalculator("accountSize", event.target.value)}
            />
          </label>
          <label className="risk-field">
            <span>Risk %</span>
            <input
              type="number"
              min="0"
              step="0.1"
              value={calculator.riskPercent}
              onChange={(event) => updateCalculator("riskPercent", event.target.value)}
            />
          </label>
          <label className="risk-field">
            <span>Side</span>
            <select value={calculator.side} onChange={(event) => updateCalculator("side", event.target.value)}>
              <option value="long">Long</option>
              <option value="short">Short</option>
            </select>
          </label>
          <label className="risk-field">
            <span>Entry Price</span>
            <input
              type="number"
              min="0"
              step="0.01"
              value={calculator.entryPrice}
              onChange={(event) => updateCalculator("entryPrice", event.target.value)}
            />
          </label>
          <label className="risk-field">
            <span>Stop Exit</span>
            <input
              type="number"
              min="0"
              step="0.01"
              value={calculator.stopPrice}
              onChange={(event) => updateCalculator("stopPrice", event.target.value)}
            />
          </label>
          <label className="risk-field">
            <span>Reward/Risk</span>
            <input
              type="number"
              min="0"
              step="0.25"
              value={calculator.rewardMultiple}
              onChange={(event) => updateCalculator("rewardMultiple", event.target.value)}
            />
          </label>
        </div>

        <div className="risk-results">
          <div className="risk-result-card risk-result-card-primary">
            <span>Shares</span>
            <strong>{result.valid ? result.shares.toLocaleString() : "-"}</strong>
          </div>
          <div className="risk-result-card">
            <span>Entry</span>
            <strong>{formatTradeMoney(calculator.entryPrice)}</strong>
          </div>
          <div className="risk-result-card">
            <span>Stop Exit</span>
            <strong>{result.stopExit > 0 ? formatTradeMoney(result.stopExit) : "-"}</strong>
          </div>
          <div className="risk-result-card">
            <span>Target Exit</span>
            <strong>{result.valid ? formatTradeMoney(result.targetExit) : "-"}</strong>
          </div>
          <div className="risk-result-card">
            <span>Position Value</span>
            <strong>{result.valid ? formatTradeMoney(result.positionValue) : "-"}</strong>
          </div>
          <div className="risk-result-card">
            <span>Max Risk</span>
            <strong>{result.valid ? formatTradeMoney(result.maxLoss) : result.riskBudget > 0 ? formatTradeMoney(result.riskBudget) : "-"}</strong>
          </div>
          <div className="risk-result-card">
            <span>Risk / Share</span>
            <strong>{result.riskPerShare > 0 ? formatTradeMoney(result.riskPerShare) : "-"}</strong>
          </div>
          <div className="risk-result-card">
            <span>Potential Gain</span>
            <strong>{result.valid ? formatTradeMoney(result.potentialGain) : "-"}</strong>
          </div>
        </div>
      </div>

      {!result.valid ? (
        <div className="risk-calculator-note">
          Enter an account size, risk percent, entry, stop, and reward/risk. For long trades, stop must be below entry. For short trades, stop must be above entry.
        </div>
      ) : null}
    </section>
  );
};

const PremarketIntelligencePage = () => {
  const [filters, setFilters] = useState({
    minGap: "1",
    minVolume: "100000",
    sector: "",
    positiveOnly: true,
    limit: "8",
  });
  const [payload, setPayload] = useState({
    topPicks: [],
    earlySetupWatch: [],
    heatmap: [],
    stocks: [],
    marketSummary: {},
    marketSession: "premarket",
    timestamp: "",
  });
  const [selectedTicker, setSelectedTicker] = useState("");
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");

  const sectors = useMemo(() => {
    const values = Array.from(new Set((payload.stocks || []).map((item) => item.sector).filter(Boolean)));
    return values.sort((a, b) => a.localeCompare(b));
  }, [payload.stocks]);

  const loadDetail = async (ticker) => {
    if (!ticker) {
      setDetail(null);
      return;
    }
    try {
      setDetailLoading(true);
      const data = await apiFetch(`/api/premarket/intelligence/${ticker}`, { timeoutMs: 20000 });
      setDetail(data);
    } catch (err) {
      setDetail(null);
    } finally {
      setDetailLoading(false);
    }
  };

  const loadPageData = async (nextFilters = filters, preferredTicker = "") => {
    const hasExistingData = Boolean(payload.topPicks?.length || payload.heatmap?.length || payload.stocks?.length);
    try {
      setLoading(true);
      setError("");
      const params = new URLSearchParams({
        limit: nextFilters.limit || "8",
        min_gap_pct: nextFilters.minGap || "0",
        min_volume: nextFilters.minVolume || "0",
        positive_only: String(nextFilters.positiveOnly),
      });
      if (nextFilters.sector) {
        params.set("sector", nextFilters.sector);
      }

      const data = await apiFetch(`/api/premarket/intelligence?${params}`, { timeoutMs: 35000 });
      setPayload(data);

      const fallbackTicker = preferredTicker && data?.stocks?.some((item) => item.ticker === preferredTicker)
        ? preferredTicker
        : data?.topPicks?.[0]?.ticker || "";

      setSelectedTicker(fallbackTicker);
      loadDetail(fallbackTicker);
    } catch (err) {
      if (!hasExistingData) {
        setPayload({
          topPicks: [],
          earlySetupWatch: [],
          heatmap: [],
          stocks: [],
          marketSummary: {},
          marketSession: "premarket",
          timestamp: "",
        });
        setSelectedTicker("");
        setDetail(null);
      }
      const errorMessage = String(err?.message || "");
      setError(
        errorMessage.includes("Failed to fetch") || errorMessage.includes("timed out")
          ? "Unable to refresh the premarket scan right now. Please try again in a moment."
          : errorMessage || "Failed to load premarket intelligence."
      );
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadPageData();
  }, []);

  const handleFilterChange = (key, value) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
  };

  const handleApplyFilters = () => {
    loadPageData(filters, selectedTicker);
  };

  const handleResetFilters = () => {
    const reset = {
      minGap: "1",
      minVolume: "100000",
      sector: "",
      positiveOnly: true,
      limit: "8",
    };
    setFilters(reset);
    loadPageData(reset);
  };

  const handleSelectTicker = async (ticker) => {
    setSelectedTicker(ticker);
    await loadDetail(ticker);
  };

  const selectedStock = detail || payload.topPicks.find((item) => item.ticker === selectedTicker) || null;
  const selectedDisplayScore = getDisplayScore(selectedStock);
  const selectedDisplaySummary = getDisplaySummary(selectedStock);
  const timestampLabel = payload.timestamp ? new Date(payload.timestamp).toLocaleString() : "Waiting for first scan";

  return (
    <div className="premarket-page">
      <div className="premarket-shell">
        <div className="premarket-hero">
          <div className="premarket-header-row">
            <div>
              <div className="premarket-kicker">Premium Intelligence Surface</div>
              <h2 className="premarket-title">Premarket Intelligence</h2>
              <p className="premarket-subtitle">
                This belongs on its own page. The product story is cleaner, the scoring can stay opinionated, and the user sees ranked premarket setups instead of a generic stock list with extra noise bolted on.
              </p>
            </div>

            <div className="top-badges">
              <span className="status-badge"><strong>Session:</strong> {payload.marketSession || "premarket"}</span>
              <span className="status-badge"><strong>Last updated:</strong> {timestampLabel}</span>
              <span className="status-badge"><strong>Top sector:</strong> {payload.marketSummary?.highestConvictionSector || "Unclassified"}</span>
              <span className="status-badge"><strong>Early watch:</strong> {Number(payload.marketSummary?.earlySetupCount || 0)}</span>
            </div>
          </div>

          <div className="filters-row">
            <div className="filter-group">
              <label className="filter-label" htmlFor="premarket-min-gap">Min Gap %</label>
              <input
                id="premarket-min-gap"
                className="filter-input"
                type="number"
                value={filters.minGap}
                onChange={(e) => handleFilterChange("minGap", e.target.value)}
              />
            </div>

            <div className="filter-group">
              <label className="filter-label" htmlFor="premarket-min-volume">Min Premarket Volume</label>
              <input
                id="premarket-min-volume"
                className="filter-input"
                type="number"
                value={filters.minVolume}
                onChange={(e) => handleFilterChange("minVolume", e.target.value)}
              />
            </div>

            <div className="filter-group">
              <label className="filter-label" htmlFor="premarket-sector">Sector</label>
              <select
                id="premarket-sector"
                className="filter-select"
                value={filters.sector}
                onChange={(e) => handleFilterChange("sector", e.target.value)}
              >
                <option value="">All sectors</option>
                {sectors.map((sector) => (
                  <option key={sector} value={sector}>
                    {sector}
                  </option>
                ))}
              </select>
            </div>

            <div className="filter-group">
              <label className="filter-label" htmlFor="premarket-limit">Top Picks</label>
              <select
                id="premarket-limit"
                className="filter-select"
                value={filters.limit}
                onChange={(e) => handleFilterChange("limit", e.target.value)}
              >
                <option value="5">5</option>
                <option value="8">8</option>
                <option value="10">10</option>
                <option value="12">12</option>
              </select>
            </div>

            <div className="filter-checkbox-wrap">
              <label className="premarket-toggle" htmlFor="premarket-positive-only">
                <input
                  id="premarket-positive-only"
                  type="checkbox"
                  checked={filters.positiveOnly}
                  onChange={(e) => handleFilterChange("positiveOnly", e.target.checked)}
                />
                Only positive catalyst names
              </label>
            </div>

            <div className="premarket-actions">
              <button className="btn-primary" type="button" onClick={handleApplyFilters} disabled={loading}>
                {loading ? (
                  <>
                    <span className="btn-spinner" aria-hidden="true" />
                    Refreshing...
                  </>
                ) : (
                  "Refresh scan"
                )}
              </button>
              <button className="btn-secondary" type="button" onClick={handleResetFilters} disabled={loading}>
                Reset
              </button>
            </div>
          </div>
        </div>

        <div className="content-grid">
          <aside className="panel left-rail">
            <div className="panel-inner">
              <h3 className="panel-title">AI Best Picks</h3>
              <p className="panel-subtitle">Code does the ranking. The intelligence layer rewrites the reasons and the risks.</p>

              {loading ? <p className="premarket-loading">Scanning premarket setups...</p> : null}
              {error ? <p className="premarket-error">{error}</p> : null}
              {!loading && payload.topPicks.length === 0 ? <div className="premarket-empty">No names cleared the current filters.</div> : null}

              <div className="premarket-picks">
                {payload.topPicks.map((stock) => (
                  (() => {
                    const displayScore = getDisplayScore(stock);
                    const displaySummary = getDisplaySummary(stock);
                    return (
                      <button
                        key={stock.ticker}
                        type="button"
                        className={`pick-card ${selectedTicker === stock.ticker ? "active" : ""}`}
                        onClick={() => handleSelectTicker(stock.ticker)}
                        style={{ textAlign: "left" }}
                      >
                        <div className="pick-header">
                          <div>
                            <div className="pick-ticker">{stock.ticker}</div>
                            <div style={{ marginTop: "6px", fontSize: "12px", color: "#94a3b8" }}>{displaySummary}</div>
                          </div>
                          <div className="pick-score" style={{ color: scoreColor(displayScore) }}>
                            {displayScore.toFixed(0)}
                          </div>
                        </div>

                        <div className="premarket-meta">
                          <span className="premarket-mini-chip">{formatPct(stock.gapPercent)}</span>
                          <span className="premarket-mini-chip">{formatVolume(stock.premarketVolume)} vol</span>
                          <span className="premarket-mini-chip">{displaySummary}</span>
                        </div>

                        <div className="premarket-meta">
                          {(stock.triggerFlags || []).slice(0, 2).map((flag) => (
                            <span key={`${stock.ticker}-${flag}`} className="premarket-mini-chip">
                              {formatTriggerFlag(flag)}
                            </span>
                          ))}
                        </div>

                        <div className="premarket-pick-copy">{stock.aiSummary}</div>
                        <div className="premarket-pick-copy" style={{ color: "#94a3b8" }}>
                          Risk: {stock.risk}
                        </div>
                      </button>
                    );
                  })()
                ))}
              </div>
            </div>
          </aside>

          <main>
            <div className="summary-grid">
              <div className="summary-card">
                <div className="summary-label">Bullish Count</div>
                <div className="summary-value">{Number(payload.marketSummary?.bullishCount || 0)}</div>
              </div>
              <div className="summary-card">
                <div className="summary-label">Bearish Count</div>
                <div className="summary-value">{Number(payload.marketSummary?.bearishCount || 0)}</div>
              </div>
              <div className="summary-card">
                <div className="summary-label">Selected Setup</div>
                <div className="summary-value">
                  {selectedStock?.ticker || "None"}
                </div>
              </div>
              <div className="summary-card">
                <div className="summary-label">Early Setup Watch</div>
                <div className="summary-value">{Number(payload.marketSummary?.earlySetupCount || 0)}</div>
              </div>
            </div>

            <TradeRiskCalculator selectedStock={selectedStock} />

            {payload.earlySetupWatch?.length ? (
              <div className="early-watch-panel" style={{ marginTop: "18px" }}>
                <div className="premarket-heatmap-header">
                  <div>
                    <h3 className="panel-title" style={{ marginBottom: "6px" }}>Early Setup Watch</h3>
                    <div className="panel-subtitle">Developing premarket names with improving pressure near actionable levels.</div>
                  </div>
                  <div className="top-badges">
                    <span className="premarket-mini-chip">Pressure score = early setup quality</span>
                    <span className="premarket-mini-chip">Near high = closer to breakout</span>
                  </div>
                </div>

                <div className="early-watch-grid">
                  {payload.earlySetupWatch.map((stock) => (
                    <button
                      key={`early-${stock.ticker}`}
                      type="button"
                      className={`early-watch-card ${selectedTicker === stock.ticker ? "active" : ""}`}
                      onClick={() => handleSelectTicker(stock.ticker)}
                    >
                      <div className="pick-header">
                        <div>
                          <div className="pick-ticker">{stock.ticker}</div>
                          <div className="early-watch-state">{getDisplaySummary(stock)}</div>
                        </div>
                        <div className="pick-score" style={{ color: scoreColor(getDisplayScore(stock)) }}>
                          {getDisplayScore(stock).toFixed(0)}
                        </div>
                      </div>

                      <div className="premarket-meta">
                        <span className="premarket-mini-chip">{formatPct(stock.gapPercent)}</span>
                        <span className="premarket-mini-chip">{formatVolume(stock.premarketVolume)} vol</span>
                        <span className="premarket-mini-chip">{Number(stock.distanceToPremarketHighPct || 0).toFixed(2)}% from PM high</span>
                        {(stock.triggerFlags || []).slice(0, 2).map((flag) => (
                          <span key={`early-${stock.ticker}-${flag}`} className="premarket-mini-chip">
                            {formatTriggerFlag(flag)}
                          </span>
                        ))}
                      </div>

                      <div className="premarket-pick-copy">{stock.aiSummary}</div>
                    </button>
                  ))}
                </div>
              </div>
            ) : null}

            <div className="heatmap-panel" style={{ marginTop: "18px" }}>
              <div className="premarket-heatmap-header">
                <div>
                  <h3 className="panel-title" style={{ marginBottom: "6px" }}>Heat Map</h3>
                  <div className="panel-subtitle">Ranked scan view first. Relationship graph second. That order is correct for this feature.</div>
                </div>
                <div className="top-badges">
                  <span className="premarket-mini-chip">Tile size = premarket volume</span>
                  <span className="premarket-mini-chip">Tile tone = sentiment</span>
                </div>
              </div>

              {loading ? (
                <p className="premarket-loading">Building heat map...</p>
              ) : payload.heatmap.length === 0 ? (
                <div className="premarket-empty">No heat map data is available right now.</div>
              ) : (
                <div className="premarket-heatmap-grid">
                  {payload.heatmap.map((stock) => (
                    <button
                      key={stock.ticker}
                      type="button"
                      className={`heat-tile ${selectedTicker === stock.ticker ? "active" : ""}`}
                      style={{
                        ...tileSpan(stock.sizeMetric),
                        background: tileBackground(stock),
                        boxShadow: selectedTicker === stock.ticker ? "0 16px 36px rgba(8,145,178,0.22)" : "none",
                        textAlign: "left",
                      }}
                      onClick={() => handleSelectTicker(stock.ticker)}
                    >
                      <div className="premarket-heatmap-glow" style={{ background: tileAccent(stock) }} />
                      <div className="premarket-heatmap-symbol">{stock.ticker}</div>
                      <div className="premarket-heatmap-metrics">
                        <div style={{ color: toneColor(stock.colorMetric) }}>{formatPct(stock.gapPercent)}</div>
                        <div>Detector {getDisplayScore(stock).toFixed(0)}</div>
                        <div>{getDisplaySummary(stock)}</div>
                        <div>{formatVolume(stock.sizeMetric)} vol</div>
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </main>

          <aside className="panel">
            <div className="panel-inner">
              <h3 className="panel-title">Ticker Detail</h3>
              <p className="panel-subtitle">Narrative, risk framing, score decomposition, and catalyst links.</p>

              {detailLoading ? <p className="premarket-loading">Loading selected ticker...</p> : null}
              {!selectedStock && !detailLoading ? <div className="premarket-empty">Select a name to inspect the setup.</div> : null}

              {selectedStock ? (
                <>
                  <div className="detail-card">
                    <div className="premarket-detail-top">
                      <div>
                        <div className="premarket-symbol">{selectedStock.ticker}</div>
                        <div style={{ marginTop: "6px", fontSize: "13px", color: "#94a3b8" }}>
                          {selectedStock.companyName || selectedStock.sector || "Premarket candidate"}
                        </div>
                      </div>
                      <div className="premarket-score" style={{ color: scoreColor(selectedDisplayScore) }}>
                        {selectedDisplayScore.toFixed(0)}
                      </div>
                    </div>

                    <div className="premarket-meta">
                      <span className="premarket-mini-chip">{selectedDisplaySummary}</span>
                      <span className="premarket-mini-chip">{formatPct(selectedStock.gapPercent)}</span>
                      <span className="premarket-mini-chip">{formatVolume(selectedStock.premarketVolume)} vol</span>
                      <span className="premarket-mini-chip">
                        Detector {selectedDisplayScore.toFixed(0)}
                      </span>
                    </div>

                    <div className="premarket-meta">
                      {(selectedStock.triggerFlags || []).slice(0, 3).map((flag) => (
                        <span key={`detail-${selectedStock.ticker}-${flag}`} className="premarket-mini-chip">
                          {formatTriggerFlag(flag)}
                        </span>
                      ))}
                    </div>

                    <div className="premarket-detail-copy">{selectedStock.aiSummary || detail?.aiAnalysis?.summary}</div>
                    <div className="premarket-detail-copy" style={{ color: "#94a3b8" }}>
                      Risk: {selectedStock.risk || detail?.aiAnalysis?.risk}
                    </div>

                    <div className="premarket-meta">
                      <span className="premarket-mini-chip">Liquidity {selectedStock.liquidityGrade || "-"}</span>
                      <span className="premarket-mini-chip">Entry {selectedStock.entryQuality || "-"}</span>
                      <span className="premarket-mini-chip">Cap {formatMoney(selectedStock.marketCap)}</span>
                    </div>
                  </div>

                  <div className="detail-card">
                    <h4 style={{ margin: 0, color: "#f8fafc" }}>Score Breakdown</h4>
                    <ScoreBreakdown breakdown={detail?.scoreBreakdown} />
                  </div>

                  <div className="detail-card">
                    <h4 style={{ margin: 0, color: "#f8fafc" }}>Catalyst Headlines</h4>
                    {Array.isArray(detail?.headlines) && detail.headlines.length > 0 ? (
                      <div className="premarket-headline-list">
                        {detail.headlines.map((item, index) => (
                          <div key={`${selectedStock.ticker}-headline-${index}`} className="premarket-headline-item">
                            <div className="premarket-headline-title">{item.title || item.summary || "Headline unavailable"}</div>
                            <div className="premarket-headline-meta">
                              {(item.publisher && (item.publisher.name || item.publisher)) || "News source"}
                              {item.published_utc ? ` | ${new Date(item.published_utc).toLocaleString()}` : ""}
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="premarket-empty" style={{ marginTop: "14px" }}>
                        No recent headlines were attached to this name.
                      </div>
                    )}
                  </div>

                  <div className="detail-card">
                    <h4 style={{ margin: 0, color: "#f8fafc" }}>Relationship Graph</h4>
                    <RelationshipGraph graph={detail?.relationships?.graph} />
                  </div>
                </>
              ) : null}
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
};

export default PremarketIntelligencePage;
