import React, { useCallback, useEffect, useState } from "react";
import StockScanner from "./StockScanner";
import { apiFetch } from "../apiClient";

const AnomaliesPage = () => {
  const [stocks, setStocks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [date, setDate] = useState(new Date().toISOString().split("T")[0]); // Today
  const [threshold, setThreshold] = useState(3);

  const fetchAnomalies = useCallback(async () => {
    try {
      setLoading(true);
      const res = await apiFetch(`/api/anomalies?date=${date}&threshold_multiplier=${threshold}`);
      const data = await res.json();

      if (data?.candidates?.length) {
        const normalized = data.candidates
          .filter((c) => c.ticker)
          .map((c) => ({
            ...c,
            T: c.ticker,
            entry_point: c.close_price || c.entry_point || null,
            exit_point: c.exit_point || null,
            stop_loss:
              c.stop_loss ??
              (c.close_price ? parseFloat(c.close_price) * 0.97 : null),
            target_price:
              c.target_price ??
              (c.close_price ? parseFloat(c.close_price) * 1.05 : null),
          }));
        setStocks(normalized);
      } else {
        setStocks([]);
      }
    } catch (err) {
      console.error("ƒ?O Failed to load anomalies:", err);
      setStocks([]);
    } finally {
      setLoading(false);
    }
  }, [date, threshold]);

  useEffect(() => {
    fetchAnomalies();
  }, [fetchAnomalies]);

  const handleSearch = () => {
    fetchAnomalies();
  };

  return (
    <div className="app-layout">
      <div className="stock-results-header">
        <h2>dYs" Anomaly Detector</h2>
        <p>Stocks with extreme deviations detected by AI based on trade activity.</p>

        {/* Controls */}
        <div className="controls" style={{ marginBottom: "1rem" }}>
          <label style={{ marginRight: "1rem" }}>
            dY". Date:
            <input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              style={{ marginLeft: "0.5rem" }}
            />
          </label>
          <label style={{ marginRight: "1rem" }}>
            dYZs Z-Score Threshold:
            <input
              type="number"
              min="1"
              max="10"
              step="0.1"
              value={threshold}
              onChange={(e) => setThreshold(e.target.value)}
              style={{ marginLeft: "0.5rem", width: "60px" }}
            />
          </label>
          <button onClick={handleSearch} style={{ padding: "0.5rem 1rem" }}>
            dY"? Search
          </button>
        </div>
      </div>

      <StockScanner stocks={stocks} loading={loading} />
    </div>
  );
};

export default AnomaliesPage;
