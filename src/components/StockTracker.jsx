import { useEffect, useState } from "react";
import io from "socket.io-client";
import { SOCKET_BASE } from "../apiClient";

// Establish socket connection with the backend
const socket = io(SOCKET_BASE);

function StockTracker({ ticker }) {
  const [stockData, setStockData] = useState(null);

  useEffect(() => {
    // Emit the stock tracking event
    socket.emit("track_stock", { ticker });

    // Listen for real-time stock updates
    socket.on("stock_update", (data) => {
      console.log("Real-time data:", data);
      setStockData(data);
    });

    // Cleanup: Disconnect socket when component unmounts
    return () => {
      socket.disconnect();
    };
  }, [ticker]);

  return stockData ? (
    <div>
      <h2>{stockData.ticker} - ${stockData.price}</h2>
      <p>Recommendation: {stockData.recommendation}</p>
    </div>
  ) : (
    <p>Loading...</p>
  );
}

export default StockTracker;
