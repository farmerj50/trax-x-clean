import React, { useEffect, useMemo, useState } from "react";
import { apiFetch } from "../apiClient";
import "./TradingPage.css";

const defaultTicket = {
  symbol: "AAPL",
  side: "buy",
  type: "market",
  qty: "1",
  limitPrice: "",
  estimatedPrice: "100",
  timeInForce: "day",
  assetClass: "stock",
};

const money = (value) => {
  const num = Number(value);
  return Number.isFinite(num)
    ? num.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 2 })
    : "-";
};

const qty = (value) => {
  const num = Number(value);
  return Number.isFinite(num) ? num.toLocaleString(undefined, { maximumFractionDigits: 8 }) : "-";
};

const alpacaAccountErrorMessage = (err) => {
  const raw = err?.message || "";
  if (/unauthorized|rejected the broker api credentials|HTTP 401/i.test(raw)) {
    return "Alpaca rejected the Broker API credentials. Confirm the Broker API key and secret match the selected Broker Dashboard environment.";
  }
  return raw || "Failed to load Alpaca accounts.";
};

const TradingPage = () => {
  const [status, setStatus] = useState(null);
  const [account, setAccount] = useState(null);
  const [positions, setPositions] = useState([]);
  const [orders, setOrders] = useState([]);
  const [auditLog, setAuditLog] = useState([]);
  const [ticket, setTicket] = useState(defaultTicket);
  const [alpacaAccounts, setAlpacaAccounts] = useState([]);
  const [selectedAlpacaAccount, setSelectedAlpacaAccount] = useState(null);
  const [readiness, setReadiness] = useState(null);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [previewingOrder, setPreviewingOrder] = useState(false);
  const [testingProvider, setTestingProvider] = useState(false);
  const [loadingAlpacaAccounts, setLoadingAlpacaAccounts] = useState(false);
  const [creatingSandboxAccount, setCreatingSandboxAccount] = useState(false);
  const [fundingSandboxAccount, setFundingSandboxAccount] = useState(false);
  const [checkingAlpacaEnv, setCheckingAlpacaEnv] = useState(false);
  const [orderPreview, setOrderPreview] = useState(null);
  const [pendingSubmit, setPendingSubmit] = useState(null);
  const [marketClock, setMarketClock] = useState(null);
  const [envDiagnostics, setEnvDiagnostics] = useState(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [alpacaNotice, setAlpacaNotice] = useState("");

  const loadTrading = async () => {
    try {
      setLoading(true);
      setError("");
      const [accountData, positionsData, ordersData, selectedAlpacaData, readinessData, auditData, clockData] = await Promise.all([
        apiFetch("/api/trading/account"),
        apiFetch("/api/trading/positions"),
        apiFetch("/api/trading/orders?limit=25"),
        apiFetch("/api/trading/alpaca/selected-account"),
        apiFetch("/api/trading/readiness").catch(() => null),
        apiFetch("/api/trading/audit-log?limit=25").catch(() => null),
        apiFetch("/api/trading/market-clock").catch(() => null),
      ]);
      setStatus({
        enabled: accountData.enabled,
        mode: accountData.mode,
        provider: accountData.provider,
        brokerEnvironment: accountData.brokerEnvironment,
        brokerIsSandbox: accountData.brokerIsSandbox,
        supportedMode: accountData.supportedMode,
        liveTradingAvailable: accountData.liveTradingAvailable,
        brokerConfigured: accountData.brokerConfigured,
        paperAutoFill: accountData.paperAutoFill,
        orderSubmissionEnabled: accountData.orderSubmissionEnabled,
        orderSubmissionLocked: accountData.orderSubmissionLocked,
        riskControls: accountData.riskControls,
        message: accountData.message,
      });
      setAccount(accountData.account || null);
      setPositions(Array.isArray(positionsData.positions) ? positionsData.positions : []);
      setOrders(Array.isArray(ordersData.orders) ? ordersData.orders : []);
      setAuditLog(Array.isArray(auditData?.auditLog) ? auditData.auditLog : []);
      setMarketClock(clockData?.clock || null);
      setSelectedAlpacaAccount(selectedAlpacaData || null);
      if (readinessData) {
        setReadiness(readinessData);
      }
    } catch (err) {
      setError(err?.message || "Trading layer is unavailable.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadTrading();
  }, []);

  const estimatedNotional = useMemo(() => {
    const price = Number(ticket.type === "limit" ? ticket.limitPrice : ticket.estimatedPrice);
    const shares = Number(ticket.qty);
    return Number.isFinite(price) && Number.isFinite(shares) ? price * shares : 0;
  }, [ticket]);

  const updateTicket = (key, value) => {
    setTicket((current) => ({ ...current, [key]: value }));
    setOrderPreview(null);
  };

  const buildOrderPayload = () => ({
    ...ticket,
    symbol: ticket.symbol.toUpperCase().trim(),
    qty: Number(ticket.qty),
    limitPrice: ticket.type === "limit" ? Number(ticket.limitPrice) : undefined,
    estimatedPrice: ticket.estimatedPrice ? Number(ticket.estimatedPrice) : undefined,
    source: "trading-page",
  });

  const previewOrder = async () => {
    try {
      setPreviewingOrder(true);
      setError("");
      setMessage("");
      const response = await apiFetch("/api/trading/orders/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildOrderPayload()),
      });
      setOrderPreview(response.preview || null);
      setMessage(response.message || "Order preview ready.");
    } catch (err) {
      setOrderPreview(null);
      setError(err?.message || "Order preview failed.");
    } finally {
      setPreviewingOrder(false);
    }
  };

  const submitOrder = async (event) => {
    event.preventDefault();
    setPendingSubmit(buildOrderPayload());
  };

  const confirmSubmitOrder = async () => {
    const payload = pendingSubmit;
    if (!payload) return;
    try {
      setSubmitting(true);
      setError("");
      setMessage("");
      const response = await apiFetch("/api/trading/orders", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      setMessage(`Order ${response.order?.status || "submitted"}: ${response.order?.symbol || payload.symbol}`);
      setOrderPreview(null);
      setPendingSubmit(null);
      await loadTrading();
      window.setTimeout(loadTrading, 3000);
    } catch (err) {
      setError(err?.message || "Order rejected.");
    } finally {
      setSubmitting(false);
    }
  };

  const cancelOrder = async (orderId) => {
    try {
      setError("");
      setMessage("");
      await apiFetch(`/api/trading/orders/${encodeURIComponent(orderId)}`, { method: "DELETE" });
      setMessage("Order canceled.");
      await loadTrading();
    } catch (err) {
      setError(err?.message || "Cancel failed.");
    }
  };

  const testProvider = async () => {
    try {
      setTestingProvider(true);
      setError("");
      setMessage("");
      const response = await apiFetch("/api/trading/provider-test", { timeoutMs: 25000 });
      if (response.ok) {
        setMessage(`Provider test passed: ${response.tested}`);
      } else {
        setError(response.error || response.message || "Provider test did not pass.");
      }
      await loadTrading();
    } catch (err) {
      setError(err?.message || "Provider test failed.");
    } finally {
      setTestingProvider(false);
    }
  };

  const checkAlpacaEnv = async () => {
    try {
      setCheckingAlpacaEnv(true);
      setError("");
      setMessage("");
      setAlpacaNotice("");
      const response = await apiFetch("/api/trading/env-diagnostics");
      setEnvDiagnostics(response);
      if (response?.apiMissing?.length) {
        setAlpacaNotice(`Backend runtime is missing: ${response.apiMissing.join(", ")}.`);
      } else if (!response?.runtime?.ALPACA_BROKER_ALLOW_ORDERS) {
        setAlpacaNotice("Backend sees Alpaca API keys. Broker order submission is still locked.");
      } else {
        setAlpacaNotice("Backend sees Alpaca API keys and broker order submission is unlocked.");
      }
    } catch (err) {
      setEnvDiagnostics(null);
      setAlpacaNotice(err?.message || "Could not check backend Alpaca env.");
    } finally {
      setCheckingAlpacaEnv(false);
    }
  };

  const loadAlpacaAccounts = async () => {
    try {
      setLoadingAlpacaAccounts(true);
      setAlpacaNotice("");
      setMessage("");
      const response = await apiFetch("/api/trading/alpaca/accounts?limit=25", { timeoutMs: 25000 });
      if (response.ok) {
        setAlpacaAccounts(Array.isArray(response.accounts) ? response.accounts : []);
        setMessage(`Loaded ${response.count || 0} Alpaca account${response.count === 1 ? "" : "s"}.`);
      } else {
        setAlpacaAccounts([]);
        setAlpacaNotice(response.message || "Alpaca account discovery is not configured.");
      }
    } catch (err) {
      setAlpacaNotice(alpacaAccountErrorMessage(err));
      setAlpacaAccounts([]);
    } finally {
      setLoadingAlpacaAccounts(false);
    }
  };

  const createSandboxAccount = async () => {
    try {
      setCreatingSandboxAccount(true);
      setError("");
      setMessage("");
      setAlpacaNotice("");
      const response = await apiFetch("/api/trading/alpaca/sandbox-account", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        timeoutMs: 30000,
      });
      if (response.ok) {
        setSelectedAlpacaAccount(response.selected || { selectedAccountId: response.selectedAccountId });
        await loadTrading();
        await loadAlpacaAccounts();
        setMessage(response.message || "Created sandbox Alpaca account.");
      } else {
        setAlpacaNotice(response.message || "Could not create sandbox Alpaca account.");
      }
    } catch (err) {
      setAlpacaNotice(err?.message || "Could not create sandbox Alpaca account.");
    } finally {
      setCreatingSandboxAccount(false);
    }
  };

  const fundSandboxAccount = async () => {
    try {
      setFundingSandboxAccount(true);
      setError("");
      setMessage("");
      setAlpacaNotice("");
      const response = await apiFetch("/api/trading/alpaca/sandbox-funding", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ amount: 1000 }),
        timeoutMs: 30000,
      });
      if (response.ok) {
        await loadTrading();
        setMessage(response.message || "Requested sandbox account funding.");
      } else {
        setAlpacaNotice(response.message || "Could not fund sandbox Alpaca account.");
      }
    } catch (err) {
      setAlpacaNotice(err?.message || "Could not fund sandbox Alpaca account.");
    } finally {
      setFundingSandboxAccount(false);
    }
  };

  const selectAlpacaAccount = async (accountId) => {
    try {
      setError("");
      setMessage("");
      const response = await apiFetch("/api/trading/alpaca/selected-account", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ accountId }),
        timeoutMs: 25000,
      });
      if (response.ok) {
        setSelectedAlpacaAccount(response);
        setMessage(`Selected Alpaca account ${response.selectedAccountId}.`);
        await loadTrading();
      } else {
        setError(response.message || "Could not select Alpaca account.");
      }
    } catch (err) {
      setError(err?.message || "Could not select Alpaca account.");
    }
  };

  const clearAlpacaSelection = async () => {
    try {
      setError("");
      setMessage("");
      const response = await apiFetch("/api/trading/alpaca/selected-account", { method: "DELETE" });
      setSelectedAlpacaAccount(response);
      setMessage("Cleared selected Alpaca account.");
      await loadTrading();
    } catch (err) {
      setError(err?.message || "Could not clear Alpaca account selection.");
    }
  };

  const orderSubmissionEnabled =
    status?.orderSubmissionEnabled ?? (!status || status.provider === "paper" ? Boolean(status?.enabled && status?.supportedMode) : false);
  const disabled = !orderSubmissionEnabled || submitting;
  const selectedAlpacaId = selectedAlpacaAccount?.selectedAccountId || "";
  const brokerIsSandbox = status?.brokerIsSandbox !== false;
  const pendingSubmitNotional = pendingSubmit
    ? Number(pendingSubmit.qty) * Number(pendingSubmit.type === "limit" ? pendingSubmit.limitPrice : pendingSubmit.estimatedPrice)
    : 0;
  const submitLabel =
    status?.provider === "alpaca_broker"
      ? status?.orderSubmissionLocked
        ? "Broker Orders Locked"
        : status?.liveTradingAvailable
          ? "Submit Alpaca Live Order"
          : "Submit Alpaca Broker Order"
      : "Submit Paper Order";
  const backendEnvKeys = envDiagnostics?.envFiles?.backend?.keys || {};
  const runtimeEnv = envDiagnostics?.runtime || {};
  const fileKeyText = (key) => {
    const entry = backendEnvKeys[key];
    if (!entry?.defined) return "not defined";
    if (entry.blank) return "blank";
    return `present (${entry.length})`;
  };
  const runtimeKeyText = (key) => {
    const entry = runtimeEnv[key];
    if (!entry) return "missing";
    return entry.present ? `present (${entry.length})` : "missing";
  };
  const readinessChecks = Array.isArray(readiness?.checks) ? readiness.checks : [];

  return (
    <div className="trading-page">
      <div className="trading-shell">
        <div className="trading-header">
          <div>
            <div className="trading-kicker">Execution Layer</div>
            <h2>Trading</h2>
            <p>
              Provider-based order entry separated from scanner signals. Paper is the default;
              Alpaca Broker routing can be enabled from backend config.
            </p>
          </div>
          <div className="trading-badges">
            <span>
              Provider <strong>{status?.provider || "paper"}</strong>
            </span>
            <span>
              Status <strong>{status?.enabled ? "Enabled" : "Disabled"}</strong>
            </span>
            <span>
              Env <strong>{status?.brokerEnvironment || "paper"}</strong>
            </span>
            <button type="button" onClick={loadTrading} disabled={loading}>
              {loading ? "Refreshing" : "Refresh"}
            </button>
            <button type="button" onClick={testProvider} disabled={testingProvider}>
              {testingProvider ? "Testing" : "Test Provider"}
            </button>
          </div>
        </div>

        {status?.message && <div className={status.enabled ? "trading-note" : "trading-warning"}>{status.message}</div>}
        {message && <div className="trading-note">{message}</div>}
        {error && <div className="trading-error">{error}</div>}

        {readiness && (
          <section className="trading-panel trading-readiness-panel">
            <div className="trading-panel-header trading-panel-header--actions">
              <div>
                <h3>Execution Readiness</h3>
                <p>{readiness.nextAction}</p>
              </div>
              <div className="trading-readiness-flags">
                <span className={readiness.alpacaDiscoveryReady ? "ready" : "blocked"}>Discovery</span>
                <span className={readiness.alpacaRoutingReady ? "ready" : "pending"}>Routing</span>
                <span className={readiness.orderSubmissionReady ? "ready" : "locked"}>Orders</span>
              </div>
            </div>
            <div className="trading-readiness-grid">
              {readinessChecks.map((check) => (
                <div key={check.key} className={`trading-readiness-item trading-readiness-item--${check.state}`}>
                  <span>{check.label}</span>
                  <strong>{check.state}</strong>
                  <p>{check.message}</p>
                </div>
              ))}
            </div>
          </section>
        )}

        <div className="trading-summary-grid">
          <div className="trading-summary-card">
            <span>Cash</span>
            <strong>{money(account?.cash)}</strong>
          </div>
          <div className="trading-summary-card">
            <span>Buying Power</span>
            <strong>{money(account?.buyingPower)}</strong>
          </div>
          <div className="trading-summary-card">
            <span>Portfolio Value</span>
            <strong>{money(account?.portfolioValue)}</strong>
          </div>
          <div className="trading-summary-card">
            <span>Open Orders</span>
            <strong>{account?.openOrderCount ?? 0}</strong>
          </div>
        </div>

        {marketClock && (
          <div className={marketClock.isOpen ? "trading-note" : "trading-warning"}>
            Market clock: {marketClock.isOpen ? "open" : "closed"}
            {marketClock.nextOpen ? ` / next open ${new Date(marketClock.nextOpen).toLocaleString()}` : ""}
            {marketClock.nextClose ? ` / next close ${new Date(marketClock.nextClose).toLocaleString()}` : ""}
          </div>
        )}

        <section className="trading-panel">
          <div className="trading-panel-header trading-panel-header--actions">
            <div>
              <h3>Alpaca Account Discovery</h3>
              <p>
                Read-only broker account lookup for selecting the account ID used by order routing.
                {selectedAlpacaId ? ` Selected: ${selectedAlpacaId}` : " No account selected."}
              </p>
            </div>
            <div className="trading-panel-actions">
              {selectedAlpacaId && (
                <button type="button" className="trading-secondary-btn" onClick={clearAlpacaSelection}>
                  Clear Selection
                </button>
              )}
              <button type="button" className="trading-secondary-btn" onClick={checkAlpacaEnv} disabled={checkingAlpacaEnv}>
                {checkingAlpacaEnv ? "Checking" : "Check Env"}
              </button>
              {brokerIsSandbox && (
                <button
                  type="button"
                  className="trading-secondary-btn"
                  onClick={createSandboxAccount}
                  disabled={creatingSandboxAccount}
                >
                  {creatingSandboxAccount ? "Creating" : "Create Sandbox Account"}
                </button>
              )}
              {brokerIsSandbox && (
                <button
                  type="button"
                  className="trading-secondary-btn"
                  onClick={fundSandboxAccount}
                  disabled={fundingSandboxAccount || !selectedAlpacaId}
                >
                  {fundingSandboxAccount ? "Funding" : "Fund Sandbox"}
                </button>
              )}
              <button type="button" className="trading-secondary-btn" onClick={loadAlpacaAccounts} disabled={loadingAlpacaAccounts}>
                {loadingAlpacaAccounts ? "Loading" : "Load Accounts"}
              </button>
            </div>
          </div>
          <div className="trading-table-wrap">
            {alpacaNotice && <div className="trading-panel-notice">{alpacaNotice}</div>}
            {envDiagnostics && (
              <div className="trading-env-grid">
                <div>
                  <span>backend/.env</span>
                  <strong>{envDiagnostics.envFiles?.backend?.exists ? "found" : "missing"}</strong>
                </div>
                <div>
                  <span>Provider</span>
                  <strong>{runtimeEnv.TRADING_PROVIDER || "-"}</strong>
                </div>
                <div>
                  <span>Broker Enabled</span>
                  <strong>
                    file {fileKeyText("ALPACA_BROKER_ENABLED")} / runtime {runtimeEnv.ALPACA_BROKER_ENABLED ? "true" : "false"}
                  </strong>
                </div>
                <div>
                  <span>API Key</span>
                  <strong>
                    file {fileKeyText("ALPACA_BROKER_API_KEY")} / runtime {runtimeKeyText("ALPACA_BROKER_API_KEY")}
                  </strong>
                </div>
                <div>
                  <span>API Secret</span>
                  <strong>
                    file {fileKeyText("ALPACA_BROKER_API_SECRET")} / runtime {runtimeKeyText("ALPACA_BROKER_API_SECRET")}
                  </strong>
                </div>
                <div>
                  <span>Account ID</span>
                  <strong>
                    file {fileKeyText("ALPACA_BROKER_ACCOUNT_ID")} / runtime {runtimeKeyText("ALPACA_BROKER_ACCOUNT_ID")}
                  </strong>
                </div>
              </div>
            )}
            <table className="trading-table">
              <thead>
                <tr>
                  <th>Account ID</th>
                  <th>Account #</th>
                  <th>Status</th>
                  <th>Crypto</th>
                  <th>Created</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {alpacaAccounts.length === 0 ? (
                  <tr>
                    <td colSpan="6">No Alpaca accounts loaded.</td>
                  </tr>
                ) : (
                  alpacaAccounts.map((row) => (
                    <tr key={row.id || row.accountNumber}>
                      <td className="trading-mono-cell">{row.id || "-"}</td>
                      <td>{row.accountNumber || "-"}</td>
                      <td>{row.status || "-"}</td>
                      <td>{row.cryptoStatus || "-"}</td>
                      <td>{row.createdAt ? new Date(row.createdAt).toLocaleString() : "-"}</td>
                      <td>
                        {row.id === selectedAlpacaId ? (
                          <span className="trading-selected-pill">Selected</span>
                        ) : (
                          <button type="button" className="trading-link-btn" onClick={() => selectAlpacaAccount(row.id)}>
                            Use
                          </button>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>

        <div className="trading-grid">
          <section className="trading-panel">
            <div className="trading-panel-header">
              <div>
                <h3>Trade Ticket</h3>
                <p>Manual paper order entry with explicit review fields.</p>
              </div>
            </div>
            <form className="trading-ticket" onSubmit={submitOrder}>
              <label>
                <span>Symbol</span>
                <input value={ticket.symbol} onChange={(e) => updateTicket("symbol", e.target.value)} />
              </label>
              <label>
                <span>Side</span>
                <select value={ticket.side} onChange={(e) => updateTicket("side", e.target.value)}>
                  <option value="buy">Buy</option>
                  <option value="sell">Sell</option>
                </select>
              </label>
              <label>
                <span>Type</span>
                <select value={ticket.type} onChange={(e) => updateTicket("type", e.target.value)}>
                  <option value="market">Market</option>
                  <option value="limit">Limit</option>
                </select>
              </label>
              <label>
                <span>Quantity</span>
                <input value={ticket.qty} onChange={(e) => updateTicket("qty", e.target.value)} inputMode="decimal" />
              </label>
              {ticket.type === "limit" && (
                <label>
                  <span>Limit Price</span>
                  <input
                    value={ticket.limitPrice}
                    onChange={(e) => updateTicket("limitPrice", e.target.value)}
                    inputMode="decimal"
                  />
                </label>
              )}
              <label>
                <span>Estimated Price</span>
                <input
                  value={ticket.estimatedPrice}
                  onChange={(e) => updateTicket("estimatedPrice", e.target.value)}
                  inputMode="decimal"
                />
              </label>
              <label>
                <span>Time In Force</span>
                <select value={ticket.timeInForce} onChange={(e) => updateTicket("timeInForce", e.target.value)}>
                  <option value="day">Day</option>
                  <option value="gtc">GTC</option>
                  <option value="ioc">IOC</option>
                </select>
              </label>
              <div className="trading-review">
                <span>Estimated Notional</span>
                <strong>{money(estimatedNotional)}</strong>
              </div>
              {status?.riskControls && (
                <div className="trading-review">
                  <span>Max Notional</span>
                  <strong>{money(status.riskControls.maxOrderNotional)}</strong>
                </div>
              )}
              {orderPreview && (
                <div className="trading-preview-box">
                  <div>
                    <span>Preview</span>
                    <strong>
                      {orderPreview.side} {qty(orderPreview.qty)} {orderPreview.symbol}
                    </strong>
                  </div>
                  <div>
                    <span>Route</span>
                    <strong>{status?.provider || "paper"}</strong>
                  </div>
                  <div>
                    <span>Notional</span>
                    <strong>{money(orderPreview.estimatedNotional)}</strong>
                  </div>
                </div>
              )}
              <div className="trading-ticket-actions">
                <button type="button" className="trading-secondary-action-btn" onClick={previewOrder} disabled={previewingOrder}>
                  {previewingOrder ? "Previewing" : "Preview Order"}
                </button>
                <button type="submit" disabled={disabled}>
                  {submitting ? "Submitting" : submitLabel}
                </button>
              </div>
            </form>
          </section>

          <section className="trading-panel">
            <div className="trading-panel-header">
              <div>
                <h3>Positions</h3>
                <p>Positions maintained by the selected execution provider.</p>
              </div>
            </div>
            <div className="trading-table-wrap">
              <table className="trading-table">
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Qty</th>
                    <th>Avg</th>
                    <th>Value</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.length === 0 ? (
                    <tr>
                      <td colSpan="4">No paper positions yet.</td>
                    </tr>
                  ) : (
                    positions.map((position) => (
                      <tr key={position.symbol}>
                        <td>{position.symbol}</td>
                        <td>{qty(position.qty)}</td>
                        <td>{money(position.avgPrice)}</td>
                        <td>{money(position.marketValue)}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </div>

        <section className="trading-panel">
          <div className="trading-panel-header trading-panel-header--actions">
            <div>
              <h3>Recent Orders</h3>
              <p>Order history from the selected execution provider.</p>
            </div>
            <button type="button" className="trading-secondary-btn" onClick={loadTrading} disabled={loading}>
              {loading ? "Refreshing" : "Refresh Orders"}
            </button>
          </div>
          <div className="trading-table-wrap">
            <table className="trading-table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Symbol</th>
                  <th>Side</th>
                  <th>Type</th>
                  <th>Qty</th>
                  <th>Status</th>
                  <th>Fill</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {orders.length === 0 ? (
                  <tr>
                    <td colSpan="8">No orders submitted.</td>
                  </tr>
                ) : (
                  orders.map((order) => (
                    <tr key={order.id}>
                      <td>{order.submittedAt ? new Date(order.submittedAt).toLocaleString() : "-"}</td>
                      <td>{order.symbol}</td>
                      <td>{order.side}</td>
                      <td>{order.type}</td>
                      <td>{qty(order.qty)}</td>
                      <td>{order.status}</td>
                      <td>{order.filledAvgPrice ? money(order.filledAvgPrice) : "-"}</td>
                      <td>
                        {["accepted", "pending_new", "partially_filled"].includes(order.status) && (
                          <button type="button" className="trading-link-btn" onClick={() => cancelOrder(order.id)}>
                            Cancel
                          </button>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section className="trading-panel">
          <div className="trading-panel-header trading-panel-header--actions">
            <div>
              <h3>Audit Log</h3>
              <p>Recent preview, submit, and cancel decisions recorded by the backend.</p>
            </div>
            <button type="button" className="trading-secondary-btn" onClick={loadTrading} disabled={loading}>
              {loading ? "Refreshing" : "Refresh Audit"}
            </button>
          </div>
          <div className="trading-table-wrap">
            <table className="trading-table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Action</th>
                  <th>Outcome</th>
                  <th>Symbol</th>
                  <th>Notional</th>
                  <th>Broker Status</th>
                  <th>Error</th>
                </tr>
              </thead>
              <tbody>
                {auditLog.length === 0 ? (
                  <tr>
                    <td colSpan="7">No audit events recorded.</td>
                  </tr>
                ) : (
                  auditLog.map((event) => (
                    <tr key={event.id}>
                      <td>{event.at ? new Date(event.at).toLocaleString() : "-"}</td>
                      <td>{event.action}</td>
                      <td>{event.outcome}</td>
                      <td>{event.symbol || "-"}</td>
                      <td>{money(event.estimatedNotional)}</td>
                      <td>{event.brokerStatus || "-"}</td>
                      <td className="trading-audit-error">{event.error || "-"}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>
      </div>

      {pendingSubmit && (
        <div className="trading-modal-backdrop" role="presentation">
          <div className="trading-confirm-modal" role="dialog" aria-modal="true" aria-labelledby="trading-confirm-title">
            <h3 id="trading-confirm-title">Confirm Order</h3>
            <div className="trading-confirm-grid">
              <div>
                <span>Symbol</span>
                <strong>{pendingSubmit.symbol}</strong>
              </div>
              <div>
                <span>Side</span>
                <strong>{pendingSubmit.side}</strong>
              </div>
              <div>
                <span>Type</span>
                <strong>{pendingSubmit.type}</strong>
              </div>
              <div>
                <span>Qty</span>
                <strong>{qty(pendingSubmit.qty)}</strong>
              </div>
              <div>
                <span>Notional</span>
                <strong>{money(pendingSubmitNotional)}</strong>
              </div>
              <div>
                <span>Route</span>
                <strong>{status?.provider || "paper"}</strong>
              </div>
            </div>
            <div className="trading-ticket-actions">
              <button type="button" className="trading-secondary-action-btn" onClick={() => setPendingSubmit(null)} disabled={submitting}>
                Cancel
              </button>
              <button type="button" className="trading-primary-action-btn" onClick={confirmSubmitOrder} disabled={submitting}>
                {submitting ? "Submitting" : "Confirm Submit"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default TradingPage;
