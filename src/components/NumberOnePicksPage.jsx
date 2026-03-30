import React, { useEffect, useState } from "react";
import StockScanner from "./StockScanner";
import { apiFetch } from "../apiClient";

const NumberOnePicksPage = () => {
  const [stocks, setStocks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const fetchTopPicks = async () => {
      try {
        const data = await apiFetch("/api/number-one-picks");

        if (data?.candidates?.length > 0) {
          setStocks(data.candidates);
          setError("");
        } else {
          setStocks([]);
          setError("No high-confidence picks found at this time.");
        }
      } catch (err) {
        console.error("❌ Error fetching picks:", err);
        setError("Unable to load stock picks. Please try again later.");
      } finally {
        setLoading(false);
      }
    };

    fetchTopPicks();
  }, []);

  return (
    <div className="app-layout">
      <div className="stock-results-header">
        <h2>🔥 Top AI Stock Picks</h2>
        <p>This page shows high-confidence stocks with clean momentum and entry setups.</p>
      </div>

      {error && (
        <p style={{ color: "red", textAlign: "center", marginTop: "10px" }}>{error}</p>
      )}

      <StockScanner stocks={stocks} loading={loading} />
    </div>
  );
};

export default NumberOnePicksPage;
