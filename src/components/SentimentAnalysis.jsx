const SentimentCard = ({ sentimentData, sentimentReasons }) => {
    return (
      <div className="sentiment-card">
        <h3>Sentiment Analysis</h3>
        <div className="sentiment-metrics">
          <p><strong>Positive:</strong> {sentimentData.positive}</p>
          <p><strong>Negative:</strong> {sentimentData.negative}</p>
          <p><strong>Neutral:</strong> {sentimentData.neutral}</p>
        </div>
        {sentimentReasons && sentimentReasons.length > 0 && (
          <div className="sentiment-reasons">
            <h4>Sentiment Reasons:</h4>
            {sentimentReasons.map((reason, index) => (
              <div key={index}>
                <p><strong>Date:</strong> {reason.date}</p>
                {reason.reasons.map((r, i) => (
                  <p key={i}><strong>{r.sentiment}:</strong> {r.reasoning}</p>
                ))}
              </div>
            ))}
          </div>
        )}
      </div>
    );
  };
  