import React, { useEffect, useMemo, useState } from "react";
import { apiFetch } from "../apiClient";
import "./CryptoPage.css";

const fallbackCoins = [
  { id: "bitcoin", name: "Bitcoin", symbol: "BTC", price: 42000, change24h: 2.3, dominance: 49.0 },
  { id: "ethereum", name: "Ethereum", symbol: "ETH", price: 2300, change24h: 1.8, dominance: 18.5 },
  { id: "solana", name: "Solana", symbol: "SOL", price: 92, change24h: -0.6, dominance: 2.1 },
];

const CryptoPage = () => {
  const [coins, setCoins] = useState(fallbackCoins);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [lastUpdated, setLastUpdated] = useState("");

  const fetchLive = async () => {
    try {
      setLoading(true);
      setError("");
      const res = await apiFetch(`/api/crypto-signals?ticker=BTC`);
      const data = await res.json();
      if (res.ok && data?.signals) {
        setCoins([
          {
            id: data.signals.ticker.toLowerCase(),
            name: data.signals.ticker,
            symbol: data.signals.ticker,
            price: data.signals.entry,
            change24h: (data.signals.score || 0) * 10,
          },
          ...fallbackCoins.slice(1),
        ]);
      } else {
        setCoins(fallbackCoins);
        setError("Using fallback data; live fetch failed.");
      }
    } catch (err) {
      console.warn("Crypto fetch failed; using fallback.", err);
      setError("Using fallback data; live fetch failed.");
      setCoins(fallbackCoins);
    } finally {
      setLoading(false);
      setLastUpdated(new Date().toLocaleTimeString());
    }
  };

  useEffect(() => {
    fetchLive();
  }, []);

  const marketStats = useMemo(() => {
    const avgChange =
      coins.length > 0 ? coins.reduce((sum, coin) => sum + Number(coin.change24h || 0), 0) / coins.length : 0;
    const leader = [...coins].sort((a, b) => Number(b.change24h || 0) - Number(a.change24h || 0))[0];
    const laggard = [...coins].sort((a, b) => Number(a.change24h || 0) - Number(b.change24h || 0))[0];
    return { avgChange, leader, laggard };
  }, [coins]);

  return (
    <div className="crypto-page">
      <div className="crypto-page__shell">
        <div className="crypto-page__hero">
          <div>
            <div className="crypto-page__kicker">Digital Asset Monitor</div>
            <h2 className="crypto-page__title">Crypto Watch</h2>
            <p className="crypto-page__subtitle">
              Quick market board for majors with fallback-safe pricing, directional context, and
              a cleaner terminal layout.
            </p>
          </div>
          <div className="crypto-page__hero-actions">
            <div className="crypto-page__badges">
              <span className="crypto-status-pill">
                Feed: <strong>{error ? "Fallback" : loading ? "Refreshing" : "Live"}</strong>
              </span>
              {lastUpdated && (
                <span className="crypto-status-pill">
                  Updated: <strong>{lastUpdated}</strong>
                </span>
              )}
            </div>
            <button className="crypto-btn" onClick={fetchLive} disabled={loading}>
              {loading ? "Loading..." : "Refresh"}
            </button>
          </div>
        </div>

        {error && <div className="crypto-alert">{error}</div>}

        <div className="crypto-summary-grid">
          <div className="crypto-summary-card">
            <span className="crypto-summary-card__label">Tracked Assets</span>
            <strong>{coins.length}</strong>
          </div>
          <div className="crypto-summary-card">
            <span className="crypto-summary-card__label">Average 24H Move</span>
            <strong className={marketStats.avgChange >= 0 ? "is-positive" : "is-negative"}>
              {marketStats.avgChange >= 0 ? "+" : ""}
              {marketStats.avgChange.toFixed(2)}%
            </strong>
          </div>
          <div className="crypto-summary-card">
            <span className="crypto-summary-card__label">Leader</span>
            <strong>{marketStats.leader ? marketStats.leader.symbol : "-"}</strong>
          </div>
          <div className="crypto-summary-card">
            <span className="crypto-summary-card__label">Weakest</span>
            <strong>{marketStats.laggard ? marketStats.laggard.symbol : "-"}</strong>
          </div>
        </div>

        <div className="crypto-page__grid">
          <section className="crypto-panel crypto-panel--board">
            <div className="crypto-panel__header">
              <div>
                <h3>Market Board</h3>
                <p>Snapshot of majors with price, 24H move, and dominance context.</p>
              </div>
            </div>
            <div className="crypto-board">
              {coins.map((coin) => (
                <article key={coin.id} className="crypto-coin-card">
                  <div className="crypto-coin-card__top">
                    <div>
                      <h4>{coin.name}</h4>
                      <span>{coin.symbol}</span>
                    </div>
                    <div className={`crypto-change-pill ${Number(coin.change24h || 0) >= 0 ? "is-positive" : "is-negative"}`}>
                      {Number(coin.change24h || 0) >= 0 ? "+" : ""}
                      {Number(coin.change24h || 0).toFixed(2)}%
                    </div>
                  </div>
                  <div className="crypto-coin-card__price">
                    ${Number(coin.price || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}
                  </div>
                  <div className="crypto-coin-card__meta">
                    <span>Dominance</span>
                    <strong>{coin.dominance !== undefined ? `${coin.dominance}%` : "-"}</strong>
                  </div>
                </article>
              ))}
            </div>
          </section>

          <aside className="crypto-page__side">
            <section className="crypto-panel">
              <div className="crypto-panel__header">
                <div>
                  <h3>Strength Leader</h3>
                  <p>Best performer in the current watch list.</p>
                </div>
              </div>
              <div className="crypto-side-card">
                <strong>{marketStats.leader ? `${marketStats.leader.name} (${marketStats.leader.symbol})` : "-"}</strong>
                <p>
                  {marketStats.leader
                    ? `Price $${Number(marketStats.leader.price || 0).toLocaleString(undefined, {
                        maximumFractionDigits: 2,
                      })} with a ${marketStats.leader.change24h >= 0 ? "+" : ""}${Number(
                        marketStats.leader.change24h || 0
                      ).toFixed(2)}% 24H move.`
                    : "No leader available."}
                </p>
              </div>
            </section>

            <section className="crypto-panel">
              <div className="crypto-panel__header">
                <div>
                  <h3>Risk Read</h3>
                  <p>Simple directional pulse from the current basket.</p>
                </div>
              </div>
              <div className="crypto-side-card">
                <strong className={marketStats.avgChange >= 0 ? "is-positive" : "is-negative"}>
                  {marketStats.avgChange >= 0 ? "Risk-On Bias" : "Risk-Off Bias"}
                </strong>
                <p>
                  The tracked basket is averaging {marketStats.avgChange >= 0 ? "+" : ""}
                  {marketStats.avgChange.toFixed(2)}% across the current 24H window.
                </p>
              </div>
            </section>

            <section className="crypto-panel">
              <div className="crypto-panel__header">
                <div>
                  <h3>Feed Notes</h3>
                  <p>Status context for the current data source.</p>
                </div>
              </div>
              <div className="crypto-side-card">
                <strong>{error ? "Fallback Snapshot" : "Live Snapshot"}</strong>
                <p>
                  {error
                    ? "Live crypto signals were unavailable, so the page is showing safe fallback majors."
                    : "Data loaded successfully from the crypto signals endpoint for the current session."}
                </p>
              </div>
            </section>
          </aside>
        </div>
      </div>
    </div>
  );
};

export default CryptoPage;
