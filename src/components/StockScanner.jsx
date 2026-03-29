import React from "react";
import CandlestickChart from "./CandlestickChart";
import "./StockScanner.css";

const StockScanner = ({ stocks, loading, hasScanned }) => {
  const downloadCSV = () => {
    if (!stocks || stocks.length === 0) return;

    const csvContent = [
      ["Ticker", "Volatility", "Price Change", "RSI", "Close Price", "Entry", "Stop", "Target"],
      ...stocks.map((stock, idx) => {
        const ticker = stock.T || stock.ticker || `TICKER_${idx}`;
        const entry = stock.entry_point ?? stock.entry_price;
        const stop = stock.stop_loss;
        const target = stock.target_price ?? stock.exit_point;
        return [
          ticker,
          stock.volatility ? `${(stock.volatility * 100).toFixed(2)}%` : "N/A",
          stock.price_change ? `${(stock.price_change * 100).toFixed(2)}%` : "N/A",
          stock.rsi ? stock.rsi.toFixed(2) : "N/A",
          stock.c ? stock.c.toFixed(2) : "N/A",
          entry ? `$${parseFloat(entry).toFixed(2)}` : "N/A",
          stop ? `$${parseFloat(stop).toFixed(2)}` : "N/A",
          target ? `$${parseFloat(target).toFixed(2)}` : "N/A",
        ];
      }),
    ]
      .map((row) => row.join(","))
      .join("\n");

    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.setAttribute("href", url);
    link.setAttribute("download", "scanned_stocks.csv");
    link.click();
  };

  return (
    <div className="scanner-card scanner-results-card">
      <div className="scanner-card-header">
        <div>
          <h3 className="scanner-card-title">Stock Results</h3>
          <p className="scanner-card-subtitle">Matching symbols based on scanner criteria.</p>
        </div>
        <div className="scanner-results-actions">
          <span className="scanner-results-count">{stocks?.length || 0} matches</span>
          <button
            onClick={downloadCSV}
            className="scanner-btn secondary"
            disabled={!stocks || stocks.length === 0}
          >
            Export CSV
          </button>
        </div>
      </div>

      <div className="scanner-card-body">
        {loading ? (
          <div className="scanner-empty-state">
            <div className="scanner-empty-kicker">Scanner Running</div>
            <h4>Loading matching setups...</h4>
            <p>Scanning for symbols that meet the current price, RSI, and volume criteria.</p>
          </div>
        ) : !hasScanned ? (
          <div className="scanner-empty-state">
            <div className="scanner-empty-kicker">Scanner Ready</div>
            <h4>Set your filters and run a scan.</h4>
            <p>
              Results will appear here with technical levels, rank score, and a live chart
              view.
            </p>
          </div>
        ) : (
          <div className="stock-list">
            {stocks && stocks.length > 0 ? (
              stocks.map((stock, idx) => {
                const ticker = stock.T || stock.ticker || `TICKER_${idx}`;
                const entryVal = stock.entry_point ?? stock.entry_price;
                const stopVal = stock.stop_loss;
                const targetVal = stock.target_price ?? stock.exit_point;
                const rankScore =
                  typeof stock.rank_score === "number" && !isNaN(stock.rank_score)
                    ? stock.rank_score
                    : stock.score ?? null;

                const entryPrice = entryVal && !isNaN(entryVal) ? parseFloat(entryVal) : null;
                const stopLoss = stopVal && !isNaN(stopVal) ? parseFloat(stopVal) : null;
                const targetPrice =
                  targetVal && !isNaN(targetVal) ? parseFloat(targetVal) : null;

                return (
                  <div className="stock-item" key={ticker}>
                    <div className="stock-stats">
                      <div className="stock-stats-header">
                        <h4>{ticker}</h4>
                        {rankScore !== null && (
                          <span className="stock-score-pill">{Number(rankScore).toFixed(2)}</span>
                        )}
                      </div>
                      <p>
                        <strong>Volatility:</strong>{" "}
                        {stock.volatility ? `${(stock.volatility * 100).toFixed(2)}%` : "N/A"}
                      </p>
                      <p>
                        <strong>Price Change:</strong>{" "}
                        {stock.price_change
                          ? `${(stock.price_change * 100).toFixed(2)}%`
                          : "N/A"}
                      </p>
                      <p>
                        <strong>RSI:</strong> {stock.rsi ? stock.rsi.toFixed(2) : "N/A"}
                      </p>
                      <p>
                        <strong>Entry:</strong> {entryPrice ? `$${entryPrice.toFixed(2)}` : "--"}
                      </p>
                      <p>
                        <strong>Stop:</strong> {stopLoss ? `$${stopLoss.toFixed(2)}` : "--"}
                      </p>
                      <p>
                        <strong>Target:</strong>{" "}
                        {targetPrice ? `$${targetPrice.toFixed(2)}` : "--"}
                      </p>
                    </div>

                    <div className="stock-chart">
                      {ticker && !ticker.startsWith("TICKER_") ? (
                        <CandlestickChart
                          ticker={ticker}
                          entryPoint={entryPrice || 0}
                          exitPoint={targetPrice || 0}
                        />
                      ) : (
                        <p className="stock-chart-empty">No chart available.</p>
                      )}
                    </div>
                  </div>
                );
              })
            ) : (
              <div className="scanner-empty-state">
                <div className="scanner-empty-kicker">Scanner Idle</div>
                <h4>No stocks matched your criteria.</h4>
                <p>Try widening the RSI or price filters to surface more candidates.</p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default StockScanner;
