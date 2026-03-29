import React, { useState } from "react";
import "./SearchForm.css";

const SearchForm = ({ onSearch }) => {
  const [minPrice, setMinPrice] = useState("");
  const [maxPrice, setMaxPrice] = useState("");
  const [minRSI, setMinRSI] = useState(30);
  const [maxRSI, setMaxRSI] = useState(70);
  const [volumeSurge, setVolumeSurge] = useState(1.2);

  const handleSearch = () => {
    // Create search parameters and pass to parent
    const criteria = {
      minPrice: minPrice || "0",
      maxPrice: maxPrice || "1000000",
      minRSI: minRSI || "0",
      maxRSI: maxRSI || "100",
      volumeSurge: volumeSurge || "1",
    };
    onSearch(criteria);
  };

  const handleSubmit = (event) => {
    event.preventDefault();
    handleSearch();
  };

  return (
    <div className="scanner-card scanner-filters-card">
      <div className="scanner-card-header">
        <div>
          <h3 className="scanner-card-title">Scanner Filters</h3>
          <p className="scanner-card-subtitle">Filter stocks by price, momentum, and volume expansion.</p>
        </div>
      </div>

      <form className="scanner-card-body search-form" onSubmit={handleSubmit}>
        <div className="scanner-filter-grid">
          <label className="scanner-field">
            <span className="scanner-field-label">Min Price</span>
            <input
              className="scanner-input"
              type="number"
              value={minPrice}
              onChange={(e) => setMinPrice(e.target.value)}
              placeholder="0"
            />
          </label>

          <label className="scanner-field">
            <span className="scanner-field-label">Max Price</span>
            <input
              className="scanner-input"
              type="number"
              value={maxPrice}
              onChange={(e) => setMaxPrice(e.target.value)}
              placeholder="1000"
            />
          </label>

          <label className="scanner-field">
            <span className="scanner-field-label">Min RSI</span>
            <input
              className="scanner-input"
              type="number"
              value={minRSI}
              onChange={(e) => setMinRSI(e.target.value)}
              placeholder="30"
            />
          </label>

          <label className="scanner-field">
            <span className="scanner-field-label">Max RSI</span>
            <input
              className="scanner-input"
              type="number"
              value={maxRSI}
              onChange={(e) => setMaxRSI(e.target.value)}
              placeholder="70"
            />
          </label>

          <label className="scanner-field">
            <span className="scanner-field-label">Volume Surge</span>
            <input
              className="scanner-input"
              type="number"
              step="0.1"
              value={volumeSurge}
              onChange={(e) => setVolumeSurge(e.target.value)}
              placeholder="1.2"
            />
          </label>

          <div className="scanner-field scanner-field-action">
            <span className="scanner-field-label">Run Scanner</span>
            <button type="submit" className="scanner-btn">Search Stocks</button>
          </div>
        </div>
      </form>
    </div>
  );
};

export default SearchForm;
