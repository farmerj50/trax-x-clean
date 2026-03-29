import React, { useState, useEffect } from "react";
import { Line } from "react-chartjs-2";
import axios from "axios";
import { API_BASE } from "../apiClient";

const ProfessionalChart = ({ ticker, entryPoint, exitPoint, intervalOptions }) => {
  const [interval, setInterval] = useState(intervalOptions[0]); // Default to the first interval
  const [chartData, setChartData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    fetchChartData();
  }, [ticker, interval]);

  const fetchChartData = async () => {
    try {
      setError("");
      const response = await axios.get(`${API_BASE}/api/technical-indicators`, {
        params: {
          ticker: ticker,
          interval: interval.toLowerCase(), // Convert interval to lowercase for API compatibility
        },
      });
      setChartData(response.data);
    } catch (err) {
      console.error(err);
      setError("Failed to fetch chart data.");
    }
  };

  const renderChart = () => {
    if (!chartData) return null;

    return (
      <Line
        data={{
          labels: chartData.dates,
          datasets: [
            {
              label: "Close Price",
              data: chartData.close,
              borderColor: "blue",
              fill: false,
            },
            {
              label: "SMA",
              data: chartData.sma,
              borderColor: "green",
              fill: false,
            },
            {
              label: "EMA",
              data: chartData.ema,
              borderColor: "red",
              fill: false,
            },
            {
              label: "Bollinger Band Upper",
              data: chartData.bb_upper,
              borderColor: "purple",
              fill: false,
            },
            {
              label: "Bollinger Band Lower",
              data: chartData.bb_lower,
              borderColor: "orange",
              fill: false,
            },
          ],
        }}
        options={{
          responsive: true,
          maintainAspectRatio: false,
        }}
      />
    );
  };

  return (
    <div className="professional-chart">
      <h3>{ticker}</h3>
      <div className="chart-controls">
        <label>Interval: </label>
        <select value={interval} onChange={(e) => setInterval(e.target.value)}>
          {intervalOptions.map((opt) => (
            <option key={opt} value={opt}>
              {opt}
            </option>
          ))}
        </select>
      </div>

      {error && <p style={{ color: "red" }}>{error}</p>}

      <div className="chart-container">
        {renderChart()}
        <div className="chart-info">
          <p>Entry Point: ${entryPoint.toFixed(2)}</p>
          <p>Exit Point: ${exitPoint.toFixed(2)}</p>
        </div>
      </div>
    </div>
  );
};

export default ProfessionalChart;
