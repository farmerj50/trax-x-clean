import React, { useEffect, useState } from "react";
import StockScanner from "./StockScanner";
import { apiFetch } from "../apiClient";

const ThreeDayBreakoutsPage = () => {
  const [stocks, setStocks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const fetchBreakouts = async () => {
      try {
        const res = await apiFetch("/api/three-day-breakouts");
        const data = await res.json();

        if (!res.ok) {
          throw new Error(data.error || "Failed to fetch three-day breakouts.");
        }

        if (data?.candidates?.length > 0) {
          setStocks(data.candidates);
          setError("");
        } else {
          setStocks([]);
          setError("No three-day breakout candidates found at this time.");
        }
      } catch (err) {
        console.error("❌ Error fetching breakouts:", err);
        setError("Unable to load breakouts. Please try again later.");
      } finally {
        setLoading(false);
      }
    };

    fetchBreakouts();
  }, []);

  return (
    <div className="app-layout">
      <div className="stock-results-header">
        <h2>🔥 3-Day Breakouts</h2>
        <p>Pre-breakout setups with compression, RVOL build, and cash-flow quality.</p>
      </div>

      {error && (
        <p style={{ color: "red", textAlign: "center", marginTop: "10px" }}>{error}</p>
      )}

      <StockScanner stocks={stocks} loading={loading} />
    </div>
  );
};

export default ThreeDayBreakoutsPage;
