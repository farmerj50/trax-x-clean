import React, { useEffect, useMemo, useState } from "react";
import StockScanner from "./StockScanner";
import { apiFetch } from "../apiClient";

const computeUpsidePct = (candidate) => {
  const basePrice = candidate.entry_point ?? candidate.close_price ?? 1;
  const targetPrice = candidate.target_price ?? candidate.close_price ?? basePrice;
  return ((targetPrice - basePrice) / Math.max(basePrice, 0.0001)) * 100;
};

const BiggestGainsPage = () => {
  const [candidates, setCandidates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const fetchBigMoves = async () => {
      try {
        setLoading(true);
        setError("");
        const res = await apiFetch("/api/next-day-picks");
        const data = await res.json();
        if (data?.candidates?.length) {
          setCandidates(data.candidates);
        } else {
          setCandidates([]);
          setError("No big gain picks available right now.");
        }
      } catch (err) {
        console.error("Error fetching biggest gains:", err);
        setCandidates([]);
        setError("Failed to load big gain candidates.");
      } finally {
        setLoading(false);
      }
    };

    fetchBigMoves();
  }, []);

  const sortedCandidates = useMemo(() => {
    return [...candidates]
      .map((c) => ({ ...c, upsidePercent: computeUpsidePct(c) }))
      .sort((a, b) => (b.upsidePercent ?? 0) - (a.upsidePercent ?? 0));
  }, [candidates]);

  return (
    <div className="app-layout">
      <div className="stock-results-header">
        <h2>Biggest Gains Picks</h2>
        <p>AI-selected names with the largest projected upside for the next session.</p>
        {error && <p style={{ color: "#f77" }}>{error}</p>}
      </div>
      <StockScanner stocks={sortedCandidates} loading={loading} />
    </div>
  );
};

export default BiggestGainsPage;
