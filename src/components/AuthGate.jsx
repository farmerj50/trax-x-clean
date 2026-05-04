import React, { useEffect, useState } from "react";
import { AUTH_EXPIRED_EVENT, apiFetch } from "../apiClient";
import "./AuthGate.css";

const emptyForm = {
  username: "",
  password: "",
  confirmPassword: "",
  currentPassword: "",
  newPassword: "",
  confirmNewPassword: "",
};

const AuthGate = ({ children }) => {
  const [loading, setLoading] = useState(true);
  const [auth, setAuth] = useState({ authenticated: false, setupRequired: false, user: null });
  const [form, setForm] = useState(emptyForm);
  const [mode, setMode] = useState("login");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const loadSession = async () => {
    try {
      setLoading(true);
      setError("");
      const response = await apiFetch("/api/auth/session", { timeoutMs: 10000 });
      setAuth(response);
      setMode(response.setupRequired ? "setup" : "login");
    } catch (err) {
      setAuth({ authenticated: false, setupRequired: false, user: null });
      setError(err?.message || "Could not check login session.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadSession();
  }, []);

  useEffect(() => {
    const handleAuthExpired = () => {
      setAuth({ authenticated: false, setupRequired: false, user: null });
      setForm(emptyForm);
      setMode("login");
      setMessage("");
      setError("Session expired. Sign in again.");
    };

    window.addEventListener(AUTH_EXPIRED_EVENT, handleAuthExpired);
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, handleAuthExpired);
  }, []);

  const updateForm = (key, value) => {
    setForm((current) => ({ ...current, [key]: value }));
    setError("");
    setMessage("");
  };

  const submitLogin = async (event) => {
    event.preventDefault();
    try {
      setSubmitting(true);
      setError("");
      const response = await apiFetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: form.username, password: form.password }),
      });
      setAuth(response);
      setForm(emptyForm);
    } catch (err) {
      setError(err?.message || "Login failed.");
    } finally {
      setSubmitting(false);
    }
  };

  const submitSetup = async (event) => {
    event.preventDefault();
    if (form.password !== form.confirmPassword) {
      setError("Passwords do not match.");
      return;
    }
    try {
      setSubmitting(true);
      setError("");
      const response = await apiFetch("/api/auth/setup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: form.username, password: form.password }),
      });
      setAuth(response);
      setForm(emptyForm);
    } catch (err) {
      setError(err?.message || "Could not create login.");
    } finally {
      setSubmitting(false);
    }
  };

  const submitPasswordChange = async (event) => {
    event.preventDefault();
    if (form.newPassword !== form.confirmNewPassword) {
      setError("New passwords do not match.");
      return;
    }
    try {
      setSubmitting(true);
      setError("");
      const response = await apiFetch("/api/auth/change-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          currentPassword: form.currentPassword,
          newPassword: form.newPassword,
        }),
      });
      setAuth((current) => ({ ...current, user: response.user || current.user }));
      setForm(emptyForm);
      setMode("app");
      setMessage("Password changed.");
    } catch (err) {
      setError(err?.message || "Could not change password.");
    } finally {
      setSubmitting(false);
    }
  };

  const logout = async () => {
    try {
      await apiFetch("/api/auth/logout", { method: "POST" });
    } catch (err) {
      // Clear local state even if the network request fails.
    }
    setAuth({ authenticated: false, setupRequired: false, user: null });
    setForm(emptyForm);
    setMode("login");
  };

  if (loading) {
    return (
      <main className="auth-page">
        <section className="auth-card">
          <div className="auth-kicker">Trax-X</div>
          <h1>Checking Session</h1>
        </section>
      </main>
    );
  }

  if (!auth.authenticated) {
    const isSetup = auth.setupRequired || mode === "setup";
    return (
      <main className="auth-page">
        <section className="auth-card">
          <div className="auth-kicker">Trax-X</div>
          <h1>{isSetup ? "Create Admin Login" : "Sign In"}</h1>
          <form className="auth-form" onSubmit={isSetup ? submitSetup : submitLogin}>
            <label>
              <span>Username</span>
              <input
                autoComplete="username"
                value={form.username}
                onChange={(event) => updateForm("username", event.target.value)}
              />
            </label>
            <label>
              <span>Password</span>
              <input
                type="password"
                autoComplete={isSetup ? "new-password" : "current-password"}
                value={form.password}
                onChange={(event) => updateForm("password", event.target.value)}
              />
            </label>
            {isSetup && (
              <label>
                <span>Confirm Password</span>
                <input
                  type="password"
                  autoComplete="new-password"
                  value={form.confirmPassword}
                  onChange={(event) => updateForm("confirmPassword", event.target.value)}
                />
              </label>
            )}
            {error && <div className="auth-error">{error}</div>}
            <button type="submit" disabled={submitting}>
              {submitting ? "Working" : isSetup ? "Create Login" : "Login"}
            </button>
          </form>
        </section>
      </main>
    );
  }

  return (
    <>
      {children({
        user: auth.user,
        logout,
        changePassword: () => {
          setMode("change-password");
          setError("");
          setMessage("");
        },
      })}
      {message && <div className="auth-toast">{message}</div>}
      {mode === "change-password" && (
        <div className="auth-modal-backdrop" role="presentation">
          <section className="auth-card auth-modal" role="dialog" aria-modal="true" aria-labelledby="change-password-title">
            <h1 id="change-password-title">Change Password</h1>
            <form className="auth-form" onSubmit={submitPasswordChange}>
              <label>
                <span>Current Password</span>
                <input
                  type="password"
                  autoComplete="current-password"
                  value={form.currentPassword}
                  onChange={(event) => updateForm("currentPassword", event.target.value)}
                />
              </label>
              <label>
                <span>New Password</span>
                <input
                  type="password"
                  autoComplete="new-password"
                  value={form.newPassword}
                  onChange={(event) => updateForm("newPassword", event.target.value)}
                />
              </label>
              <label>
                <span>Confirm New Password</span>
                <input
                  type="password"
                  autoComplete="new-password"
                  value={form.confirmNewPassword}
                  onChange={(event) => updateForm("confirmNewPassword", event.target.value)}
                />
              </label>
              {error && <div className="auth-error">{error}</div>}
              <div className="auth-actions">
                <button type="button" className="auth-secondary-btn" onClick={() => setMode("app")} disabled={submitting}>
                  Cancel
                </button>
                <button type="submit" disabled={submitting}>
                  {submitting ? "Saving" : "Save Password"}
                </button>
              </div>
            </form>
          </section>
        </div>
      )}
    </>
  );
};

export default AuthGate;
