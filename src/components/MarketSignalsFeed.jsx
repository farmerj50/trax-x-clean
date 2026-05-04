/* eslint-disable react-hooks/exhaustive-deps */
import React, { useEffect, useMemo, useState } from "react";
import { io } from "socket.io-client";
import { SOCKET_BASE, apiFetch } from "../apiClient";

const AI_ALERT_SETTINGS_KEY = "aiAlertSettings";
const SCAN_REQUEST_TIMEOUT_MS = 60000;
const AI_PICKS_TIMEOUT_MS = 60000;

const formatNotional = (value) => {
  if (!Number.isFinite(value)) return "-";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);
};

const formatTime = (ts) => {
  if (!ts) return "-";
  return new Date(ts).toLocaleTimeString();
};

const tierColor = (tier) => {
  if (tier === "STRONG") return "#f97316";
  if (tier === "GOOD") return "#22c55e";
  return "#93c5fd";
};

const alertColor = (alert) => {
  if (alert === "LIVE") return "#f97316";
  if (alert === "NEAR") return "#22c55e";
  if (alert === "WATCH") return "#93c5fd";
  return "#9ca3af";
};

const metricColor = (value) => {
  if (value > 0) return "#22c55e";
  if (value < 0) return "#ef4444";
  return "#e5e7eb";
};

const scoreGlow = (score) => {
  if (score >= 90) return "0 0 0 1px rgba(34,197,94,0.35), 0 12px 30px rgba(34,197,94,0.12)";
  if (score >= 80) return "0 0 0 1px rgba(96,165,250,0.35), 0 12px 30px rgba(96,165,250,0.12)";
  if (score >= 70) return "0 0 0 1px rgba(250,204,21,0.2), 0 10px 24px rgba(250,204,21,0.08)";
  return "0 0 0 1px rgba(31,41,55,1)";
};

const MarketSignalsFeed = ({ selectedTicker, theme = "dark" }) => {
  const [signals, setSignals] = useState([]);
  const [onlySelectedTicker, setOnlySelectedTicker] = useState(false);
  const [lastLoadCount, setLastLoadCount] = useState(0);
  const [targets, setTargets] = useState([]);
  const [targetsFallbackMessage, setTargetsFallbackMessage] = useState("");
  const [targetsError, setTargetsError] = useState("");
  const [nearMisses, setNearMisses] = useState([]);
  const [failureSummary, setFailureSummary] = useState([]);
  const [loadingTargets, setLoadingTargets] = useState(false);
  const [preTargets, setPreTargets] = useState([]);
  const [preTargetsError, setPreTargetsError] = useState("");
  const [preFailureSummary, setPreFailureSummary] = useState([]);
  const [loadingPreTargets, setLoadingPreTargets] = useState(false);
  const [pennyTargets, setPennyTargets] = useState([]);
  const [pennyTargetsError, setPennyTargetsError] = useState("");
  const [pennyFailureSummary, setPennyFailureSummary] = useState([]);
  const [loadingPennyTargets, setLoadingPennyTargets] = useState(false);
  const [pennyNews, setPennyNews] = useState({});
  const [volatilityTargets, setVolatilityTargets] = useState([]);
  const [volatilityTargetsError, setVolatilityTargetsError] = useState("");
  const [loadingVolatilityTargets, setLoadingVolatilityTargets] = useState(false);
  const [aiPicks, setAiPicks] = useState([]);
  const [loadingAiPicks, setLoadingAiPicks] = useState(false);
  const [aiPicksError, setAiPicksError] = useState("");
  const [aiPicksGeneratedAt, setAiPicksGeneratedAt] = useState("");
  const [aiPicksDebug, setAiPicksDebug] = useState(null);
  const [aiAlertFilter, setAiAlertFilter] = useState("all");
  const [aiLiveMinScore, setAiLiveMinScore] = useState(85);
  const [aiNearMinScore, setAiNearMinScore] = useState(75);
  const [aiNearDistancePct, setAiNearDistancePct] = useState(1);
  const [activePreset, setActivePreset] = useState("normal");

  const [mode, setMode] = useState("breakout");
  const [minDayNotional, setMinDayNotional] = useState(800000000);
  const [minPrice, setMinPrice] = useState(10);
  const [minMovePct, setMinMovePct] = useState(2);
  const [maxMovePct, setMaxMovePct] = useState(3);
  const [minRvol, setMinRvol] = useState(2);
  const [minPrintNotional, setMinPrintNotional] = useState(10000000);
  const [minPrintCount, setMinPrintCount] = useState(2);
  const [requireVwap, setRequireVwap] = useState(true);
  const [qualifiedOnly, setQualifiedOnly] = useState(true);

  const loadRecent = async () => {
    try {
      const data = await apiFetch("/api/market-signals/recent?limit=100");
      if (Array.isArray(data?.signals)) {
        setSignals(data.signals.slice().reverse());
        setLastLoadCount(data.signals.length);
      } else {
        setLastLoadCount(0);
      }
    } catch (error) {
      setLastLoadCount(0);
    }
  };

  const loadQualifiedTargets = async () => {
    try {
      setLoadingTargets(true);
      setTargetsFallbackMessage("");
      setTargetsError("");
      const params = new URLSearchParams({
        mode,
        limit: "20",
        min_day_notional: String(minDayNotional),
        min_price: String(minPrice),
        min_move_pct: String(minMovePct),
        max_move_pct: String(maxMovePct),
        min_rvol: String(minRvol),
        min_print_notional: String(minPrintNotional),
        min_print_count: String(minPrintCount),
        require_vwap: String(requireVwap),
        qualified_only: String(qualifiedOnly),
      });
      const data = await apiFetch(`/api/market-signals/qualified-targets?${params}`, { timeoutMs: SCAN_REQUEST_TIMEOUT_MS });
      const loadedTargets = Array.isArray(data?.targets) ? data.targets : [];
      setTargets(loadedTargets);
      setFailureSummary(Array.isArray(data?.debug?.failure_counts) ? data.debug.failure_counts : []);

      // When strict filters return very few names, fetch full ranked list and show near misses.
      if (qualifiedOnly && loadedTargets.length <= 1) {
        const fallbackParams = new URLSearchParams(params);
        fallbackParams.set("qualified_only", "false");
        const fallbackData = await apiFetch(`/api/market-signals/qualified-targets?${fallbackParams}`, { timeoutMs: SCAN_REQUEST_TIMEOUT_MS });
        const misses = (Array.isArray(fallbackData?.targets) ? fallbackData.targets : [])
          .filter((item) => !item.qualified)
          .slice(0, 8);
        if (loadedTargets.length === 0 && misses.length > 0) {
          setTargets(misses);
          setTargetsFallbackMessage("No names fully qualified. Showing highest-ranked near misses instead.");
        }
        setNearMisses(misses);
      } else {
        setNearMisses([]);
      }
    } catch (error) {
      setTargets([]);
      setTargetsFallbackMessage("");
      setTargetsError(String(error?.message || "Qualified targets unavailable"));
      setFailureSummary([]);
      setNearMisses([]);
    } finally {
      setLoadingTargets(false);
    }
  };

  const loadPreBreakoutTargets = async () => {
    try {
      setLoadingPreTargets(true);
      setPreTargetsError("");
      const params = new URLSearchParams({
        mode: "pre_breakout",
        limit: "20",
        min_day_notional: String(minDayNotional),
        min_price: String(minPrice),
        // keep loose movement filters; pre-breakout engine handles scoring
        min_move_pct: "0",
        max_move_pct: "10",
        min_rvol: "0",
        min_print_notional: String(minPrintNotional),
        min_print_count: String(minPrintCount),
        require_vwap: String(requireVwap),
        qualified_only: "false", // show A/B/watch even if not fully qualified
      });
      const data = await apiFetch(`/api/market-signals/qualified-targets?${params}`, { timeoutMs: SCAN_REQUEST_TIMEOUT_MS });
      setPreTargets(Array.isArray(data?.targets) ? data.targets : []);
      setPreFailureSummary(Array.isArray(data?.debug?.failure_counts) ? data.debug.failure_counts : []);
    } catch (error) {
      setPreTargets([]);
      setPreTargetsError(String(error?.message || "Pre-breakout scan unavailable"));
      setPreFailureSummary([]);
    } finally {
      setLoadingPreTargets(false);
    }
  };

  const loadPennyTargets = async () => {
    try {
      setLoadingPennyTargets(true);
      setPennyTargetsError("");
      setPennyNews({});
      const params = new URLSearchParams({
        mode: "breakout",
        limit: "12",
        min_day_notional: "1000000",
        min_day_volume: "5000000",
        min_price: "0.5",
        max_price: "5",
        min_move_pct: "8",
        min_rvol: "2",
        require_vwap: "false",
        qualified_only: "false",
        pool_limit: "600",
      });
      const data = await apiFetch(`/api/market-signals/qualified-targets?${params}`, { timeoutMs: SCAN_REQUEST_TIMEOUT_MS });
      const loadedTargets = Array.isArray(data?.targets) ? data.targets.slice(0, 12) : [];
      setPennyTargets(loadedTargets);
      setPennyFailureSummary(Array.isArray(data?.debug?.failure_counts) ? data.debug.failure_counts : []);
      const symbols = loadedTargets.map((item) => item.symbol).filter(Boolean);
      if (symbols.length > 0) {
        const newsData = await apiFetch(`/api/ticker-news?ticker=${symbols.join(",")}`);
        setPennyNews(newsData && typeof newsData === "object" ? newsData : {});
      }
    } catch (error) {
      setPennyTargets([]);
      setPennyTargetsError(String(error?.message || "Penny movers unavailable"));
      setPennyFailureSummary([]);
      setPennyNews({});
    } finally {
      setLoadingPennyTargets(false);
    }
  };

  const loadVolatilityTargets = async () => {
    try {
      setLoadingVolatilityTargets(true);
      setVolatilityTargetsError("");
      const params = new URLSearchParams({
        universe_limit: "300",
        min_price: "0.5",
        max_price: "10",
        min_day_volume: "5000000",
        min_day_change_pct: "8",
        min_rvol: "2",
      });
      const data = await apiFetch(`/api/volatility-contraction-breakouts?${params}`, { timeoutMs: SCAN_REQUEST_TIMEOUT_MS });
      setVolatilityTargets(Array.isArray(data?.candidates) ? data.candidates.slice(0, 12) : []);
    } catch (error) {
      setVolatilityTargets([]);
      setVolatilityTargetsError(String(error?.message || "VCB scan unavailable"));
    } finally {
      setLoadingVolatilityTargets(false);
    }
  };

  const loadAiPicks = async () => {
    try {
      setLoadingAiPicks(true);
      setAiPicksError("");
      const params = new URLSearchParams({
        limit: "8",
        pool_limit: "120",
        min_day_notional: String(minDayNotional),
        min_price: String(minPrice),
        live_min_score: String(aiLiveMinScore),
        near_min_score: String(aiNearMinScore),
        near_distance_pct: String(aiNearDistancePct),
      });
      const data = await apiFetch(`/api/ai-picks?${params}`, { timeoutMs: AI_PICKS_TIMEOUT_MS });
      setAiPicks(Array.isArray(data?.picks) ? data.picks : []);
      setAiPicksGeneratedAt(String(data?.generated_at || ""));
      setAiPicksDebug(data?.debug && typeof data.debug === "object" ? data.debug : null);
    } catch (error) {
      setAiPicks([]);
      setAiPicksGeneratedAt("");
      setAiPicksDebug(null);
      const message = String(error?.message || "");
      setAiPicksError(
        message.includes("timed out")
          ? "AI picks are taking longer than usual to rank. Try again in a moment."
          : message || "AI picks unavailable"
      );
    } finally {
      setLoadingAiPicks(false);
    }
  };

  const applyPreset = (preset) => {
    setActivePreset(preset);
    if (preset === "easy") {
      setMode("breakout");
      setMinDayNotional(1000000000);
      setMinPrice(5);
      setMinMovePct(0.5);
      setMaxMovePct(4);
      setMinRvol(1);
      setRequireVwap(false);
      setQualifiedOnly(false);
      return;
    }
    if (preset === "normal") {
      setMode("breakout");
      setMinDayNotional(3000000000);
      setMinPrice(10);
      setMinMovePct(1);
      setMaxMovePct(3);
      setMinRvol(1.2);
      setRequireVwap(true);
      setQualifiedOnly(true);
      return;
    }
    if (preset === "strict") {
      setMode("breakout");
      setMinDayNotional(5000000000);
      setMinPrice(10);
      setMinMovePct(2);
      setMaxMovePct(3);
      setMinRvol(2);
      setRequireVwap(true);
      setQualifiedOnly(true);
      return;
    }
    if (preset === "early") {
      setMode("pre_breakout");
      setMinDayNotional(1000000000);
      setMinPrice(10);
      setMinMovePct(0.5);
      setMaxMovePct(3);
      setMinRvol(1.2);
      setRequireVwap(false);
      setQualifiedOnly(true);
      return;
    }
    if (preset === "penny") {
      setMode("breakout");
      setMinDayNotional(1000000);
      setMinPrice(0.5);
      setMinMovePct(8);
      setMaxMovePct(20);
      setMinRvol(2);
      setRequireVwap(false);
      setQualifiedOnly(false);
    }
  };

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(AI_ALERT_SETTINGS_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (Number.isFinite(Number(parsed.liveMinScore))) setAiLiveMinScore(Number(parsed.liveMinScore));
      if (Number.isFinite(Number(parsed.nearMinScore))) setAiNearMinScore(Number(parsed.nearMinScore));
      if (Number.isFinite(Number(parsed.nearDistancePct))) setAiNearDistancePct(Number(parsed.nearDistancePct));
      if (parsed.filter === "actionable" || parsed.filter === "all") setAiAlertFilter(parsed.filter);
    } catch (error) {
      // Ignore bad saved settings and fall back to defaults.
    }
  }, []);

  useEffect(() => {
    try {
      window.localStorage.setItem(
        AI_ALERT_SETTINGS_KEY,
        JSON.stringify({
          liveMinScore: aiLiveMinScore,
          nearMinScore: aiNearMinScore,
          nearDistancePct: aiNearDistancePct,
          filter: aiAlertFilter,
        })
      );
    } catch (error) {
      // Ignore storage failures; runtime state still works.
    }
  }, [aiLiveMinScore, aiNearMinScore, aiNearDistancePct, aiAlertFilter]);

  useEffect(() => {
    loadRecent();
    loadAiPicks();
    loadQualifiedTargets();
    const timers = [
      setTimeout(() => loadPreBreakoutTargets(), 1500),
      setTimeout(() => loadPennyTargets(), 3000),
      setTimeout(() => loadVolatilityTargets(), 4500),
    ];
    return () => timers.forEach((timer) => clearTimeout(timer));
  }, []);

  useEffect(() => {
    const interval = setInterval(() => {
      loadAiPicks();
    }, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, [minDayNotional, minPrice, aiLiveMinScore, aiNearMinScore, aiNearDistancePct]);

  useEffect(() => {
    const socket = io(SOCKET_BASE);
    const onSignal = (signal) => {
      setSignals((prev) => [signal, ...prev].slice(0, 100));
    };

    socket.on("market_signal", onSignal);
    return () => {
      socket.off("market_signal", onSignal);
      socket.close();
    };
  }, []);

  const filteredSignals = useMemo(() => {
    if (!onlySelectedTicker || !selectedTicker) return signals;
    const symbol = selectedTicker.toUpperCase();
    return signals.filter((item) => item.symbol === symbol);
  }, [signals, selectedTicker, onlySelectedTicker]);

  const visibleAiPicks = useMemo(() => {
    if (aiAlertFilter === "actionable") {
      return aiPicks.filter((item) => ["LIVE", "NEAR"].includes(String(item.alert?.label || "").toUpperCase()));
    }
    return aiPicks;
  }, [aiPicks, aiAlertFilter]);

  const isDark = theme === "dark";
  const themeColors = {
    pageBorder: isDark ? "#2d3748" : "#cfdced",
    border: isDark ? "#1f2937" : "#c9d7eb",
    strongBorder: isDark ? "#334155" : "#b7c9e0",
    pageBackground: isDark ? "#0b1120" : "#f8fbff",
    cardBackground: isDark
      ? "linear-gradient(180deg, rgba(15,23,42,0.82), rgba(10,15,24,0.88))"
      : "linear-gradient(180deg, rgba(255,255,255,0.96), rgba(238,244,255,0.96))",
    controlBackground: isDark
      ? "linear-gradient(180deg, rgba(17,24,39,0.92), rgba(10,15,24,0.92))"
      : "linear-gradient(180deg, rgba(255,255,255,0.96), rgba(241,245,249,0.96))",
    mutedPanel: isDark ? "rgba(15,23,42,0.9)" : "rgba(244,247,252,0.95)",
    inputBackground: isDark ? "#0f172a" : "#ffffff",
    buttonBackground: isDark ? "#111827" : "#f8fbff",
    heading: isDark ? "#f8fafc" : "#102038",
    text: isDark ? "#e5e7eb" : "#1f2937",
    mutedText: isDark ? "#94a3b8" : "#64748b",
    subtleText: isDark ? "#9ca3af" : "#64748b",
    chipText: isDark ? "#cbd5e1" : "#334155",
    actionBackground: isDark ? "#172554" : "#dbeafe",
    actionText: isDark ? "#dbeafe" : "#0f172a",
  };

  const fieldStyle = { display: "flex", flexDirection: "column", gap: "4px", fontSize: "11px", color: themeColors.subtleText };
  const inputStyle = {
    minHeight: "36px",
    padding: "0 10px",
    borderRadius: "8px",
    border: `1px solid ${themeColors.strongBorder}`,
    background: themeColors.inputBackground,
    color: themeColors.heading,
  };
  const baseButtonStyle = {
    minHeight: "38px",
    padding: "0 14px",
    borderRadius: "999px",
    border: `1px solid ${themeColors.strongBorder}`,
    background: themeColors.buttonBackground,
    color: themeColors.text,
    cursor: "pointer",
    fontWeight: 600,
    transition: "all 120ms ease",
  };
  const presetButtonStyle = (preset) => ({
    ...baseButtonStyle,
    background: activePreset === preset ? "linear-gradient(135deg, #0ea5e9, #2563eb)" : themeColors.buttonBackground,
    borderColor: activePreset === preset ? "#38bdf8" : themeColors.strongBorder,
    color: activePreset === preset ? "#eff6ff" : themeColors.text,
    boxShadow: activePreset === preset ? "0 8px 20px rgba(37,99,235,0.2)" : "none",
  });
  const actionButtonStyle = (disabled) => ({
    ...baseButtonStyle,
    background: disabled ? themeColors.buttonBackground : themeColors.actionBackground,
    borderColor: disabled ? themeColors.strongBorder : "#1d4ed8",
    color: disabled ? themeColors.mutedText : themeColors.actionText,
    cursor: disabled ? "default" : "pointer",
  });
  const mutedButtonStyle = {
    ...baseButtonStyle,
    background: themeColors.inputBackground,
  };
  const checkboxLabelStyle = { fontSize: "12px", color: themeColors.chipText, whiteSpace: "nowrap", paddingBottom: "8px" };
  const controlGroupStyle = {
    display: "flex",
    gap: "10px",
    flexWrap: "wrap",
    alignItems: "flex-end",
    padding: "12px",
    border: `1px solid ${themeColors.border}`,
    borderRadius: "10px",
    background: themeColors.controlBackground,
  };
  const sectionCardStyle = {
    marginTop: "16px",
    border: `1px solid ${themeColors.border}`,
    borderRadius: "12px",
    padding: "14px",
    background: themeColors.cardBackground,
  };
  const statusChipStyle = {
    fontSize: "12px",
    color: themeColors.chipText,
    padding: "6px 10px",
    borderRadius: "999px",
    border: `1px solid ${themeColors.border}`,
    background: themeColors.mutedPanel,
  };

  return (
    <div style={{ marginTop: "16px", border: `1px solid ${themeColors.pageBorder}`, borderRadius: "12px", padding: "12px", background: themeColors.pageBackground }}>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      <div style={{ ...sectionCardStyle, marginTop: 0 }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: "12px", flexWrap: "wrap", marginBottom: "12px" }}>
          <div>
            <div style={{ fontSize: "26px", fontWeight: 800, color: themeColors.heading, letterSpacing: "-0.02em" }}>AI Market Scanner</div>
            <div style={{ fontSize: "13px", color: themeColors.mutedText, marginTop: "4px" }}>Professional trade intelligence across breakout, AI-ranked, and small-cap momentum setups.</div>
          </div>
          <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
            <span style={statusChipStyle}>Mode: {mode}</span>
            <span style={statusChipStyle}>Min Notional: {formatNotional(minDayNotional)}</span>
            <span style={statusChipStyle}>Min Price: {Number(minPrice || 0).toFixed(2)}</span>
          </div>
        </div>

        <div style={{ display: "grid", gap: "12px" }}>
          <div style={controlGroupStyle}>
            <div style={{ minWidth: "120px" }}>
              <div style={{ fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.08em", color: "#38bdf8" }}>Strategy Presets</div>
              <div style={{ fontSize: "12px", color: "#94a3b8", marginTop: "4px" }}>Fast scanner modes</div>
            </div>
            <button style={presetButtonStyle("easy")} onClick={() => applyPreset("easy")} title="Easy debug preset">Easy</button>
            <button style={presetButtonStyle("normal")} onClick={() => applyPreset("normal")} title="Balanced preset">Normal</button>
            <button style={presetButtonStyle("strict")} onClick={() => applyPreset("strict")} title="Strict preset">Strict</button>
            <button style={presetButtonStyle("early")} onClick={() => applyPreset("early")} title="Catch pre-move setups">Early</button>
            <button style={presetButtonStyle("penny")} onClick={() => applyPreset("penny")} title="Penny-stock breakout preset">Penny</button>
          </div>

          <div style={controlGroupStyle}>
            <div style={{ minWidth: "120px" }}>
              <div style={{ fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.08em", color: "#38bdf8" }}>Scanner Filters</div>
              <div style={{ fontSize: "12px", color: "#94a3b8", marginTop: "4px" }}>Liquidity, move, and quality gates</div>
            </div>
            <div style={fieldStyle}>
              <span>Mode</span>
              <select value={mode} onChange={(e) => setMode(e.target.value)} style={{ ...inputStyle, minWidth: "110px" }}>
                <option value="breakout">Breakout</option>
                <option value="reversal">Reversal</option>
                <option value="big_prints">Big Prints</option>
                <option value="pre_breakout">Pre-Breakout</option>
              </select>
            </div>
            <div style={fieldStyle}>
              <span>Day Notional</span>
              <input type="number" value={minDayNotional} onChange={(e) => setMinDayNotional(Number(e.target.value) || 0)} style={{ ...inputStyle, width: "130px" }} title="Min Day Notional" />
            </div>
            <div style={fieldStyle}>
              <span>RVOL</span>
              <input type="number" value={minRvol} onChange={(e) => setMinRvol(Number(e.target.value) || 0)} style={{ ...inputStyle, width: "70px" }} title="Min RVOL" />
            </div>
            <div style={fieldStyle}>
              <span>% Change</span>
              <input type="number" value={minMovePct} onChange={(e) => setMinMovePct(Number(e.target.value) || 0)} style={{ ...inputStyle, width: "70px" }} title="Min % Move" />
            </div>
            {mode === "pre_breakout" && (
              <div style={fieldStyle}>
                <span>Max % Change</span>
                <input type="number" value={maxMovePct} onChange={(e) => setMaxMovePct(Number(e.target.value) || 0)} style={{ ...inputStyle, width: "70px" }} title="Max % Move" />
              </div>
            )}
            <div style={fieldStyle}>
              <span>Price</span>
              <input type="number" value={minPrice} onChange={(e) => setMinPrice(Number(e.target.value) || 0)} style={{ ...inputStyle, width: "70px" }} title="Min Price" />
            </div>
            {mode === "big_prints" && (
              <>
                <div style={fieldStyle}>
                  <span>Print Notional</span>
                  <input type="number" value={minPrintNotional} onChange={(e) => setMinPrintNotional(Number(e.target.value) || 0)} style={{ ...inputStyle, width: "120px" }} title="Min Print Notional" />
                </div>
                <div style={fieldStyle}>
                  <span>Print Count</span>
                  <input type="number" value={minPrintCount} onChange={(e) => setMinPrintCount(Number(e.target.value) || 0)} style={{ ...inputStyle, width: "80px" }} title="Min Prints in Window" />
                </div>
              </>
            )}
            <label style={checkboxLabelStyle}>
              <input type="checkbox" checked={requireVwap} onChange={(e) => setRequireVwap(e.target.checked)} style={{ marginRight: "6px" }} />
              VWAP
            </label>
            <label style={checkboxLabelStyle}>
              <input type="checkbox" checked={qualifiedOnly} onChange={(e) => setQualifiedOnly(e.target.checked)} style={{ marginRight: "6px" }} />
              Qualified only
            </label>
          </div>

          <div style={controlGroupStyle}>
            <div style={{ minWidth: "120px" }}>
              <div style={{ fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.08em", color: "#38bdf8" }}>System Actions</div>
              <div style={{ fontSize: "12px", color: "#94a3b8", marginTop: "4px" }}>Run scanners and ranked views</div>
            </div>
            <button
              style={actionButtonStyle(loadingTargets || loadingAiPicks)}
              onClick={() => {
                loadQualifiedTargets();
                loadAiPicks();
              }}
              disabled={loadingTargets || loadingAiPicks}
            >
              {loadingTargets || loadingAiPicks ? "Scanning market..." : "Apply Scanner"}
            </button>
            <button style={actionButtonStyle(loadingAiPicks)} onClick={loadAiPicks} disabled={loadingAiPicks} title="Refresh ranked AI picks">
              {loadingAiPicks ? "Ranking AI..." : "Load AI Picks"}
            </button>
            <button style={actionButtonStyle(loadingPreTargets)} onClick={loadPreBreakoutTargets} disabled={loadingPreTargets} title="Refresh pre-breakout pressure list">
              {loadingPreTargets ? "Scanning pre-market..." : "Load Pre-Breakout"}
            </button>
            <button style={actionButtonStyle(loadingPennyTargets)} onClick={loadPennyTargets} disabled={loadingPennyTargets} title="Refresh penny-stock movers">
              {loadingPennyTargets ? "Scanning penny..." : "Load Penny Movers"}
            </button>
            <button style={actionButtonStyle(loadingVolatilityTargets)} onClick={loadVolatilityTargets} disabled={loadingVolatilityTargets} title="Refresh spike-tight-breakout scanner">
              {loadingVolatilityTargets ? "Scanning VCB..." : "Load VCB"}
            </button>
          </div>
        </div>
      </div>

      <div style={sectionCardStyle}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "12px", marginBottom: "12px" }}>
          <div>
            <h3 style={{ margin: 0, fontSize: "22px" }}>Qualified Targets</h3>
            <div style={{ fontSize: "13px", color: "#94a3b8", marginTop: "4px" }}>Confirmed scanner results using your current liquidity and breakout filters.</div>
          </div>
          {failureSummary.length > 0 && (
            <div style={{ fontSize: "12px", color: "#94a3b8", maxWidth: "540px" }}>
              Top failures: {failureSummary.map((f) => `${f.rule} (${f.count})`).join(" | ")}
            </div>
          )}
        </div>

        {loadingTargets && (
          <div style={{ margin: "0 0 12px 0", color: "#9ca3af", fontSize: "12px", display: "flex", alignItems: "center", gap: "8px" }}>
            <span
              style={{
                width: "12px",
                height: "12px",
                border: "2px solid #374151",
                borderTop: "2px solid #60a5fa",
                borderRadius: "50%",
                display: "inline-block",
                animation: "spin 1s linear infinite",
              }}
            />
            Scanning qualified targets...
          </div>
        )}

        {targetsFallbackMessage && (
          <div style={{ margin: "0 0 10px 0", color: "#fcd34d", fontSize: "12px" }}>
            {targetsFallbackMessage}
          </div>
        )}
        {targets.length === 0 ? (
          <div style={{ color: "#9ca3af", border: "1px dashed #334155", borderRadius: "10px", padding: "14px" }}>
            <p style={{ margin: 0 }}>{targetsError || "No targets matched current filters."}</p>
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(220px, 1fr))", gap: "16px" }}>
            {targets.map((item) => (
              <div key={`${item.mode}-${item.symbol}`} style={{ fontSize: "12px", border: "1px solid #1f2937", borderRadius: "12px", padding: "16px", background: "rgba(15,23,42,0.76)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "8px", marginBottom: "10px" }}>
                  <div>
                    <div style={{ fontSize: "22px", fontWeight: 800, lineHeight: 1 }}>{item.symbol}</div>
                    <div style={{ color: "#94a3b8", marginTop: "4px" }}>Score {item.score}</div>
                  </div>
                  <div style={{ color: "#fcd34d", fontWeight: 700 }}>{item.phase || "Mixed"}</div>
                </div>

                <div style={{ marginBottom: "10px", padding: "10px", borderRadius: "10px", background: "rgba(15,23,42,0.92)", border: "1px solid #273449" }}>
                  <div style={{ color: "#fcd34d", fontWeight: 700 }}>Trade Context</div>
                  <div style={{ marginTop: "6px", color: "#f8fafc" }}>{item.tooLate ? "Too Late: Yes" : "Too Late: No"} | {item.idealEntryType || "No clean entry"}</div>
                  <div style={{ color: "#cbd5e1" }}>{item.overallBias || "Neutral/Chop"}</div>
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "6px", marginBottom: "10px" }}>
                  <div>{formatNotional(item.day_notional)}</div>
                  <div style={{ color: metricColor(Number(item.pct_change || 0)) }}>Move: {Number(item.pct_change || 0).toFixed(2)}%</div>
                  <div>Price: {Number(item.price || 0).toFixed(2)}</div>
                  <div>RVOL: {Number(item.rvol || 0).toFixed(2)}</div>
                </div>

                {item.engines && (
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "6px", marginBottom: "10px" }}>
                    <div style={{ color: "#86efac" }}>Pre: {Number(item.engines.pre?.score || 0).toFixed(0)}</div>
                    <div style={{ color: "#93c5fd" }}>Cont: {Number(item.engines.continuation?.score || 0).toFixed(0)}</div>
                    <div style={{ color: "#fca5a5" }}>Squeeze: {Number(item.engines.squeeze?.score || 0).toFixed(0)}</div>
                    <div style={{ color: "#f59e0b" }}>Exhaust: {Number(item.engines.exhaustion?.score || 0).toFixed(0)}</div>
                  </div>
                )}

                <div style={{ color: "#9ca3af" }}>{(item.reasons || []).slice(0, 2).join(" | ")}</div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div style={sectionCardStyle}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "12px", marginBottom: "12px" }}>
          <div>
            <h3 style={{ margin: 0, fontSize: "22px" }}>AI Top Picks</h3>
            <div style={{ fontSize: "13px", color: "#94a3b8", marginTop: "4px" }}>Top trading opportunities ranked by AI scoring.</div>
          </div>
          <div style={{ display: "flex", alignItems: "flex-end", gap: "10px", flexWrap: "wrap" }}>
            <div style={fieldStyle}>
              <span>LIVE Score</span>
              <input type="number" value={aiLiveMinScore} onChange={(e) => setAiLiveMinScore(Number(e.target.value) || 0)} style={{ ...inputStyle, width: "80px" }} title="Min score for LIVE alerts" />
            </div>
            <div style={fieldStyle}>
              <span>NEAR Score</span>
              <input type="number" value={aiNearMinScore} onChange={(e) => setAiNearMinScore(Number(e.target.value) || 0)} style={{ ...inputStyle, width: "80px" }} title="Min score for NEAR alerts" />
            </div>
            <div style={fieldStyle}>
              <span>NEAR %</span>
              <input type="number" step="0.1" value={aiNearDistancePct} onChange={(e) => setAiNearDistancePct(Number(e.target.value) || 0)} style={{ ...inputStyle, width: "70px" }} title="Max distance to trigger for NEAR alerts" />
            </div>
            <label style={checkboxLabelStyle}>
              <input type="checkbox" checked={aiAlertFilter === "actionable"} onChange={(e) => setAiAlertFilter(e.target.checked ? "actionable" : "all")} style={{ marginRight: "6px" }} />
              Only LIVE + NEAR
            </label>
            <button
              type="button"
              style={mutedButtonStyle}
              onClick={() => {
                setAiLiveMinScore(85);
                setAiNearMinScore(75);
                setAiNearDistancePct(1);
                setAiAlertFilter("all");
              }}
            >
              Reset AI Alerts
            </button>
          </div>
        </div>

        <div style={{ display: "flex", gap: "8px", flexWrap: "wrap", marginBottom: "10px" }}>
          <span style={statusChipStyle}>{aiPicksGeneratedAt ? `Last Scan: ${formatTime(aiPicksGeneratedAt)}` : "Auto-refresh: 5m"}</span>
          <span style={statusChipStyle}>Universe: {(aiPicksDebug?.universe_count || 0).toLocaleString()}</span>
          <span style={statusChipStyle}>Candidates: {(aiPicksDebug?.candidate_count || 0).toLocaleString()}</span>
          <span style={statusChipStyle}>Ranked: {(aiPicksDebug?.scored_count || 0).toLocaleString()}</span>
        </div>

        {loadingAiPicks && <p style={{ margin: "0 0 10px 0", color: "#9ca3af", fontSize: "12px" }}>Scanning market and ranking AI picks...</p>}
        {visibleAiPicks.length === 0 ? (
          <div style={{ margin: "0 0 4px 0", color: "#9ca3af" }}>
            <p style={{ margin: 0 }}>
              {aiPicksError || (aiAlertFilter === "actionable" ? "No LIVE or NEAR AI picks right now." : "No AI picks available right now.")}
            </p>
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(220px, 1fr))", gap: "16px", marginBottom: "4px" }}>
            {visibleAiPicks.map((item) => (
              <div
                key={`ai-${item.symbol}`}
                style={{
                  fontSize: "12px",
                  border: "1px solid #1f2937",
                  borderRadius: "12px",
                  padding: "16px",
                  background: "rgba(15,23,42,0.78)",
                  boxShadow: scoreGlow(Number(item.score || 0)),
                  transition: "transform 120ms ease, box-shadow 120ms ease",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "10px", marginBottom: "10px" }}>
                  <div>
                    <div style={{ fontSize: "22px", fontWeight: 800, lineHeight: 1 }}>{item.symbol}</div>
                    <div style={{ color: "#94a3b8", marginTop: "4px" }}>Score {Number(item.score || 0).toFixed(0)}</div>
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: "4px" }}>
                    <span style={{ color: tierColor(item.tier), fontWeight: 700 }}>{item.tier || "WATCH"}</span>
                    <span style={{ color: alertColor(item.alert?.label), fontWeight: 700 }}>{item.alert?.label || "WATCH"}</span>
                  </div>
                </div>

                <div style={{ marginBottom: "10px", padding: "10px", borderRadius: "10px", background: "rgba(15,23,42,0.92)", border: "1px solid #273449" }}>
                  <div style={{ color: "#fcd34d", fontWeight: 700 }}>Trade Setup</div>
                  <div style={{ marginTop: "6px", color: "#f8fafc" }}>Trigger {Number(item.plan?.trigger || 0).toFixed(2)} | Entry {Number(item.plan?.entry || 0).toFixed(2)}</div>
                  <div style={{ color: "#cbd5e1" }}>Stop {Number(item.plan?.stop || 0).toFixed(2)} | Target {Number(item.plan?.target1 || 0).toFixed(2)}</div>
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "6px", marginBottom: "10px" }}>
                  <div>Price: {Number(item.price || 0).toFixed(2)}</div>
                  <div style={{ color: metricColor(Number(item.pct_change || 0)) }}>Move: {Number(item.pct_change || 0).toFixed(2)}%</div>
                  <div>RVOL: {Number(item.rvol || 0).toFixed(2)}</div>
                  <div>{formatNotional(item.day_notional)}</div>
                  <div>Near 20d: {Number(item.dist_to_high_20_pct || 0).toFixed(1)}%</div>
                  <div>Trigger dist: {Number(item.alert?.distance_to_trigger_pct || 0).toFixed(2)}%</div>
                </div>

                <div style={{ color: "#93c5fd" }}>{Array.isArray(item.reasons) ? item.reasons.join(" | ") : ""}</div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div style={sectionCardStyle}>
      <div style={{ margin: "0 0 4px 0", display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "8px" }}>
        <h3 style={{ margin: 0 }}>Penny Movers</h3>
        <div style={{ fontSize: "12px", color: "#9ca3af" }}>
          Small-cap momentum setups
        </div>
      </div>
      <div style={{ margin: "0 0 8px 0", color: "#9ca3af", fontSize: "12px" }}>
        Price 0.50-5 | Day volume 5M+ | RVOL 2+ | % change 8%+ | Best trading windows are typically 9:35-10:30 AM and 3:30-4:00 PM.
      </div>
      {loadingPennyTargets && <p style={{ margin: "0 0 6px 0", color: "#9ca3af", fontSize: "12px" }}>Scanning penny movers...</p>}
      {pennyTargets.length === 0 ? (
        <div style={{ margin: "0 0 8px 0", color: "#9ca3af" }}>
          <p style={{ margin: "0 0 4px 0" }}>{pennyTargetsError || "No penny movers matched current market data."}</p>
          {pennyFailureSummary.length > 0 && (
            <p style={{ margin: 0, fontSize: "12px" }}>
              Top failures: {pennyFailureSummary.map((f) => `${f.rule} (${f.count})`).join(" | ")}
            </p>
          )}
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(180px, 1fr))", gap: "12px", marginBottom: "4px" }}>
          {pennyTargets.map((item) => (
            <div key={`penny-${item.symbol}`} style={{ fontSize: "12px", border: "1px solid #1f2937", borderRadius: "10px", padding: "12px", background: "rgba(15,23,42,0.72)" }}>
              <div style={{ fontWeight: "bold" }}>
                {item.symbol} ({item.score})
              </div>
              <div>Price: {Number(item.price || 0).toFixed(2)}</div>
              <div>{formatNotional(item.day_notional)}</div>
              <div>Vol: {Number(item.day_volume || 0).toLocaleString()}</div>
              <div style={{ color: metricColor(Number(item.pct_change || 0)) }}>Move: {Number(item.pct_change || 0).toFixed(2)}%</div>
              <div>RVOL: {Number(item.rvol || 0).toFixed(2)}</div>
              <div>News: {Array.isArray(pennyNews[item.symbol]) && pennyNews[item.symbol].length > 0 ? "Recent catalyst" : "No recent news"}</div>
              <div style={{ color: "#9ca3af" }}>{(item.reasons || []).slice(0, 3).join(" | ")}</div>
            </div>
          ))}
        </div>
      )}
      </div>

      <div style={sectionCardStyle}>
        <div style={{ margin: "0 0 4px 0", display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "8px" }}>
          <h3 style={{ margin: 0 }}>Volatility Contraction Breakouts</h3>
          <div style={{ fontSize: "12px", color: "#9ca3af" }}>
            {"Spike -> tight coil -> higher lows -> breakout trigger"}
          </div>
        </div>
        <div style={{ margin: "0 0 8px 0", color: "#9ca3af", fontSize: "12px" }}>
          Tuned for small caps: price 0.50-10, day volume 5M+, RVOL 2+, daily change 8%+.
        </div>
        {loadingVolatilityTargets && <p style={{ margin: "0 0 6px 0", color: "#9ca3af", fontSize: "12px" }}>Scanning volatility contractions...</p>}
        {volatilityTargets.length === 0 ? (
          <div style={{ margin: "0 0 8px 0", color: "#9ca3af" }}>
            <p style={{ margin: "0 0 4px 0" }}>{volatilityTargetsError || "No volatility contraction setups right now."}</p>
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(180px, 1fr))", gap: "12px" }}>
            {volatilityTargets.map((item) => (
              <div key={`vcb-${item.ticker}`} style={{ fontSize: "12px", border: "1px solid #1f2937", borderRadius: "10px", padding: "12px", background: "rgba(15,23,42,0.72)" }}>
                <div style={{ fontWeight: "bold" }}>
                  {item.ticker} ({Number(item.pattern_score || 0).toFixed(0)})
                </div>
                <div>Price: {Number(item.close || 0).toFixed(2)}</div>
                <div>Vol: {Number(item.volume || 0).toLocaleString()}</div>
                <div style={{ color: metricColor(Number(item.pct_change || 0)) }}>Move: {Number(item.pct_change || 0).toFixed(2)}%</div>
                <div>RVOL: {Number(item.rvol || 0).toFixed(2)}</div>
                <div>{item.breakout_now ? "Status: Breaking out" : "Status: In consolidation"}</div>
                <div>Trigger: {item.breakout_trigger ? Number(item.breakout_trigger).toFixed(3) : "n/a"}</div>
                <div style={{ color: "#9ca3af" }}>{Array.isArray(item.notes) ? item.notes.join(" | ") : ""}</div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div style={sectionCardStyle}>
        <div style={{ margin: "0 0 4px 0", display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "8px" }}>
          <h3 style={{ margin: 0 }}>Pre-Breakout Pressure</h3>
          <div style={{ fontSize: "12px", color: "#9ca3af" }}>
            Auto-fetched with same liquidity settings; shows A/B/watch lists even when qualified-only is on.
          </div>
        </div>
        {loadingPreTargets && <p style={{ margin: "0 0 6px 0", color: "#9ca3af", fontSize: "12px" }}>Scanning pre-breakout setups...</p>}
        {preTargets.length === 0 ? (
          <div style={{ margin: "0 0 8px 0", color: "#9ca3af" }}>
            <p style={{ margin: "0 0 4px 0" }}>{preTargetsError || "No pre-breakout setups yet."}</p>
            {preFailureSummary.length > 0 && (
              <p style={{ margin: 0, fontSize: "12px" }}>
                Top failures: {preFailureSummary.map((f) => `${f.rule} (${f.count})`).join(" | ")}
              </p>
            )}
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(180px, 1fr))", gap: "12px" }}>
            {preTargets.map((item) => (
              <div key={`pre-${item.symbol}`} style={{ fontSize: "12px", border: "1px solid #1f2937", borderRadius: "10px", padding: "12px", background: "rgba(15,23,42,0.72)" }}>
                <div style={{ fontWeight: "bold" }}>
                  {item.symbol} ({Number(item.engines?.pre?.score || 0).toFixed(0)}) {item.engines?.pre?.state || ""}
                </div>
                <div>{formatNotional(item.day_notional)}</div>
                <div>Price: {Number(item.price || 0).toFixed(2)}</div>
                <div>Dist to 20d high: {item.range_high_20 ? `${((item.range_high_20 - item.price) / item.range_high_20 * 100).toFixed(1)}%` : "n/a"}</div>
                <div>RVOL: {Number(item.rvol || 0).toFixed(2)} | Rvol5: {Number(item.rvol5 || 0).toFixed(2)}</div>
                <div style={{ color: "#9ca3af" }}>{(item.engines?.pre?.reasons || []).slice(0, 3).join(" | ")}</div>
              </div>
            ))}
          </div>
        )}
      </div>

      {nearMisses.length > 0 && (
        <div style={sectionCardStyle}>
          <p style={{ margin: "0 0 6px 0", color: "#9ca3af", fontSize: "12px" }}>
            Near misses (high score but failed one or more rules):
          </p>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(180px, 1fr))", gap: "12px" }}>
            {nearMisses.map((item) => (
              <div key={`miss-${item.symbol}-${item.score}`} style={{ fontSize: "12px", border: "1px solid #1f2937", borderRadius: "10px", padding: "12px", background: "rgba(15,23,42,0.72)" }}>
                <div style={{ fontWeight: "bold" }}>
                  {item.symbol} ({item.score})
                </div>
                <div>{formatNotional(item.day_notional)}</div>
                <div style={{ color: metricColor(Number(item.pct_change || 0)) }}>Move: {Number(item.pct_change || 0).toFixed(2)}%</div>
                <div>RVOL: {Number(item.rvol || 0).toFixed(2)}</div>
                <div style={{ color: "#fca5a5" }}>
                  Fail: {(item.failed_rules || []).slice(0, 2).join(" | ") || "none"}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div style={sectionCardStyle}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "12px", marginBottom: "8px", flexWrap: "wrap" }}>
          <h3 style={{ margin: 0 }}>Market Signals</h3>
          <div style={{ display: "flex", alignItems: "center", gap: "12px", flexWrap: "wrap" }}>
            <button onClick={loadRecent} style={{ ...mutedButtonStyle, minHeight: "30px", padding: "0 12px" }}>
              Refresh
            </button>
            <label style={{ fontSize: "12px", color: "#9ca3af", whiteSpace: "nowrap" }}>Loaded: {lastLoadCount}</label>
            <label style={{ fontSize: "12px", color: "#9ca3af", whiteSpace: "nowrap" }}>
              <input
                type="checkbox"
                checked={onlySelectedTicker}
                onChange={(e) => setOnlySelectedTicker(e.target.checked)}
                style={{ marginRight: "6px" }}
              />
              Only {selectedTicker || "selected"}
            </label>
          </div>
        </div>
        {filteredSignals.length === 0 ? (
          <p style={{ margin: 0, color: "#9ca3af" }}>No qualifying signals yet.</p>
        ) : (
          <div style={{ maxHeight: "200px", overflowY: "auto" }}>
            {filteredSignals.map((signal, index) => (
              <div
                key={`${signal.symbol}-${signal.ts}-${index}`}
                style={{
                  display: "grid",
                  gridTemplateColumns: "70px 120px 80px 130px 80px 100px",
                  gap: "8px",
                  padding: "6px 0",
                  borderBottom: "1px solid #1f2937",
                  fontSize: "13px",
                }}
              >
                <span>{signal.symbol}</span>
                <span>{signal.type}</span>
                <span>{signal.side}</span>
                <span>{formatNotional(signal.notional)}</span>
                <span>{signal.size}</span>
                <span>{formatTime(signal.ts)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default MarketSignalsFeed;
