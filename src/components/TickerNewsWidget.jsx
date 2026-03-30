import React, { useEffect, useState } from "react";
import { apiFetch } from "../apiClient";
import "./TickerNewsWidget.css";

const TickerNewsWidget = ({ tickers }) => {
  const [news, setNews] = useState({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!tickers || tickers.length === 0) {
      setNews({});
      setLoading(false);
      return;
    }

    const fetchNewsForTickers = async () => {
      setLoading(true);

      try {
        const tickerString = tickers.join(",");
        const data = await apiFetch(`/api/ticker-news?ticker=${tickerString}`);

        if (data?.error) {
          setNews({});
          return;
        }

        setNews(data || {});
      } catch (error) {
        console.error("Error fetching news:", error);
        setNews({});
      } finally {
        setLoading(false);
      }
    };

    fetchNewsForTickers();
  }, [tickers]);

  return (
    <div className="scanner-card scanner-news-card">
      <div className="scanner-card-header">
        <div>
          <h3 className="scanner-card-title">Latest Stock News</h3>
          <p className="scanner-card-subtitle">Catalysts linked to the current scanner results.</p>
        </div>
      </div>

      <div className="scanner-card-body scanner-news-body">
        {loading ? (
          <div className="scanner-empty-state scanner-news-empty">
            <div className="scanner-empty-kicker">News Feed</div>
            <h4>Loading market context...</h4>
            <p>Collecting headlines tied to the current result set.</p>
          </div>
        ) : Object.keys(news).length === 0 ? (
          <div className="scanner-empty-state scanner-news-empty">
            <div className="scanner-empty-kicker">No Headlines</div>
            <h4>No news available for the selected stocks.</h4>
            <p>Run the scanner or widen the filters to populate the context feed.</p>
          </div>
        ) : (
          Object.entries(news).map(([ticker, articles]) => (
            <section key={ticker} className="news-section">
              <div className="news-section-header">
                <h5>{ticker}</h5>
                <span>{articles.length} articles</span>
              </div>

              {articles.length > 0 ? (
                articles.map((article) => (
                  <article key={article.id} className="news-article">
                    <a
                      className="news-article-title"
                      href={article.article_url}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {article.title}
                    </a>

                    <div className="news-article-meta">
                      <span>
                        {typeof article.publisher === "object"
                          ? article.publisher.name
                          : "Unknown Publisher"}
                      </span>
                      <span>{new Date(article.published_utc).toLocaleString()}</span>
                    </div>

                    {article.description && (
                      <p className="news-article-description">{article.description}</p>
                    )}

                    {article.image_url && (
                      <img
                        className="news-article-image"
                        src={article.image_url}
                        alt={article.title}
                      />
                    )}

                    <p className="news-article-sentiment">
                      <strong>Sentiment:</strong> {article.sentiment}
                      {article.sentiment_reasoning ? ` - ${article.sentiment_reasoning}` : ""}
                    </p>
                  </article>
                ))
              ) : (
                <p className="news-section-empty">No news available for {ticker}.</p>
              )}
            </section>
          ))
        )}
      </div>
    </div>
  );
};

export default TickerNewsWidget;
