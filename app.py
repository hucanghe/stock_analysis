import streamlit as st
import pandas as pd
import yfinance as yf
import requests, io, os
import plotly.express as px
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode
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

def get_sp500_constituents():
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(WIKI_URL_SP500, headers=headers)
    resp.raise_for_status()
    tables = pd.read_html(io.StringIO(resp.text))
    for df in tables:
        cols = [str(c).lower() for c in df.columns]
        if "symbol" in cols and "security" in cols:
            df_out = df[[df.columns[cols.index("symbol")], df.columns[cols.index("security")]]]
            df_out.columns = ["Ticker", "Company"]
            df_out["Ticker"] = df_out["Ticker"].astype(str).str.strip()
            return df_out
    raise RuntimeError("No suitable table found for S&P 500")

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

# AgGrid selection helper (robust)
def get_selected_ticker(grid_response):
    selected_rows = grid_response.get("selected_rows", [])
    if isinstance(selected_rows, pd.DataFrame):
        selected_rows = selected_rows.to_dict("records")  # convert DataFrame to list of dicts
    if not selected_rows:
        return None
    row = selected_rows[0]
    for key in row.keys():
        if key.lower() == "ticker":
            return row[key]
    return None

# -----------------------------
# Streamlit UI
# -----------------------------
st.set_page_config(page_title="Top10 Dashboard", layout="wide")
st.title("📊 Top10 Winners & Losers")

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

# -----------------------------
# Single tab: Tables + Chart
# -----------------------------
st.subheader(f"Top10 and Chart ({window}-day returns, as of {asof_date})")
col1, col2 = st.columns(2)
with col1:
    st.write("🏆 Top 10 Winners")
    gb_top = GridOptionsBuilder.from_dataframe(top)
    gb_top.configure_selection("single", use_checkbox=False)
    grid_top = AgGrid(top, gridOptions=gb_top.build(), update_on=["selectionChanged"])

with col2:
    st.write("💀 Top 10 Losers")
    gb_bot = GridOptionsBuilder.from_dataframe(bot)
    gb_bot.configure_selection("single", use_checkbox=False)
    grid_bot = AgGrid(bot, gridOptions=gb_bot.build(), update_on=["selectionChanged"])

    # Get selected ticker robustly
    # --- after grid_top and grid_bot are created ---

    # get current selections (may be None)
    sel_top = get_selected_ticker(grid_top)
    sel_bot = get_selected_ticker(grid_bot)

    # initialize session state keys if missing
    if "prev_top_selected_ticker" not in st.session_state:
        st.session_state["prev_top_selected_ticker"] = None
    if "prev_bot_selected_ticker" not in st.session_state:
        st.session_state["prev_bot_selected_ticker"] = None
    if "last_clicked" not in st.session_state:
        st.session_state["last_clicked"] = None

    # detect which grid changed since last run
    if sel_top != st.session_state["prev_top_selected_ticker"]:
        st.session_state["prev_top_selected_ticker"] = sel_top
        # if user clicked in top grid, mark it as last clicked
        st.session_state["last_clicked"] = "top"

    if sel_bot != st.session_state["prev_bot_selected_ticker"]:
        st.session_state["prev_bot_selected_ticker"] = sel_bot
        # if user clicked in bot grid, mark it as last clicked
        st.session_state["last_clicked"] = "bot"

    # choose ticker based on last click (prefer the most recently clicked grid)
    last = st.session_state.get("last_clicked")
    if last == "top":
        ticker_choice = sel_top
    elif last == "bot":
        ticker_choice = sel_bot
    else:
        # fallback if no last_clicked set yet
        ticker_choice = sel_top or sel_bot

# Plot chart
st.subheader("📈 Price Trend")
if ticker_choice and ticker_choice in prices.columns:
    prices_to_plot = prices[ticker_choice].dropna()
    fig = px.line(
        prices_to_plot[-window-1:],
        title=f"{ticker_choice} Price Trend ({window} days)",
        labels={"index": "Date", ticker_choice: "Price"}
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Click a ticker in the Winners or Losers to see its chart.")

# Download CSV
st.download_button("💾 Download full CSV", df.to_csv(index=False), f"{index_choice}_returns.csv", "text/csv")
