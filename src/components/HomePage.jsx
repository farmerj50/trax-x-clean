import React from "react";
import SearchForm from "../components/SearchForm";
import "./HomePage.css";

const HomePage = () => {
  return (
    <div className="home-layout">
      {/* Search Bar */}
      <div className="search-bar">
        <SearchForm onSearch={() => {}} />
      </div>

      {/* Stock Results */}
      <div className="stock-results-header">
        <h2>Stock Results</h2>
      </div>

      {/* Add your stock-related components below */}
    </div>
  );
};

export default HomePage;
