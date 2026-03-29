const defaultApiBase = typeof window !== "undefined" ? window.location.origin : "http://localhost:5000";
const defaultSocketBase = typeof window !== "undefined" ? (window.location.protocol === "https:" ? "wss://" : "ws://") + window.location.host : "ws://localhost:5000";

const API_BASE = process.env.REACT_APP_API_BASE || defaultApiBase;
const SOCKET_BASE = process.env.REACT_APP_SOCKET_BASE || defaultSocketBase;

const buildApiUrl = (path) => `${API_BASE}${path}`;

const apiFetch = async (path, options = {}) => {
  const response = await fetch(buildApiUrl(path), options);
  if (!response.ok) {
    const text = await response.text();
    const message = text.length && text.startsWith("<") ? `HTML response (${response.status})` : text || `Status ${response.status}`;
    throw new Error(message);
  }
  return response;
};

const exportsObj = {
  API_BASE,
  SOCKET_BASE,
  buildApiUrl,
  apiFetch,
};

export { API_BASE, SOCKET_BASE, buildApiUrl, apiFetch };
export default exportsObj;
