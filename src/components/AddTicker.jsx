import React, { useState } from "react";
import { apiFetch } from "../apiClient";

const AddTicker = () => {
    const [ticker, setTicker] = useState("");

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (!ticker) return;

        try {
            const response = await apiFetch("/api/add_ticker", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({ ticker }),
            });

            const data = await response.json();
            alert(data.message); // Show confirmation
        } catch (error) {
            console.error("Error adding ticker:", error);
        }

        setTicker(""); // Reset input field
    };

    return (
        <div>
            <h3 style={{ margin: "0 0 10px 0", fontSize: "16px", color: "#f8fafc" }}>Add Stock to Watchlist</h3>
            <form onSubmit={handleSubmit} style={{ display: "flex", gap: "10px", alignItems: "center", flexWrap: "wrap" }}>
                <input
                    type="text"
                    value={ticker}
                    onChange={(e) => setTicker(e.target.value.toUpperCase())}
                    placeholder="Enter Stock Symbol"
                    required
                    style={{
                        minHeight: "40px",
                        minWidth: "220px",
                        padding: "0 12px",
                        borderRadius: "10px",
                        border: "1px solid #334155",
                        background: "#0f172a",
                        color: "#f8fafc",
                    }}
                />
                <button
                    type="submit"
                    style={{
                        minHeight: "40px",
                        padding: "0 16px",
                        borderRadius: "10px",
                        border: "1px solid #1d4ed8",
                        background: "#172554",
                        color: "#dbeafe",
                        fontWeight: 600,
                        cursor: "pointer",
                    }}
                >
                    Add
                </button>
            </form>
        </div>
    );
};

export default AddTicker;
