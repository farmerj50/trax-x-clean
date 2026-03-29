from io import BytesIO
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from polygon import RESTClient
import config

POLYGON_API_KEY = config.POLYGON_API_KEY
client = RESTClient(POLYGON_API_KEY)

def fetch_sentiment_trend(ticker, start_date, end_date):
    """
    Fetch daily sentiment trends for a given ticker within a date range.
    """
    sentiment_count = []
    for day in pd.date_range(start=start_date, end=end_date):
        try:
            daily_news = list(client.list_ticker_news(ticker, published_utc=day.strftime("%Y-%m-%d"), limit=100))
            daily_sentiment = {'date': day.strftime("%Y-%m-%d"), 'positive': 0, 'negative': 0, 'neutral': 0}
            for article in daily_news:
                if hasattr(article, 'insights') and article.insights:
                    for insight in article.insights:
                        if insight.sentiment == 'positive':
                            daily_sentiment['positive'] += 1
                        elif insight.sentiment == 'negative':
                            daily_sentiment['negative'] += 1
                        elif insight.sentiment == 'neutral':
                            daily_sentiment['neutral'] += 1
            sentiment_count.append(daily_sentiment)
        except Exception as e:
            print(f"Error fetching sentiment for {ticker} on {day}: {e}")
    return pd.DataFrame(sentiment_count)


def generate_sentiment_plot(ticker, start_date, end_date):
    """
    Generate and return a sentiment plot for a given ticker and date range.
    """
    sentiment_data = fetch_sentiment_trend(ticker, start_date, end_date)
    sentiment_data['date'] = pd.to_datetime(sentiment_data['date'])

    # Plot the sentiment data
    plt.figure(figsize=(20, 10))
    plt.plot(sentiment_data['date'], sentiment_data['positive'], label='Positive', color='green')
    plt.plot(sentiment_data['date'], sentiment_data['negative'], label='Negative', color='red')
    plt.plot(sentiment_data['date'], sentiment_data['neutral'], label='Neutral', color='grey', linestyle='--')
    plt.title(f'Sentiment Trends for {ticker}')
    plt.xlabel('Date')
    plt.ylabel('Sentiment Counts')
    plt.legend()
    plt.grid(True)

    # Format the x-axis to display dates
    plt.gca().xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    plt.gcf().autofmt_xdate()

    # Save the plot to a BytesIO buffer
    buffer = BytesIO()
    plt.savefig(buffer, format='png')
    buffer.seek(0)
    plt.close()

    return buffer
