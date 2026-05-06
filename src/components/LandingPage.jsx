import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import StartInvestingLayer from "./StartInvestingLayer";
import "./LandingPage.css";

const features = [
  {
    tag: "AI",
    title: "AI-Powered Insights",
    copy: "Advanced algorithms scan millions of data points to find high-probability trades.",
  },
  {
    tag: "RT",
    title: "Real-Time Alerts",
    copy: "Never miss an opportunity with real-time alerts and market updates.",
  },
  {
    tag: "RM",
    title: "Risk Management",
    copy: "Built-in risk tools help protect your capital and trade smarter.",
  },
  {
    tag: "AP",
    title: "All-in-One Platform",
    copy: "Everything you need to research, analyze, and trade in one platform.",
  },
];

const movers = [
  { symbol: "NVDA", price: "$495.00", move: "+3.4%", tone: "up" },
  { symbol: "TSLA", price: "$248.10", move: "-0.8%", tone: "down" },
  { symbol: "AMZN", price: "$178.25", move: "+1.1%", tone: "up" },
  { symbol: "MSFT", price: "$415.30", move: "+0.6%", tone: "up" },
];

const journeySteps = [
  {
    step: "Step 1",
    number: "1",
    title: "Create Account",
    copy: "Sign up in less than a minute",
  },
  {
    step: "Step 2",
    number: "2",
    title: "Choose Account",
    copy: "Select the account type that fits you",
  },
  {
    step: "Step 3",
    number: "3",
    title: "Connect & Secure",
    copy: "Connect your brokerage and secure your data",
  },
  {
    step: "Step 4",
    number: "4",
    title: "Customize",
    copy: "Set your watchlist and preferences",
  },
  {
    step: "Step 5",
    number: "5",
    title: "Start Trading",
    copy: "Get AI-powered trade ideas",
  },
];

const accountCards = [
  {
    id: "personal",
    title: "Personal",
    accent: "blue",
    copy: "Invest and trade as an individual.",
    perks: ["Personal investing", "Retirement accounts", "Tax-advantaged accounts", "And more"],
  },
  {
    id: "business",
    title: "Business",
    accent: "green",
    copy: "Manage your business finances and investments.",
    perks: ["Business checking", "Business savings", "Merchant services", "And more"],
  },
  {
    id: "corporate",
    title: "Corporate",
    accent: "purple",
    copy: "Advanced solutions for companies and teams.",
    perks: ["Corporate accounts", "Treasury management", "Employee management", "And more"],
  },
];

const MiniChart = ({ variant = "primary" }) => (
  <svg className={`traxx-mini-chart ${variant}`} viewBox="0 0 220 120" aria-hidden="true">
    <defs>
      <linearGradient id={`chart-fill-${variant}`} x1="0" x2="0" y1="0" y2="1">
        <stop offset="0%" stopColor={variant === "primary" ? "#3178ff" : "#20bc70"} stopOpacity="0.34" />
        <stop offset="100%" stopColor={variant === "primary" ? "#3178ff" : "#20bc70"} stopOpacity="0" />
      </linearGradient>
    </defs>
    <path
      d="M12 94 L38 82 L62 88 L86 58 L112 66 L138 44 L166 49 L192 32 L214 36 L214 120 L12 120 Z"
      fill={`url(#chart-fill-${variant})`}
    />
    <polyline
      points="12,94 38,82 62,88 86,58 112,66 138,44 166,49 192,32 214,36"
      fill="none"
      stroke={variant === "primary" ? "#3178ff" : "#20bc70"}
      strokeWidth="5"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const Sparkline = ({ tone }) => (
  <svg className={`traxx-sparkline ${tone}`} viewBox="0 0 90 38" aria-hidden="true">
    <polyline
      points={tone === "down" ? "4,12 22,18 38,14 54,22 70,28 86,31" : "4,30 22,22 38,28 54,14 70,18 86,11"}
      fill="none"
      stroke="currentColor"
      strokeWidth="4"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const LandingPage = () => {
  const navigate = useNavigate();
  const [isStartLayerOpen, setIsStartLayerOpen] = useState(false);
  const [initialAccount, setInitialAccount] = useState("");

  const openStartLayer = (account = "") => {
    setInitialAccount(account);
    setIsStartLayerOpen(true);
  };

  const scrollToDemo = () => {
    document.getElementById("traxx-demo")?.scrollIntoView({ behavior: "smooth" });
  };

  const completeStartFlow = (selection) => {
    sessionStorage.setItem("traxxStartSelection", JSON.stringify(selection));
    setIsStartLayerOpen(false);
    navigate("/scanner");
  };

  return (
    <main className="traxx-landing">
      <header className="traxx-nav">
        <Link className="traxx-brand" to="/" aria-label="TRAX-X home">
          <span>T</span>
          TRAX-X
        </Link>

        <nav className="traxx-nav-links" aria-label="Primary navigation">
          <a href="#features">Features</a>
          <a href="#pricing">Pricing</a>
          <a href="#security">Security</a>
          <a href="#learn">Learn</a>
          <a href="#support">Support</a>
        </nav>

        <Link className="traxx-signin" to="/scanner">
          Sign In
        </Link>
      </header>

      <section className="traxx-hero">
        <div className="traxx-hero-copy">
          <p className="traxx-pill">+ AI-Powered Trading for Every Investor</p>
          <h1>
            Smarter Trades.
            <span>Stronger Tomorrow.</span>
          </h1>
          <p className="traxx-hero-subtitle">
            AI-powered market insights and real-time analysis to help you trade with confidence.
          </p>

          <div className="traxx-hero-actions">
            <button className="traxx-primary-btn" type="button" onClick={() => openStartLayer()}>
              Start Investing Now <span aria-hidden="true">-></span>
            </button>
            <button className="traxx-secondary-btn" type="button" onClick={scrollToDemo}>
              <span aria-hidden="true">Play</span> See How It Works
            </button>
          </div>

          <div className="traxx-trust-row" aria-label="Platform highlights">
            <span>Bank-level Security</span>
            <span>Real-time Insights</span>
            <span>Trusted by Traders</span>
          </div>
        </div>

        <div className="traxx-hero-visual" aria-label="Trading dashboard preview">
          <section className="traxx-portfolio-panel">
            <p>Portfolio Value</p>
            <strong>$28,540.15</strong>
            <span>+ 2.08% Today</span>
            <MiniChart />
            <div className="traxx-range-tabs" aria-hidden="true">
              <span>1D</span>
              <span>1W</span>
              <span>1M</span>
              <span>3M</span>
              <span>YTD</span>
              <span>ALL</span>
            </div>
          </section>

          <section className="traxx-trade-panel">
            <p>AI Trade Idea</p>
            <div className="traxx-trade-head">
              <strong>AAPL</strong>
              <span>+ 2.38%</span>
            </div>
            <small>Strong Buy</small>
            <dl>
              <div>
                <dt>Entry Range</dt>
                <dd>$180.00 - $184.00</dd>
              </div>
              <div>
                <dt>Stop Loss</dt>
                <dd>$176.40</dd>
              </div>
              <div>
                <dt>Target</dt>
                <dd>$194.80</dd>
              </div>
            </dl>
            <button type="button">View Trade</button>
          </section>

          <section className="traxx-movers-panel">
            <p>Market Movers</p>
            <div className="traxx-movers-grid">
              {movers.map((mover) => (
                <div className="traxx-mover" key={mover.symbol}>
                  <strong>{mover.symbol}</strong>
                  <small>{mover.price}</small>
                  <Sparkline tone={mover.tone} />
                  <span className={mover.tone}>{mover.move}</span>
                </div>
              ))}
            </div>
          </section>
        </div>
      </section>

      <section className="traxx-section traxx-features" id="features">
        <div className="traxx-section-heading">
          <h2>
            Why Traders Choose <span>TRAX-X</span>
          </h2>
          <p>Everything you need to trade smarter, manage risk, and grow wealth</p>
        </div>

        <div className="traxx-feature-grid">
          {features.map((feature) => (
            <article className="traxx-feature-card" key={feature.title}>
              <span>{feature.tag}</span>
              <h3>{feature.title}</h3>
              <p>{feature.copy}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="traxx-section traxx-demo" id="traxx-demo">
        <div className="traxx-demo-copy">
          <p className="traxx-pill">See TRAX-X in Action</p>
          <h2>
            See How It Works in <span>60 Seconds</span>
          </h2>
          <p>
            Watch a quick demo to see how TRAX-X helps you find smarter trades, manage risk,
            and grow your portfolio.
          </p>
          <button className="traxx-primary-btn compact" type="button">
            Watch Demo <span aria-hidden="true">Play</span>
          </button>
          <small>01:03 min</small>
        </div>

        <div className="traxx-phone-demo" aria-label="Mobile trading preview">
          <div className="traxx-phone-screen">
            <p>Good morning, Alex</p>
            <small>Portfolio Value</small>
            <strong>$28,540.15</strong>
            <span>+ 2.08% Today</span>
            <MiniChart variant="secondary" />
            <div className="traxx-phone-trade">
              <small>AI Trade Idea</small>
              <strong>AAPL</strong>
              <span>+ 2.38%</span>
            </div>
            <button type="button" aria-label="Play demo">
              Play
            </button>
          </div>
        </div>
      </section>

      <section className="traxx-section traxx-journey" id="learn">
        <div className="traxx-section-heading">
          <h2>
            Start Your <span>Journey</span>
          </h2>
          <p>Simple steps to get you started</p>
        </div>

        <div className="traxx-journey-line" aria-label="Getting started steps">
          {journeySteps.map((item) => (
            <article className="traxx-journey-step" key={item.title}>
              <span>{item.number}</span>
              <small>{item.step}</small>
              <h3>{item.title}</h3>
              <p>{item.copy}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="traxx-section traxx-accounts" id="pricing">
        <div className="traxx-section-heading">
          <h2>Choose the Right Account for You</h2>
          <p>Flexible options for every type of investor</p>
        </div>

        <div className="traxx-account-grid">
          {accountCards.map((account) => (
            <article className={`traxx-account-card ${account.accent}`} key={account.id}>
              <div className="traxx-account-head">
                <span>{account.title.slice(0, 1)}</span>
                <div>
                  <h3>{account.title}</h3>
                  <p>{account.copy}</p>
                </div>
              </div>
              <ul>
                {account.perks.map((perk) => (
                  <li key={perk}>{perk}</li>
                ))}
              </ul>
              <button type="button" onClick={() => openStartLayer(account.id)}>
                Select {account.title}
              </button>
            </article>
          ))}
        </div>
      </section>

      <section className="traxx-section traxx-security" id="security">
        <div className="traxx-section-heading">
          <h2>Security Built Into Every Step</h2>
          <p>TRAX-X keeps sensitive trading workflows behind your protected app session.</p>
        </div>
      </section>

      <section className="traxx-section traxx-support" id="support">
        <div className="traxx-section-heading">
          <h2>Support When You Need It</h2>
          <p>Use the app navigation after sign in to manage alerts, scanners, and trade research.</p>
        </div>
      </section>

      {isStartLayerOpen && (
        <StartInvestingLayer
          initialAccount={initialAccount}
          onComplete={completeStartFlow}
          onClose={() => setIsStartLayerOpen(false)}
        />
      )}
    </main>
  );
};

export default LandingPage;
