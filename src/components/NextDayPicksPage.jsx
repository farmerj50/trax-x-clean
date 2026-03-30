import React, { useEffect, useState } from "react";
import StockScanner from "./StockScanner";
import { apiFetch } from "../apiClient";

const NextDayPicksPage = () => {
  const [stocks, setStocks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const fetchNextDayPicks = async () => {
      try {
        const data = await apiFetch("/api/next-day-picks");

        if (data?.candidates?.length > 0) {
          const normalized = data.candidates.map((c) => ({ ...c, T: c.ticker || c.T }));
          setStocks(normalized);
          setError("");
        } else {
          setStocks([]);
          setError("No next day picks found at this time.");
        }
      } catch (err) {
        console.error("Error fetching next day picks:", err);
        setError("Unable to load next day picks. Please try again later.");
      } finally {
        setLoading(false);
      }
    };

    fetchNextDayPicks();
  }, []);

  return (
    <div className="app-layout">
      <div className="stock-results-header">
        <h2>🚀 Next Day Picks</h2>
        <p>This page shows stocks identified for strong next day potential based on today's session.</p>
      </div>

      {error && (
        <p style={{ color: "red", textAlign: "center", marginTop: "10px" }}>{error}</p>
      )}

      <StockScanner stocks={stocks} loading={loading} />
    </div>
  );
};

export default NextDayPicksPage;
