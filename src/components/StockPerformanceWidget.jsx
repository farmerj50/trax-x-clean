import React, { useEffect, useState } from "react";
import { apiFetch } from "../apiClient";

const StockPerformanceWidget = ({ ticker }) => {
  const [performanceData, setPerformanceData] = useState(null);
  const [isCompact, setIsCompact] = useState(false);

  const toggleView = () => setIsCompact(!isCompact);

  useEffect(() => {
    const fetchPerformanceData = async () => {
      try {
        const data = await apiFetch(`/api/stock-performance?ticker=${ticker}`);
        setPerformanceData(data);
      } catch (error) {
        console.error("Error fetching stock performance data:", error);
        setPerformanceData({ error: "Failed to load data" });
      }
    };

    fetchPerformanceData();
  }, [ticker]);

  if (!performanceData) {
    return (
      <div className="widget-loading">
        <div className="spinner"></div>
        <p>Loading Stock Performance...</p>
      </div>
    );
  }

  if (performanceData?.error) {
    return <div className="widget-error">Unable to load performance data for {ticker}</div>;
  }

  if (isCompact) {
    return (
      <div className="stock-performance-widget compact-view">
        <h4>{performanceData.name || ticker}</h4>
        <p><strong>Price:</strong> ${performanceData.current_price || "N/A"}</p>
        <p><strong>Change:</strong> {performanceData.change || "N/A"}%</p>
        <button onClick={toggleView}>Detailed View</button>
      </div>
    );
  }

  return (
    <div className="stock-performance-widget" style={{ padding: "15px", border: "1px solid #ccc", borderRadius: "8px", backgroundColor: "#f9f9f9" }}>
      <h4>{performanceData.name || ticker} Overview</h4>
      <button onClick={toggleView} style={{ marginBottom: "10px", padding: "5px 10px", backgroundColor: "#007bff", color: "#fff", border: "none", borderRadius: "4px" }}>
        Compact View
      </button>
      <p><strong>Market Cap:</strong> {performanceData.market_cap || "N/A"}</p>
      <p><strong>Current Price:</strong> ${performanceData.current_price || "N/A"}</p>
      <p><strong>Change Today:</strong> {performanceData.change || "N/A"}%</p>
      <p><strong>P/E Ratio:</strong> {performanceData.pe_ratio || "N/A"}</p>
      <p><strong>52-Week High:</strong> ${performanceData.week_52_high || "N/A"}</p>
      <p><strong>52-Week Low:</strong> ${performanceData.week_52_low || "N/A"}</p>
    </div>
  );
};

export default StockPerformanceWidget;
