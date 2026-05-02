import React, { useState, useEffect, useRef } from "react";
import { BrowserRouter as Router, Routes, Route, Link } from "react-router-dom";
import StockScanner from "./components/StockScanner";
import SearchForm from "./components/SearchForm";
import TickerNewsWidget from "./components/TickerNewsWidget";
import StocksPage from "./components/StocksPage";
import OptionsPage from "./components/OptionsPage";
import CryptoPage from "./components/CryptoPage";
import ShortSalesPage from "./components/ShortSalesPage";
import NumberOnePicksPage from "./components/NumberOnePicksPage";
import AnomaliesPage from "./components/AnomaliesPage";
import NextDayPicksPage from "./components/NextDayPicksPage";
import BiggestGainsPage from "./components/BiggestGainsPage";
import ThreeDayBreakoutsPage from "./components/ThreeDayBreakoutsPage";
import PremarketIntelligencePage from "./components/PremarketIntelligencePage";
import SocialTrackerPage from "./components/SocialTrackerPage";
import TradingPage from "./components/TradingPage";
import GlobalAlertContactBar from "./components/GlobalAlertContactBar";
import AuthGate from "./components/AuthGate";
import { apiFetch } from "./apiClient";
import "./App.css";

const App = () => {
  const [stocks, setStocks] = useState([]);
  const [tickers, setTickers] = useState([]);
  const [errorMsg, setErrorMsg] = useState("");
  const [scannerLoading, setScannerLoading] = useState(false);
  const [hasScanned, setHasScanned] = useState(false);
  const [theme, setTheme] = useState(
    localStorage.getItem("theme") ||
    (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
  );
  const [showDropdown, setShowDropdown] = useState(false);
  const dropdownRef = useRef();

  useEffect(() => {
    document.body.classList.toggle("dark-mode", theme === "dark");
    document.body.classList.toggle("light-mode", theme === "light");
    localStorage.setItem("theme", theme);
  }, [theme]);

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setShowDropdown(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const fetchStocks = async (criteria) => {
    setHasScanned(true);
    setScannerLoading(true);
    try {
      setErrorMsg("");
      const queryParams = new URLSearchParams({
        min_price: criteria.minPrice,
        max_price: criteria.maxPrice,
        min_rsi: criteria.minRSI,
        max_rsi: criteria.maxRSI,
        volume_surge: criteria.volumeSurge,
      });
      const data = await apiFetch(`/api/scan-stocks?${queryParams}`);
      console.log("scan-stocks response", data);
      if (data?.candidates?.length) {
        setStocks(data.candidates);
        setTickers(data.candidates.map((stock) => stock.T));
      } else {
        setStocks([]);
        setTickers([]);
        setErrorMsg(
          data?.error && !/no stocks found/i.test(data.error) ? data.error : ""
        );
      }
    } catch (err) {
      console.error("Fetch error:", err);
      const message = String(err?.message || "");
      const scannerUnavailable =
        message.includes("SCAN_UNAVAILABLE") ||
        message.includes("/api/scan-stocks") ||
        message.includes("xgb_ticker_encoder.pkl");
      setErrorMsg(
        scannerUnavailable
          ? "This app only provides scans during live market data. Please try scanning again during normal financial market hours."
          : "Failed to load stocks. Check backend."
      );
      setStocks([]);
      setTickers([]);
    } finally {
      setScannerLoading(false);
    }
  };

  return (
    <Router>
      <AuthGate>
        {({ user, logout, changePassword }) => (
          <>
      <div className={`menu-bar ${theme}`}>
        <h1 className="menu-title">AI Stock Scanner</h1>
        <div className="menu-buttons">
          <Link to="/"><button>Home</button></Link>
          <div
            className="dropdown"
            onMouseEnter={() => setShowDropdown(true)}
            onMouseLeave={() => setShowDropdown(false)}
            ref={dropdownRef}
          >
            <button
              type="button"
              className="dropdown-btn"
              aria-expanded={showDropdown}
              onClick={() => setShowDropdown((open) => !open)}
            >
              Stocks
            </button>

            {showDropdown && (
              <div className="dropdown-content">
                <Link to="/stocks" onClick={() => setShowDropdown(false)}>All Stocks</Link>
                <Link to="/number-one-picks" onClick={() => setShowDropdown(false)}>Number One Picks</Link>
                <Link to="/anomalies" onClick={() => setShowDropdown(false)}>Anomalies</Link>
                <Link to="/next-day-picks" onClick={() => setShowDropdown(false)}>Next Day Picks</Link>
                <Link to="/biggest-gains" onClick={() => setShowDropdown(false)}>Biggest Gains</Link>
                <Link to="/three-day-breakouts" onClick={() => setShowDropdown(false)}>3-Day Breakouts</Link>
                <Link to="/premarket-intelligence" onClick={() => setShowDropdown(false)}>Premarket Intelligence</Link>
              </div>
            )}
          </div>
          <Link to="/options"><button>Options</button></Link>
          <Link to="/crypto"><button>Crypto</button></Link>
          <Link to="/trading"><button>Trading</button></Link>
          <Link to="/social-tracker"><button>Social</button></Link>
          <Link to="/short-sales"><button>Short Sales</button></Link>
          <button onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>{theme === "dark" ? "Light Mode" : "Dark Mode"}</button>
          <button type="button" onClick={changePassword}>Change Password</button>
          <button type="button" onClick={logout}>Logout {user?.username ? `(${user.username})` : ""}</button>
        </div>
      </div>

      <GlobalAlertContactBar />

      <Routes>
        <Route
          path="/"
          element={
            <div className={`scanner-home-page ${theme}`}>
              <div className="scanner-page-shell">
                <div className="scanner-page-header">
                  <div className="scanner-page-heading">
                    <div className="scanner-page-kicker">Scanner Terminal</div>
                    <h2 className="scanner-page-title">AI Stock Scanner</h2>
                    <p className="scanner-page-subtitle">
                      Filter stocks by price, momentum, and volume expansion.
                    </p>
                  </div>
                  <div className="scanner-page-badges">
                    <span className="scanner-page-badge">
                      Status: <strong>{scannerLoading ? "Scanning" : hasScanned ? "Ready" : "Idle"}</strong>
                    </span>
                    <span className="scanner-page-badge">
                      Matches: <strong>{stocks.length}</strong>
                    </span>
                  </div>
                </div>

                <SearchForm onSearch={fetchStocks} />

                {errorMsg && <div className="scanner-alert">{errorMsg}</div>}

                <div className="scanner-content-grid">
                  <StockScanner stocks={stocks} loading={scannerLoading} hasScanned={hasScanned} />
                  <TickerNewsWidget tickers={tickers} />
                </div>
              </div>
            </div>
          }
        />
        <Route path="/stocks" element={<StocksPage theme={theme} />} />
        <Route path="/number-one-picks" element={<NumberOnePicksPage />} />
        <Route path="/anomalies" element={<AnomaliesPage />} />
        <Route path="/next-day-picks" element={<NextDayPicksPage />} />
        <Route path="/three-day-breakouts" element={<ThreeDayBreakoutsPage />} />
        <Route path="/options" element={<OptionsPage theme={theme} />} />
        <Route path="/crypto" element={<CryptoPage theme={theme} />} />
        <Route path="/trading" element={<TradingPage theme={theme} />} />
        <Route path="/social-tracker" element={<SocialTrackerPage theme={theme} />} />
        <Route path="/short-sales" element={<ShortSalesPage theme={theme} />} />
        <Route path="/biggest-gains" element={<BiggestGainsPage />} />
        <Route path="/premarket-intelligence" element={<PremarketIntelligencePage theme={theme} />} />
      </Routes>
          </>
        )}
      </AuthGate>
    </Router>
  );
};

export default App;
