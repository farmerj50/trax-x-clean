const defaultApiBase = (() => {
  if (process.env.REACT_APP_API_BASE) return process.env.REACT_APP_API_BASE;
  if (typeof window === "undefined") return "http://localhost:5000";

  // In CRA local dev, frontend runs at 3000 and backend at 5000
  if (window.location.hostname === "localhost" && window.location.port === "3000") {
    return "http://localhost:5000";
  }

  return window.location.origin;
})();

const defaultSocketBase = typeof window !== "undefined" ? (window.location.protocol === "https:" ? "wss://" : "ws://") + window.location.host : "ws://localhost:5000";

const API_BASE = process.env.REACT_APP_API_BASE || defaultApiBase;
const SOCKET_BASE = process.env.REACT_APP_SOCKET_BASE || defaultSocketBase;

const buildApiUrl = (path) => {
  if (!path.startsWith("/")) path = `/${path}`;
  return `${API_BASE}${path}`;
};

const apiFetch = async (path, options = {}) => {
  const response = await fetch(buildApiUrl(path), options);
  const text = await response.text();

  if (!response.ok) {
    throw new Error(`HTTP ${response.status} ${response.statusText} for ${path}: ${text.slice(0, 300)}`);
  }

  try {
    return JSON.parse(text);
  } catch (err) {
    throw new Error(`Invalid JSON response from ${buildApiUrl(path)}: ${text.slice(0, 300)}`);
  }
};

const exportsObj = {
  API_BASE,
  SOCKET_BASE,
  buildApiUrl,
  apiFetch,
};

export { API_BASE, SOCKET_BASE, buildApiUrl, apiFetch };
export default exportsObj;
