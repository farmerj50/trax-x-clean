import React, { useEffect, useMemo, useState } from "react";
import { apiFetch } from "../apiClient";
import "./ShortSalesPage.css";

const fallbackNames = ["GME", "AMC", "CVNA", "BYND", "TSLA"];

const fmtPct = (value) => {
  const num = Number(value);
  return Number.isFinite(num) ? `${num.toFixed(2)}%` : "-";
};

const ShortSalesPage = () => {
  const [tickers, setTickers] = useState(fallbackNames.join(","));
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [lastUpdated, setLastUpdated] = useState("");

  const fetchShorts = async () => {
    try {
      setLoading(true);
      setError("");
      const query = tickers
        .split(",")
        .map((t) => t.trim().toUpperCase())
        .filter(Boolean)
        .join(",");
      const res = await apiFetch(`/api/short-ideas?tickers=${encodeURIComponent(query)}`);
      if (!res.ok) throw new Error("Backend short-ideas endpoint not available.");
      const json = await res.json();
      if (json?.candidates?.length) {
        setData(json.candidates);
        setError("");
      } else {
        setData([]);
        setError(json?.error || "No short interest data returned.");
      }
    } catch (err) {
      console.warn("Short interest fetch failed; using fallback.", err);
      setError("Using fallback list; backend not available.");
      setData(
        fallbackNames.map((t) => ({
          ticker: t,
          short_float: (Math.random() * 30 + 10).toFixed(2),
          days_to_cover: (Math.random() * 5 + 1).toFixed(2),
          borrow_fee: (Math.random() * 50).toFixed(2),
        }))
      );
    } finally {
      setLoading(false);
      setLastUpdated(new Date().toLocaleTimeString());
    }
  };

  useEffect(() => {
    fetchShorts();
  }, []);

  const summary = useMemo(() => {
    const entries = Array.isArray(data) ? data : [];
    const highestShortFloat = [...entries].sort(
      (a, b) => Number(b.short_float || 0) - Number(a.short_float || 0)
    )[0];
    const highestBorrow = [...entries].sort(
      (a, b) => Number(b.borrow_fee || 0) - Number(a.borrow_fee || 0)
    )[0];
    const avgDaysToCover =
      entries.length > 0
        ? entries.reduce((sum, row) => sum + Number(row.days_to_cover || 0), 0) / entries.length
        : 0;
    return { highestShortFloat, highestBorrow, avgDaysToCover };
  }, [data]);

  return (
    <div className="short-sales-page">
      <div className="short-sales-page__shell">
        <div className="short-sales-page__hero">
          <div>
            <div className="short-sales-page__kicker">Bearish Pressure Monitor</div>
            <h2 className="short-sales-page__title">Short Sales Monitor</h2>
            <p className="short-sales-page__subtitle">
              Track short float, days-to-cover, and borrow fees in the same dashboard language as
              the rest of the platform.
            </p>
          </div>
          <div className="short-sales-page__hero-actions">
            <div className="short-sales-page__badges">
              <span className="short-sales-status-pill">
                Feed: <strong>{error ? "Fallback" : loading ? "Refreshing" : "Live"}</strong>
              </span>
              {lastUpdated && (
                <span className="short-sales-status-pill">
                  Updated: <strong>{lastUpdated}</strong>
                </span>
              )}
            </div>
          </div>
        </div>

        <div className="short-sales-controls-card">
          <div className="short-sales-controls-card__header">
            <div>
              <h3>Scanner Controls</h3>
              <p>Enter comma-separated tickers and refresh the short-interest board.</p>
            </div>
          </div>
          <div className="short-sales-controls-grid">
            <label className="short-sales-field">
              <span className="short-sales-field__label">Tickers</span>
              <input
                className="short-sales-input"
                value={tickers}
                onChange={(e) => setTickers(e.target.value)}
                placeholder="e.g., GME, AMC, TSLA"
              />
            </label>
            <button className="short-sales-btn" onClick={fetchShorts} disabled={loading}>
              {loading ? "Loading..." : "Refresh"}
            </button>
          </div>
          {error && <div className="short-sales-alert">{error}</div>}
        </div>

        <div className="short-sales-summary-grid">
          <div className="short-sales-summary-card">
            <span className="short-sales-summary-card__label">Tracked Names</span>
            <strong>{data.length}</strong>
          </div>
          <div className="short-sales-summary-card">
            <span className="short-sales-summary-card__label">Highest Short Float</span>
            <strong>{summary.highestShortFloat ? summary.highestShortFloat.ticker : "-"}</strong>
          </div>
          <div className="short-sales-summary-card">
            <span className="short-sales-summary-card__label">Highest Borrow Fee</span>
            <strong>{summary.highestBorrow ? summary.highestBorrow.ticker : "-"}</strong>
          </div>
          <div className="short-sales-summary-card">
            <span className="short-sales-summary-card__label">Avg Days To Cover</span>
            <strong>{summary.avgDaysToCover ? summary.avgDaysToCover.toFixed(2) : "-"}</strong>
          </div>
        </div>

        <div className="short-sales-page__grid">
          <section className="short-sales-panel short-sales-panel--board">
            <div className="short-sales-panel__header">
              <div>
                <h3>Short Interest Board</h3>
                <p>Names ranked by pressure indicators and fallback-safe short data.</p>
              </div>
            </div>
            {data.length === 0 && !loading ? (
              <div className="short-sales-empty-state">No short-sale data available.</div>
            ) : (
              <div className="short-sales-board">
                {data.map((row) => (
                  <article key={row.ticker} className="short-sales-card">
                    <div className="short-sales-card__top">
                      <div>
                        <h4>{row.ticker}</h4>
                        <span>Borrow stress snapshot</span>
                      </div>
                      <div className="short-sales-card__pill">{fmtPct(row.short_float)}</div>
                    </div>

                    <div className="short-sales-card__metrics">
                      <div>
                        <span>Short Float</span>
                        <strong>{fmtPct(row.short_float)}</strong>
                      </div>
                      <div>
                        <span>Days To Cover</span>
                        <strong>{row.days_to_cover || "-"}</strong>
                      </div>
                      <div>
                        <span>Borrow Fee</span>
                        <strong>{fmtPct(row.borrow_fee)}</strong>
                      </div>
                    </div>

                    {row.entry_point && (
                      <div className="short-sales-card__plan">
                        <div>
                          <span>Entry</span>
                          <strong>${row.entry_point}</strong>
                        </div>
                        <div>
                          <span>Stop</span>
                          <strong>${row.stop_loss || "-"}</strong>
                        </div>
                        <div>
                          <span>Target</span>
                          <strong>${row.target_price || "-"}</strong>
                        </div>
                      </div>
                    )}
                  </article>
                ))}
              </div>
            )}
          </section>

          <aside className="short-sales-page__side">
            <section className="short-sales-panel">
              <div className="short-sales-panel__header">
                <div>
                  <h3>Highest Short Float</h3>
                  <p>Name with the most elevated short exposure in the current set.</p>
                </div>
              </div>
              <div className="short-sales-side-card">
                <strong>{summary.highestShortFloat ? summary.highestShortFloat.ticker : "-"}</strong>
                <p>
                  {summary.highestShortFloat
                    ? `${fmtPct(summary.highestShortFloat.short_float)} short float with ${
                        summary.highestShortFloat.days_to_cover || "-"
                      } days to cover.`
                    : "No current leader."}
                </p>
              </div>
            </section>

            <section className="short-sales-panel">
              <div className="short-sales-panel__header">
                <div>
                  <h3>Borrow Stress</h3>
                  <p>Name charging the highest borrow fee in the current list.</p>
                </div>
              </div>
              <div className="short-sales-side-card">
                <strong>{summary.highestBorrow ? summary.highestBorrow.ticker : "-"}</strong>
                <p>
                  {summary.highestBorrow
                    ? `${fmtPct(summary.highestBorrow.borrow_fee)} borrow fee with ${fmtPct(
                        summary.highestBorrow.short_float
                      )} short float.`
                    : "No borrow leader."}
                </p>
              </div>
            </section>

            <section className="short-sales-panel">
              <div className="short-sales-panel__header">
                <div>
                  <h3>Page Notes</h3>
                  <p>Status context for the current dataset.</p>
                </div>
              </div>
              <div className="short-sales-side-card">
                <strong>{error ? "Fallback Snapshot" : "Live Snapshot"}</strong>
                <p>
                  {error
                    ? "Backend short-interest data was unavailable, so the page fell back to a safe demo basket."
                    : "Current rows are loaded from the short-ideas endpoint for the selected symbols."}
                </p>
              </div>
            </section>
          </aside>
        </div>
      </div>
    </div>
  );
};

export default ShortSalesPage;
