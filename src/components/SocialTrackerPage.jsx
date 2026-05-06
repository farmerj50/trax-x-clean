import React, { useEffect, useMemo, useState } from "react";
import { apiFetch } from "../apiClient";
import "./SocialTrackerPage.css";
import React, { useEffect, useMemo, useState, useCallback } from "react";
const toCsvList = (value) =>
  String(value || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);

const formatScore = (value) => Number(value || 0).toFixed(0);

const formatSigned = (value) => {
  const number = Number(value || 0);
  const prefix = number > 0 ? "+" : "";
  return `${prefix}${number.toFixed(2)}`;
};

const formatCoverage = (value) => {
  const normalized = String(value || "").replace(/_/g, " ").trim();
  if (!normalized) return "Unknown";
  return normalized.charAt(0).toUpperCase() + normalized.slice(1);
};

const formatState = (value) => {
  const normalized = String(value || "").replace(/_/g, " ").trim();
  if (!normalized) return "Quiet";
  return normalized.charAt(0).toUpperCase() + normalized.slice(1);
};

const providerLabel = (providers) => {
  if (!Array.isArray(providers) || providers.length === 0) return "No providers configured";
  return providers.join(", ");
};

const scoreTone = (value) => {
  const score = Number(value || 0);
  if (score >= 70) return "is-strong";
  if (score >= 55) return "is-building";
  return "is-muted";
};

const SocialAssetCard = ({ asset }) => (
  <article className={`social-card ${scoreTone(asset.socialCompositeScore)}`}>
    <div className="social-card__top">
      <div>
        <div className="social-card__ticker">{asset.ticker}</div>
        <div className="social-card__name">{asset.companyName || asset.eventTopic || asset.ticker}</div>
      </div>
      <div className="social-card__score">{formatScore(asset.socialCompositeScore)}</div>
    </div>

    <div className="social-chip-row">
      <span className="social-chip">{String(asset.assetClass || "stock").replace(/_/g, " ")}</span>
      <span className="social-chip">{formatState(asset.socialTrendStage)}</span>
      <span className="social-chip">{formatState(asset.socialAlertState)}</span>
      <span className="social-chip">{formatCoverage(asset.socialCoverageStatus)}</span>
    </div>

    <div className="social-card__metrics">
      <div>
        <span>Mentions</span>
        <strong>{Number(asset.socialMentions || 0).toFixed(0)}</strong>
      </div>
      <div>
        <span>Momentum</span>
        <strong>{formatScore(asset.socialMomentumScore)}</strong>
      </div>
      <div>
        <span>Confidence</span>
        <strong>{formatScore(asset.investorConfidenceScore)}</strong>
      </div>
      <div>
        <span>Velocity</span>
        <strong>{formatSigned(asset.socialVelocity)}</strong>
      </div>
    </div>

    <p className="social-card__summary">{asset.socialSummary || "No social summary is available."}</p>

    {Array.isArray(asset.socialDrivers) && asset.socialDrivers.length > 0 ? (
      <div className="social-chip-row">
        {asset.socialDrivers.slice(0, 3).map((driver) => (
          <span key={`${asset.ticker}-${driver}`} className="social-chip social-chip--soft">
            {driver}
          </span>
        ))}
      </div>
    ) : null}
  </article>
);

const SocialTrackerPage = () => {
  const [filters, setFilters] = useState({
    tickers: "",
    crypto: "BTC,ETH,SOL,DOGE",
    events: "",
    limit: "8",
  });
  const [payload, setPayload] = useState({
    timestamp: "",
    providers: { configured: [], trackerEnabled: false, historyPath: "" },
    leaders: [],
    alerts: [],
    stocks: [],
    crypto: [],
    predictionMarkets: [],
    summary: {},
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadTracker = useCallback(async (nextFilters = filters) => {
    try {
      setLoading(true);
      setError("");
      const params = new URLSearchParams({ limit: nextFilters.limit || "8" });
      if (nextFilters.tickers.trim()) params.set("tickers", nextFilters.tickers.trim());
      if (nextFilters.crypto.trim()) params.set("crypto", nextFilters.crypto.trim());
      if (nextFilters.events.trim()) params.set("events", nextFilters.events.trim());

      const data = await apiFetch(`/api/social-tracker?${params.toString()}`, { timeoutMs: 35000 });
      setPayload({
        timestamp: data.timestamp || "",
        providers: data.providers || { configured: [], trackerEnabled: false, historyPath: "" },
        leaders: Array.isArray(data.leaders) ? data.leaders : [],
        alerts: Array.isArray(data.alerts) ? data.alerts : [],
        stocks: Array.isArray(data.stocks) ? data.stocks : [],
        crypto: Array.isArray(data.crypto) ? data.crypto : [],
        predictionMarkets: Array.isArray(data.predictionMarkets) ? data.predictionMarkets : [],
        summary: data.summary || {},
      });
    } catch (err) {
      setError(String(err?.message || "Failed to load social tracker."));
    } finally {
      setLoading(false);
    }
  }, [filters]);

 useEffect(() => {
  loadTracker();
}, [loadTracker]);

  const lastUpdated = useMemo(
    () => (payload.timestamp ? new Date(payload.timestamp).toLocaleString() : "Waiting for first refresh"),
    [payload.timestamp]
  );

  return (
    <div className="social-page">
      <div className="social-shell">
        <div className="social-hero">
          <div>
            <div className="social-kicker">Standalone Signal Surface</div>
            <h2 className="social-title">Social Tracker</h2>
            <p className="social-subtitle">
              Separate lane for social buzz, provider health, and early attention shifts without mixing it into the
              stable premarket workflow.
            </p>
          </div>

          <div className="social-badges">
            <span className="social-badge">Tracker: <strong>{payload.providers?.trackerEnabled ? "Enabled" : "Disabled"}</strong></span>
            <span className="social-badge">Configured: <strong>{payload.providers?.configured?.length || 0}</strong></span>
            <span className="social-badge">Live coverage: <strong>{Number(payload.summary?.liveCoverageCount || 0)}</strong></span>
            <span className="social-badge">Updated: <strong>{lastUpdated}</strong></span>
          </div>
        </div>

        <div className="social-filter-row">
          <div className="social-filter-group">
            <label htmlFor="social-tickers">Stock tickers</label>
            <input
              id="social-tickers"
              value={filters.tickers}
              onChange={(e) => setFilters((prev) => ({ ...prev, tickers: e.target.value }))}
              placeholder="AAPL,NVDA,TSLA"
            />
          </div>
          <div className="social-filter-group">
            <label htmlFor="social-crypto">Crypto symbols</label>
            <input
              id="social-crypto"
              value={filters.crypto}
              onChange={(e) => setFilters((prev) => ({ ...prev, crypto: e.target.value }))}
              placeholder="BTC,ETH,SOL"
            />
          </div>
          <div className="social-filter-group">
            <label htmlFor="social-events">Event topics</label>
            <input
              id="social-events"
              value={filters.events}
              onChange={(e) => setFilters((prev) => ({ ...prev, events: e.target.value }))}
              placeholder="fda approval,defense contract"
            />
          </div>
          <div className="social-filter-group social-filter-group--limit">
            <label htmlFor="social-limit">Top assets</label>
            <select
              id="social-limit"
              value={filters.limit}
              onChange={(e) => setFilters((prev) => ({ ...prev, limit: e.target.value }))}
            >
              <option value="5">5</option>
              <option value="8">8</option>
              <option value="10">10</option>
              <option value="12">12</option>
            </select>
          </div>
          <div className="social-actions">
            <button className="social-btn social-btn--primary" type="button" onClick={() => loadTracker(filters)} disabled={loading}>
              {loading ? "Refreshing..." : "Refresh tracker"}
            </button>
          </div>
        </div>

        {error ? <div className="social-alert">{error}</div> : null}

        <div className="social-summary-grid">
          <div className="social-summary-card">
            <span>Top asset</span>
            <strong>{payload.summary?.topSocialTicker || "None"}</strong>
          </div>
          <div className="social-summary-card">
            <span>Alerts</span>
            <strong>{Number(payload.summary?.earlyAlertCount || 0)}</strong>
          </div>
          <div className="social-summary-card">
            <span>Watchlist</span>
            <strong>{Number(payload.summary?.watchCount || 0)}</strong>
          </div>
          <div className="social-summary-card">
            <span>Providers</span>
            <strong>{providerLabel(payload.providers?.configured)}</strong>
          </div>
        </div>

        <div className="social-page-grid">
          <section className="social-panel">
            <div className="social-panel__header">
              <div>
                <h3>Leaders</h3>
                <p>Top-ranked social names across stocks, crypto, and event themes.</p>
              </div>
            </div>
            <div className="social-card-grid">
              {payload.leaders.length > 0 ? payload.leaders.map((asset) => <SocialAssetCard key={`leader-${asset.assetClass}-${asset.ticker}`} asset={asset} />) : <div className="social-empty">No leaders returned yet.</div>}
            </div>
          </section>

          <aside className="social-side">
            <section className="social-panel">
              <div className="social-panel__header">
                <div>
                  <h3>Alerts</h3>
                  <p>Only assets already in watch or alert state.</p>
                </div>
              </div>
              {payload.alerts.length > 0 ? (
                <div className="social-list">
                  {payload.alerts.map((asset) => (
                    <div key={`alert-${asset.assetClass}-${asset.ticker}`} className="social-list__item">
                      <strong>{asset.ticker}</strong>
                      <span>{formatState(asset.socialAlertState)}</span>
                      <span>{formatScore(asset.socialCompositeScore)}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="social-empty">No active alert-state assets.</div>
              )}
            </section>

            <section className="social-panel">
              <div className="social-panel__header">
                <div>
                  <h3>Query Preview</h3>
                  <p>The dedicated lane is driven by explicit tracker inputs.</p>
                </div>
              </div>
              <div className="social-query-box">
                <div><span>Stocks</span><strong>{toCsvList(filters.tickers).join(", ") || "Premarket seed universe"}</strong></div>
                <div><span>Crypto</span><strong>{toCsvList(filters.crypto).join(", ") || "None"}</strong></div>
                <div><span>Events</span><strong>{toCsvList(filters.events).join(", ") || "Default topics"}</strong></div>
              </div>
            </section>
          </aside>
        </div>

        <div className="social-lane-grid">
          <section className="social-panel">
            <div className="social-panel__header">
              <div>
                <h3>Stocks</h3>
                <p>Equity-specific social read without premarket page coupling.</p>
              </div>
            </div>
            <div className="social-card-grid">
              {payload.stocks.length > 0 ? payload.stocks.map((asset) => <SocialAssetCard key={`stock-${asset.ticker}`} asset={asset} />) : <div className="social-empty">No stock assets available.</div>}
            </div>
          </section>

          <section className="social-panel">
            <div className="social-panel__header">
              <div>
                <h3>Crypto</h3>
                <p>Separate crypto social lane.</p>
              </div>
            </div>
            <div className="social-card-grid">
              {payload.crypto.length > 0 ? payload.crypto.map((asset) => <SocialAssetCard key={`crypto-${asset.ticker}`} asset={asset} />) : <div className="social-empty">No crypto assets available.</div>}
            </div>
          </section>

          <section className="social-panel">
            <div className="social-panel__header">
              <div>
                <h3>Prediction Themes</h3>
                <p>Event-driven topics scored from the same social engine.</p>
              </div>
            </div>
            <div className="social-card-grid">
              {payload.predictionMarkets.length > 0 ? payload.predictionMarkets.map((asset) => <SocialAssetCard key={`event-${asset.ticker}`} asset={asset} />) : <div className="social-empty">No event-theme assets available.</div>}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
};

export default SocialTrackerPage;
