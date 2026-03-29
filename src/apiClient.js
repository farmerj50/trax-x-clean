const API_BASE = process.env.REACT_APP_API_BASE || "http://localhost:5000";
const SOCKET_BASE = process.env.REACT_APP_SOCKET_BASE || API_BASE;

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
