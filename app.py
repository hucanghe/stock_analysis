import streamlit as st
import pandas as pd
import yfinance as yf
import requests, io, os
import plotly.express as px
from datetime import datetime

# -----------------------------
# Settings
# -----------------------------
WIKI_URL_NDX = "https://en.wikipedia.org/wiki/Nasdaq-100"
WIKI_URL_SP500 = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

# -----------------------------
# Helpers
# -----------------------------
def get_constituents(url):
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    tables = pd.read_html(io.StringIO(resp.text))
    for df in tables:
        cols = {str(c).lower(): c for c in df.columns}
        if "ticker" in cols and ("company" in cols or "company name" in cols):
            cname = cols.get("company") or cols.get("company name")
            out = df[[cols["ticker"], cname]].rename(columns={cols["ticker"]: "Ticker", cname: "Company"})
            out["Ticker"] = out["Ticker"].astype(str).str.replace(".", "-", regex=False).str.strip()
            return out
    raise RuntimeError("No suitable table found on Wikipedia page")

def fetch_prices(tickers, lookback=160, chunk=25):
    all_prices = []
    for i in range(0, len(tickers), chunk):
        batch = tickers[i:i+chunk]
        df = yf.download(batch, period=f"{lookback}d", interval="1d", auto_adjust=True, progress=False, group_by="ticker")
        if df.empty:
            continue
        if isinstance(df.columns, pd.MultiIndex):
            closes = {t: df[t]["Close"] for t in batch if t in df.columns.get_level_values(0)}
            all_prices.append(pd.DataFrame(closes))
        else:
            closes = df[["Close"]].rename(columns={"Close": batch[0]})
            all_prices.append(closes)
    if not all_prices:
        return pd.DataFrame()
    return pd.concat(all_prices, axis=1)

def compute_returns(prices, window):
    prices.index = pd.to_datetime(prices.index)
    prices = prices.dropna(axis=1, how="all")
    if len(prices) <= window:
        return pd.DataFrame(), None
    valid = prices.dropna(axis=1, thresh=window+1)
    if valid.empty:
        return pd.DataFrame(), None
    returns = valid.pct_change(window).iloc[-1].dropna()
    return returns, prices.index.max().date()

def get_sp500_constituents():
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(WIKI_URL_SP500, headers=headers)
    resp.raise_for_status()
    tables = pd.read_html(io.StringIO(resp.text))
    for df in tables:
        cols = [str(c).lower() for c in df.columns]
        if "symbol" in cols and "security" in cols:
            # pick the right columns
            df_out = df[[df.columns[cols.index("symbol")], df.columns[cols.index("security")]]]
            df_out.columns = ["Ticker", "Company"]
            df_out["Ticker"] = df_out["Ticker"].astype(str).str.strip()
            return df_out
    raise RuntimeError("No suitable table found for S&P 500")

# -----------------------------
# Streamlit UI
# -----------------------------
st.set_page_config(page_title="Stock Top10 Dashboard", layout="wide")
st.title("📊 Top10 Winners & Losers Dashboard")

# User controls
window = st.slider("Trading day window", min_value=5, max_value=90, value=30, step=5)
index_choice = st.radio("Select Index", ["Nasdaq-100", "S&P 500"])

# Fetch constituents
try:
    if index_choice == "Nasdaq-100":
        names = get_constituents(WIKI_URL_NDX)
    else:
        names = get_sp500_constituents()

    tickers = names["Ticker"].tolist()
except Exception as e:
    st.error(f"Failed to load index constituents: {e}")
    st.stop()

# Fetch prices
with st.spinner("Fetching price data..."):
    prices = fetch_prices(tickers, lookback=200)
if prices.empty:
    st.error("No price data retrieved. Try again later.")
    st.stop()

returns, asof_date = compute_returns(prices, window)
if returns.empty:
    st.error(f"Not enough data points for a {window}-day window.")
    st.stop()

# Build dataframe
df = returns.reset_index()
df.columns = ["Ticker", "Return"]
df = df.merge(names, on="Ticker", how="left")
df["Return"] = (df["Return"] * 100).round(2)

# Top & bottom 10
top = df.nlargest(10, "Return")
bot = df.nsmallest(10, "Return")

# Alert new entries
prev_file = f"previous_top10_{index_choice}.csv"
if os.path.exists(prev_file):
    previous_top = pd.read_csv(prev_file)
    new_entries = top[~top["Ticker"].isin(previous_top["Ticker"])]
    if not new_entries.empty:
        st.success(f"⚡ New Top10 Winners: {', '.join(new_entries['Ticker'].tolist())}")
top.to_csv(prev_file, index=False)

# Tabs for Top10 Tables and Individual Charts
tab1, tab2 = st.tabs(["Top10 Winners & Losers", "Individual Ticker Chart"])

with tab1:
    col1, col2 = st.columns(2)
    with col1:
        st.subheader(f"Top 10 Winners ({window} trading days, as of {asof_date})")
        st.dataframe(top, hide_index=True)
        fig = px.bar(top, x="Ticker", y="Return", color="Return", color_continuous_scale="Greens", text="Return")
        st.plotly_chart(fig, use_container_width=True)
    with col2:
        st.subheader(f"Top 10 Losers ({window} trading days, as of {asof_date})")
        st.dataframe(bot, hide_index=True)
        fig2 = px.bar(bot, x="Ticker", y="Return", color="Return", color_continuous_scale="Reds", text="Return")
        st.plotly_chart(fig2, use_container_width=True)

with tab2:
    st.subheader("📈 Interactive Price Trend")
    ticker_choice = st.selectbox("Select a ticker", df["Ticker"].tolist())
    prices_to_plot = prices[ticker_choice].dropna()
    fig3 = px.line(prices_to_plot[-window-1:], title=f"{ticker_choice} Price Trend", labels={"index":"Date", ticker_choice:"Price"})
    st.plotly_chart(fig3, use_container_width=True)

# Download CSV
st.download_button("💾 Download full CSV", df.to_csv(index=False), f"{index_choice}_returns.csv", "text/csv")
