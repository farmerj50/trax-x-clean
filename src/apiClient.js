const normalizeBaseUrl = (value) => {
  if (!value || typeof value !== "string") return "";
  return value.trim().replace(/\/+$/, "");
};

const isLocalHostname = (hostname) => {
  const normalized = String(hostname || "").toLowerCase();
  return normalized === "localhost" || normalized === "127.0.0.1" || normalized === "::1";
};

const getStoredRuntimeConfigBase = (key) => {
  if (typeof window === "undefined") return "";

  let storageValue = "";
  try {
    storageValue = window.localStorage?.getItem(`TRAX_${key}`) || "";
  } catch (error) {
    storageValue = "";
  }

  const normalized = normalizeBaseUrl(storageValue);
  if (!normalized) return "";

  // In local development, stale persisted remote overrides are a common cause
  // of "scan won't populate" issues even though the backend on :5000 is healthy.
  if (isLocalHostname(window.location.hostname)) {
    try {
      const parsed = new URL(normalized);
      if (!isLocalHostname(parsed.hostname)) {
        return "";
      }
    } catch (error) {
      return "";
    }
  }

  return normalized;
};

const getRuntimeConfigBase = (key) => {
  if (typeof window === "undefined") return "";

  const runtimeValue =
    window.__TRAX_CONFIG__?.[key] ??
    window[`__TRAX_${key}__`] ??
    document.querySelector(`meta[name="trax-${key.toLowerCase().replace(/_/g, "-")}"]`)?.content ??
    getStoredRuntimeConfigBase(key);

  return normalizeBaseUrl(runtimeValue);
};

const toWebSocketBase = (value) => {
  if (!value) return "";
  return value.replace(/^http:/i, "ws:").replace(/^https:/i, "wss:");
};

const normalizeLocalDevOverride = (value, fallback) => {
  if (!value || typeof window === "undefined" || !isLocalHostname(window.location.hostname)) {
    return value;
  }

  try {
    const parsed = new URL(value);
    if (isLocalHostname(parsed.hostname) && parsed.port !== "5000") {
      return fallback;
    }
  } catch (error) {
    return value;
  }

  return value;
};

const getKnownProductionApiBase = () => {
  if (typeof window === "undefined") return "";

  const host = String(window.location.host || "").toLowerCase();
  const knownHosts = {
    "trax-x-clean-production.up.railway.app": "https://keen-hope-production-4a15.up.railway.app",
  };

  return knownHosts[host] || "";
};

const defaultApiBase = (() => {
  const configured = normalizeLocalDevOverride(
    normalizeBaseUrl(process.env.REACT_APP_API_BASE) || getRuntimeConfigBase("API_BASE"),
    "http://localhost:5000"
  );
  if (configured) return configured;
  const knownProductionBase = getKnownProductionApiBase();
  if (knownProductionBase) return knownProductionBase;
  if (typeof window === "undefined") return "http://localhost:5000";

  // In local dev, the frontend may move to 3001/3002 if 3000 is occupied.
  // Keep the API pinned to the backend on 5000 unless explicitly configured.
  if (isLocalHostname(window.location.hostname) && window.location.port !== "5000") {
    return "http://localhost:5000";
  }

  return normalizeBaseUrl(window.location.origin);
})();

const defaultSocketBase = (() => {
  const configured = normalizeLocalDevOverride(
    normalizeBaseUrl(process.env.REACT_APP_SOCKET_BASE) || getRuntimeConfigBase("SOCKET_BASE"),
    "ws://localhost:5000"
  );
  if (configured) return configured;
  const knownProductionBase = getKnownProductionApiBase();
  if (knownProductionBase) return knownProductionBase;
  if (typeof window === "undefined") return "ws://localhost:5000";
  if (isLocalHostname(window.location.hostname) && window.location.port !== "5000") {
    return "ws://localhost:5000";
  }
  return toWebSocketBase(defaultApiBase || window.location.origin);
})();

const API_BASE = defaultApiBase;
const SOCKET_BASE = defaultSocketBase;
const AUTH_EXPIRED_EVENT = "trax-x-auth-expired";

const buildApiUrl = (path) => {
  if (!path.startsWith("/")) path = `/${path}`;
  if (
    process.env.NODE_ENV === "development" &&
    typeof window !== "undefined" &&
    isLocalHostname(window.location.hostname) &&
    path.startsWith("/api/")
  ) {
    return path;
  }
  return `${API_BASE}${path}`;
};

const mergeAbortSignals = (signals = []) => {
  const validSignals = signals.filter(Boolean);
  if (validSignals.length === 0) return undefined;
  if (validSignals.length === 1) return validSignals[0];

  const controller = new AbortController();
  const abort = () => controller.abort();

  validSignals.forEach((signal) => {
    if (signal.aborted) {
      abort();
    } else {
      signal.addEventListener("abort", abort, { once: true });
    }
  });

  return controller.signal;
};

const apiFetch = async (path, options = {}) => {
  const { timeoutMs = 15000, signal, ...fetchOptions } = options;
  const timeoutController = new AbortController();
  const timeoutId = setTimeout(() => timeoutController.abort(), timeoutMs);

  let response;
  try {
    response = await fetch(buildApiUrl(path), {
      credentials: "include",
      ...fetchOptions,
      signal: mergeAbortSignals([signal, timeoutController.signal]),
    });
  } catch (error) {
    if (error?.name === "AbortError") {
      throw new Error(`Request timed out after ${timeoutMs}ms for ${path}`);
    }
    throw error;
  } finally {
    clearTimeout(timeoutId);
  }

  const text = await response.text();
  const contentType = response.headers.get("content-type") || "";
  const trimmed = text.trim();
  const receivedHtml =
    contentType.includes("text/html") ||
    /^<!doctype html/i.test(trimmed) ||
    /^<html[\s>]/i.test(trimmed);

  if (!response.ok) {
    const bodyPreview = receivedHtml ? "[HTML document returned]" : trimmed.slice(0, 300);
    if (response.status === 401 && typeof window !== "undefined" && !String(path || "").startsWith("/api/auth/")) {
      window.dispatchEvent(
        new CustomEvent(AUTH_EXPIRED_EVENT, {
          detail: { path, status: response.status },
        })
      );
    }
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
  AUTH_EXPIRED_EVENT,
  API_BASE,
  SOCKET_BASE,
  buildApiUrl,
  apiFetch,
};

export { AUTH_EXPIRED_EVENT, API_BASE, SOCKET_BASE, buildApiUrl, apiFetch };
export default exportsObj;
