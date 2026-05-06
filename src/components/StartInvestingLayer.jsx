import React, { useEffect, useState } from "react";
import { apiFetch } from "../apiClient";
import "./StartInvestingLayer.css";

const accountOptions = [
  {
    id: "personal",
    label: "Personal",
    icon: "P",
    description: "Invest and trade as an individual.",
  },
  {
    id: "business",
    label: "Business",
    icon: "B",
    description: "Manage your business finances and investments.",
  },
  {
    id: "corporate",
    label: "Corporate",
    icon: "C",
    description: "Advanced solutions for companies and teams.",
  },
];

const fundingOptions = [
  { id: "starter", label: "$500", description: "Starter allocation" },
  { id: "growth", label: "$2,500", description: "Growth allocation" },
  { id: "active", label: "$10,000", description: "Active trading allocation" },
];

const emptyAccountForm = {
  username: "",
  password: "",
  confirmPassword: "",
};

const StartInvestingLayer = ({ initialAccount = "", onClose, onComplete = onClose }) => {
  const [step, setStep] = useState(1);
  const [selectedAccount, setSelectedAccount] = useState(initialAccount);
  const [selectedFunding, setSelectedFunding] = useState("");
  const [accountForm, setAccountForm] = useState(emptyAccountForm);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const handleKeyDown = (event) => {
      if (event.key === "Escape") {
        onClose();
      }
    };

    window.addEventListener("keydown", handleKeyDown);

    return () => {
      document.body.style.overflow = originalOverflow;
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [onClose]);

  const updateAccountForm = (key, value) => {
    setAccountForm((current) => ({ ...current, [key]: value }));
    setError("");
  };

  const submitCreateAccount = async () => {
    if (accountForm.password !== accountForm.confirmPassword) {
      setError("Passwords do not match.");
      return;
    }

    try {
      setSubmitting(true);
      setError("");
      const response = await apiFetch("/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: accountForm.username,
          password: accountForm.password,
          accountType: selectedAccount,
          fundingAmount: selectedFunding,
        }),
      });
      onComplete({
        accountType: selectedAccount,
        fundingAmount: selectedFunding,
        user: response.user,
      });
    } catch (err) {
      const message = String(err?.message || "");
      setError(
        message === "Failed to fetch"
          ? "Could not reach the backend. Start or restart the backend on port 5000, then try again."
          : message.includes("HTTP 404") && message.includes("/api/auth/register")
            ? "The backend is running old code. Restart the backend, then try creating the account again."
          : message || "Could not create account."
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="start-layer-backdrop" role="presentation">
      <aside
        className="start-layer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="start-layer-title"
      >
        <div className="start-layer-topbar">
          <button className="start-back-btn" type="button" onClick={onClose}>
            &lt;- Back
          </button>
          <div className="start-layer-brand" aria-label="TRAX-X">
            <span>T</span>
            TRAX-X
          </div>
        </div>

        <div className="start-stepper" aria-label="Setup progress">
          <div className={`start-step ${step === 1 ? "active" : step > 1 ? "done" : ""}`}>
            <span>1</span>
            <strong>Account Type</strong>
          </div>
          <div className="start-step-line" />
          <div className={`start-step ${step === 2 ? "active" : step > 2 ? "done" : ""}`}>
            <span>2</span>
            <strong>Add Funds</strong>
          </div>
          <div className="start-step-line" />
          <div className={`start-step ${step === 3 ? "active" : ""}`}>
            <span>3</span>
            <strong>Account</strong>
          </div>
        </div>

        {step === 1 ? (
          <section className="start-layer-content">
            <p className="start-layer-kicker">Step 1</p>
            <h2 id="start-layer-title">Choose Your Account</h2>
            <p className="start-layer-copy">
              Select the account type that fits your goals.
            </p>

            <div className="start-account-list">
              {accountOptions.map((account) => (
                <button
                  className={`start-account-option ${
                    selectedAccount === account.id ? "selected" : ""
                  }`}
                  type="button"
                  key={account.id}
                  onClick={() => setSelectedAccount(account.id)}
                >
                  <span className={`start-account-icon ${account.id}`}>
                    {account.icon}
                  </span>
                  <span>
                    <strong>{account.label}</strong>
                    <small>{account.description}</small>
                  </span>
                  <span className="start-radio" aria-hidden="true" />
                </button>
              ))}
            </div>
          </section>
        ) : step === 2 ? (
          <section className="start-layer-content">
            <p className="start-layer-kicker">Step 2</p>
            <h2 id="start-layer-title">Add Funds</h2>
            <p className="start-layer-copy">
              Choose a starting amount for your TRAX-X account.
            </p>

            <div className="start-account-list">
              {fundingOptions.map((option) => (
                <button
                  className={`start-account-option funding ${
                    selectedFunding === option.id ? "selected" : ""
                  }`}
                  type="button"
                  key={option.id}
                  onClick={() => setSelectedFunding(option.id)}
                >
                  <span className="start-account-icon funds">$</span>
                  <span>
                    <strong>{option.label}</strong>
                    <small>{option.description}</small>
                  </span>
                  <span className="start-radio" aria-hidden="true" />
                </button>
              ))}
            </div>
          </section>
        ) : (
          <section className="start-layer-content">
            <p className="start-layer-kicker">Step 3</p>
            <h2 id="start-layer-title">Create Your Account</h2>
            <p className="start-layer-copy">
              Set your login details to enter the TRAX-X app.
            </p>

            <form
              className="start-create-form"
              id="start-create-account-form"
              onSubmit={(event) => {
                event.preventDefault();
                submitCreateAccount();
              }}
            >
              <label>
                <span>Username</span>
                <input
                  autoComplete="username"
                  value={accountForm.username}
                  onChange={(event) => updateAccountForm("username", event.target.value)}
                />
              </label>
              <label>
                <span>Password</span>
                <input
                  type="password"
                  autoComplete="new-password"
                  value={accountForm.password}
                  onChange={(event) => updateAccountForm("password", event.target.value)}
                />
              </label>
              <label>
                <span>Confirm Password</span>
                <input
                  type="password"
                  autoComplete="new-password"
                  value={accountForm.confirmPassword}
                  onChange={(event) => updateAccountForm("confirmPassword", event.target.value)}
                />
              </label>
              {error && <div className="start-error">{error}</div>}
            </form>
          </section>
        )}

        <div className="start-layer-actions">
          {step > 1 && (
            <button
              className="start-secondary-action"
              type="button"
              onClick={() => {
                setError("");
                setStep((current) => Math.max(1, current - 1));
              }}
              disabled={submitting}
            >
              Previous
            </button>
          )}
          <button
            className="start-primary-action"
            type={step === 3 ? "submit" : "button"}
            form={step === 3 ? "start-create-account-form" : undefined}
            disabled={
              submitting ||
              (step === 1 && !selectedAccount) ||
              (step === 2 && !selectedFunding) ||
              (step === 3 &&
                (!accountForm.username ||
                  !accountForm.password ||
                  !accountForm.confirmPassword))
            }
            onClick={() => {
              if (step === 1) {
                setStep(2);
                return;
              }
              if (step === 2) {
                setStep(3);
              }
            }}
          >
            {submitting
              ? "Creating Account"
              : step === 3
                ? "Create Account"
                : "Continue ->"}
          </button>
        </div>
      </aside>
    </div>
  );
};

export default StartInvestingLayer;
