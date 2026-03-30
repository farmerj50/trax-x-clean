const normalizeBaseUrl = (value) => {
  if (!value || typeof value !== "string") return "";
  return value.trim().replace(/\/+$/, "");
};

const getRuntimeConfigBase = (key) => {
  if (typeof window === "undefined") return "";

  let storageValue = "";
  try {
    storageValue = window.localStorage?.getItem(`TRAX_${key}`) || "";
  } catch (error) {
    storageValue = "";
  }

  const runtimeValue =
    window.__TRAX_CONFIG__?.[key] ??
    window[`__TRAX_${key}__`] ??
    document.querySelector(`meta[name="trax-${key.toLowerCase().replace(/_/g, "-")}"]`)?.content ??
    storageValue;

  return normalizeBaseUrl(runtimeValue);
};

const toWebSocketBase = (value) => {
  if (!value) return "";
  return value.replace(/^http:/i, "ws:").replace(/^https:/i, "wss:");
};

const defaultApiBase = (() => {
  const configured =
    normalizeBaseUrl(process.env.REACT_APP_API_BASE) || getRuntimeConfigBase("API_BASE");
  if (configured) return configured;
  if (typeof window === "undefined") return "http://localhost:5000";

  // In CRA local dev, frontend runs at 3000 and backend at 5000.
  if (window.location.hostname === "localhost" && window.location.port === "3000") {
    return "http://localhost:5000";
  }

  return normalizeBaseUrl(window.location.origin);
})();

const defaultSocketBase = (() => {
  const configured =
    normalizeBaseUrl(process.env.REACT_APP_SOCKET_BASE) || getRuntimeConfigBase("SOCKET_BASE");
  if (configured) return configured;
  if (typeof window === "undefined") return "ws://localhost:5000";
  return toWebSocketBase(defaultApiBase || window.location.origin);
})();

const API_BASE = defaultApiBase;
const SOCKET_BASE = defaultSocketBase;

const buildApiUrl = (path) => {
  if (!path.startsWith("/")) path = `/${path}`;
  return `${API_BASE}${path}`;
};

const apiFetch = async (path, options = {}) => {
  const response = await fetch(buildApiUrl(path), options);
  const text = await response.text();
  const contentType = response.headers.get("content-type") || "";
  const trimmed = text.trim();
  const receivedHtml =
    contentType.includes("text/html") ||
    /^<!doctype html/i.test(trimmed) ||
    /^<html[\s>]/i.test(trimmed);

  if (!response.ok) {
    const bodyPreview = receivedHtml ? "[HTML document returned]" : trimmed.slice(0, 300);
    throw new Error(`HTTP ${response.status} ${response.statusText} for ${path}: ${bodyPreview}`);
  }

  if (receivedHtml) {
    throw new Error(
      `Expected JSON from ${buildApiUrl(path)} but received HTML. Configure REACT_APP_API_BASE/REACT_APP_SOCKET_BASE for production.`
    );
  }

  try {
    return JSON.parse(text);
  } catch (err) {
    throw new Error(`Invalid JSON response from ${buildApiUrl(path)}: ${trimmed.slice(0, 300)}`);
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
