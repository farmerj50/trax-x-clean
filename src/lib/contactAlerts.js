import { apiFetch } from "../apiClient";

const CONTACT_ALERTS_STORAGE_KEY = "traxContactAlerts";

const loadStoredAlertContact = () => {
  if (typeof window === "undefined") {
    return {
      name: "",
      email: "",
      phone: "",
      channels: { email: true, sms: false },
    };
  }

  try {
    const raw = window.localStorage.getItem(CONTACT_ALERTS_STORAGE_KEY);
    const parsed = JSON.parse(raw || "{}");
    return {
      name: String(parsed?.name || ""),
      email: String(parsed?.email || ""),
      phone: String(parsed?.phone || ""),
      channels: {
        email: Boolean(parsed?.channels?.email ?? true),
        sms: Boolean(parsed?.channels?.sms ?? false),
      },
    };
  } catch (error) {
    return {
      name: "",
      email: "",
      phone: "",
      channels: { email: true, sms: false },
    };
  }
};

const storeAlertContact = (contact) => {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(CONTACT_ALERTS_STORAGE_KEY, JSON.stringify(contact));
  } catch (error) {
    // ignore storage failures
  }
};

const submitAlertContact = async (payload) => {
  const response = await apiFetch("/api/alerts/contact", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    timeoutMs: 20000,
  });
  return response;
};

export { CONTACT_ALERTS_STORAGE_KEY, loadStoredAlertContact, storeAlertContact, submitAlertContact };
