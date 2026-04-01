import React, { useEffect, useState } from "react";
import { io } from "socket.io-client";
import { SOCKET_BASE } from "../apiClient";

const LiveStockUpdates = ({ selectedTicker }) => {
  const [livePrice, setLivePrice] = useState(null);

  useEffect(() => {
    if (!selectedTicker) return undefined;

    const socket = io(SOCKET_BASE);
    const onStockUpdate = (data) => {
      if (data.ticker === selectedTicker) {
        console.log(`Live Update Received for ${selectedTicker}:`, data.price);
        setLivePrice(data.price);
      }
    };

    socket.on("stock_update", onStockUpdate);

    return () => {
      socket.off("stock_update", onStockUpdate);
      socket.close();
    };
  }, [selectedTicker]);

  return (
    <div>
      <h3>{selectedTicker} Live Price</h3>
      <p style={{ fontSize: "18px", fontWeight: "bold", color: "green" }}>
        {livePrice !== null ? `$${livePrice.toFixed(2)}` : "Waiting for updates..."}
      </p>
    </div>
  );
};

export default LiveStockUpdates;
