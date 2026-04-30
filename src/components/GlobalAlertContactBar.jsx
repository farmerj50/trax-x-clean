import React, { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { loadStoredAlertContact, storeAlertContact, submitAlertContact } from "../lib/contactAlerts";
import "./GlobalAlertContactBar.css";

const initialState = loadStoredAlertContact();

const GlobalAlertContactBar = () => {
  const location = useLocation();
  const [form, setForm] = useState(initialState);
  const [status, setStatus] = useState({ tone: "", message: "" });
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    storeAlertContact(form);
  }, [form]);

  const updateField = (key, value) => {
    setForm((current) => ({ ...current, [key]: value }));
  };

  const updateChannel = (key, value) => {
    setForm((current) => ({
      ...current,
      channels: {
        ...current.channels,
        [key]: value,
      },
    }));
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setSubmitting(true);
    setStatus({ tone: "", message: "" });

    try {
      const payload = {
        ...form,
        page: location.pathname || "/",
        eventType: "page_alert_subscription",
        message: `User enabled contact alerts from ${location.pathname || "/"}`,
      };
      const data = await submitAlertContact(payload);
      const emailState = String(data?.delivery?.email?.status || "skipped");
      const smsState = String(data?.delivery?.sms?.status || "skipped");
      setStatus({
        tone: "success",
        message: `Saved. Email: ${emailState}. SMS: ${smsState}.`,
      });
    } catch (error) {
      setStatus({
        tone: "error",
        message: String(error?.message || "Failed to save alert contact."),
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="global-alert-bar">
      <div className="global-alert-bar__inner">
        <div className="global-alert-bar__copy">
          <div className="global-alert-bar__eyebrow">Cross-Page Alerts</div>
          <h3>Save one email or phone number for alerts on every page</h3>
          <p>
            This saves your contact details once and tags the current route so any page can reuse the same alert path.
          </p>
        </div>

        <form className="global-alert-bar__form" onSubmit={handleSubmit}>
          <input
            className="global-alert-bar__input"
            type="text"
            placeholder="Name"
            value={form.name}
            onChange={(event) => updateField("name", event.target.value)}
          />
          <input
            className="global-alert-bar__input"
            type="email"
            placeholder="Email address"
            value={form.email}
            onChange={(event) => updateField("email", event.target.value)}
          />
          <input
            className="global-alert-bar__input"
            type="tel"
            placeholder="Phone number"
            value={form.phone}
            onChange={(event) => updateField("phone", event.target.value)}
          />
          <label className="global-alert-bar__check">
            <input
              type="checkbox"
              checked={Boolean(form.channels.email)}
              onChange={(event) => updateChannel("email", event.target.checked)}
            />
            <span>Email</span>
          </label>
          <label className="global-alert-bar__check">
            <input
              type="checkbox"
              checked={Boolean(form.channels.sms)}
              onChange={(event) => updateChannel("sms", event.target.checked)}
            />
            <span>SMS</span>
          </label>
          <button className="global-alert-bar__button" type="submit" disabled={submitting}>
            {submitting ? "Saving..." : "Save Alerts"}
          </button>
        </form>

        {status.message ? (
          <div className={`global-alert-bar__status global-alert-bar__status--${status.tone || "neutral"}`}>
            {status.message}
          </div>
        ) : null}
      </div>
    </section>
  );
};

export default GlobalAlertContactBar;
