import { useEffect, useState } from "react";
import io from "socket.io-client";
import { SOCKET_BASE } from "../apiClient";

function StockTracker({ ticker }) {
  const [stockData, setStockData] = useState(null);

  useEffect(() => {
    if (!ticker) return undefined;

    const socket = io(SOCKET_BASE);
    const onStockUpdate = (data) => {
      console.log("Real-time data:", data);
      setStockData(data);
    };

    socket.emit("track_stock", { ticker });
    socket.on("stock_update", onStockUpdate);

    return () => {
      socket.off("stock_update", onStockUpdate);
      socket.close();
    };
  }, [ticker]);

  return stockData ? (
    <div>
      <h2>
        {stockData.ticker} - ${stockData.price}
      </h2>
      <p>Recommendation: {stockData.recommendation}</p>
    </div>
  ) : (
    <p>Loading...</p>
  );
}

export default StockTracker;
