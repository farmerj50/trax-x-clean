import React, { useState, useEffect } from "react";
import { apiFetch } from "../apiClient";
import {
  ChartComponent,
  SeriesCollectionDirective,
  SeriesDirective,
  Inject,
  LineSeries,
  DateTime,
  Tooltip,
} from "@syncfusion/ej2-react-charts";

const SentimentChart = ({ ticker }) => {
  const [sentimentData, setSentimentData] = useState([]);
  const [error, setError] = useState("");

  useEffect(() => {
    const fetchSentimentData = async () => {
      try {
        const data = await apiFetch(`/api/sentiment-plot?ticker=${ticker}`);

        if (data && data.dates && data.positive && data.negative && data.neutral) {
          const formattedData = data.dates.map((date, index) => ({
            x: new Date(date),
            positive: data.positive[index] ?? 0, // Default to 0
            negative: data.negative[index] ?? 0,
            neutral: data.neutral[index] ?? 0,
          }));
          setSentimentData(formattedData);
          setError(""); // Clear error
        } else {
          setSentimentData([]);
          setError("No sentiment data available.");
        }
      } catch (err) {
        console.error("Error fetching sentiment data:", err);
        setSentimentData([]);
        setError("Failed to load sentiment data.");
      }
    };

    fetchSentimentData();
  }, [ticker]);

  return (
    <div className="sentiment-chart-container">
      {error ? (
        <p style={{ color: "red", textAlign: "center" }}>{error}</p>
      ) : (
        <ChartComponent
          primaryXAxis={{
            valueType: "DateTime",
            labelFormat: "MMM dd",
            intervalType: "Days",
            edgeLabelPlacement: "Shift",
            title: "Date",
          }}
          primaryYAxis={{
            labelFormat: "{value}",
            title: "Sentiment Count",
            minimum: 0,
            interval: 1,
          }}
          tooltip={{ enable: true }}
          dataSource={sentimentData}
          height="300px"
          width="100%"
        >
          <Inject services={[LineSeries, DateTime, Tooltip]} />
          <SeriesCollectionDirective>
            <SeriesDirective xName="x" yName="positive" type="Line" name="Positive" />
            <SeriesDirective xName="x" yName="negative" type="Line" name="Negative" />
            <SeriesDirective xName="x" yName="neutral" type="Line" name="Neutral" />
          </SeriesCollectionDirective>
        </ChartComponent>
      )}
    </div>
  );
};

export default SentimentChart;
