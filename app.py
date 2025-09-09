import streamlit as st
import pandas as pd
import yfinance as yf
import datetime
from st_aggrid import AgGrid, GridOptionsBuilder
import plotly.express as px
import requests
from io import StringIO

def get_index_constituents(index_name):
    """Fetch index constituents from Wikipedia safely with headers."""
    if index_name == "Nasdaq-100":
        url = "https://en.wikipedia.org/wiki/Nasdaq-100"
        table_idx = 4
    elif index_name == "S&P 500":
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        table_idx = 0
    else:
        st.error("Unsupported index.")
        return pd.DataFrame(columns=["Ticker", "Company"])

    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        tables = pd.read_html(StringIO(resp.text))
        df = tables[table_idx]

        if index_name == "Nasdaq-100":
            tickers = df["Ticker"].tolist()
            companies = df["Company"].tolist()
        else:  # S&P 500
            tickers = df["Symbol"].tolist()
            companies = df["Security"].tolist()

        return pd.DataFrame({"Ticker": tickers, "Company": companies})

    except Exception as e:
        st.error(f"Failed to load index constituents: {e}")
        return pd.DataFrame(columns=["Ticker", "Company"])

def download_prices(tickers, start, end):
    """Download price data in chunks to avoid API limits."""
    all_data = pd.DataFrame()
    chunk_size = 30  # smaller chunks reduce Yahoo blocking
    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i:i + chunk_size]
        try:
            data = yf.download(chunk, start=start, end=end, progress=False, group_by="ticker")
            if data.empty:
                st.warning(f"No data returned for chunk {chunk}")
                continue

            # Case 1: MultiIndex with "Adj Close"
            if isinstance(data.columns, pd.MultiIndex) and "Adj Close" in data.columns.levels[0]:
                adj_close = data["Adj Close"]
            # Case 2: SingleIndex DataFrame with "Adj Close"
            elif "Adj Close" in data.columns:
                adj_close = data["Adj Close"].to_frame() if isinstance(data["Adj Close"], pd.Series) else data[["Adj Close"]]
            else:
                st.warning(f"'Adj Close' not found for chunk {chunk}")
                continue

            all_data = pd.concat([all_data, adj_close], axis=1)

        except Exception as e:
            st.warning(f"Failed to download chunk {chunk}: {e}")

    return all_data

def compute_returns(prices, window):
    """Compute % returns over a given window."""
    if len(prices) < window:
        return pd.Series(dtype=float)
    returns = prices.pct_change(window).iloc[-1].dropna()
    return returns


def get_selected_ticker(grid_response):
    """Extract ticker from AgGrid selection (robust to DF/dict)."""
    selected_rows = grid_response.get("selected_rows", [])
    if isinstance(selected_rows, pd.DataFrame):
        selected_rows = selected_rows.to_dict("records")
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
st.set_page_config(page_title="Index Movers Dashboard", layout="wide")

st.title("📈 Index Movers Dashboard")

# Sidebar
index_choice = st.sidebar.radio("Choose Index", ["Nasdaq-100", "S&P 500"])
window = st.sidebar.number_input("Trading Days Window", 5, 60, 30)
top_n = st.sidebar.slider("Top N", 5, 20, 10)

# Load constituents
constituents = get_index_constituents(index_choice)
if constituents.empty:
    st.stop()

tickers = constituents["Ticker"].tolist()
end = datetime.date.today()
start = end - datetime.timedelta(days=90)  # lookback 90 calendar days

prices = download_prices(tickers, start, end)

if prices.empty:
    st.error("No price data available.")
    st.stop()

returns = compute_returns(prices, window)

if returns.empty:
    st.error(f"Not enough data points for {window}-day window.")
    st.stop()

df = pd.DataFrame({
    "Ticker": returns.index,
    "Return": (returns.values * 100).round(2)
}).merge(constituents, on="Ticker")

winners = df.sort_values("Return", ascending=False).head(top_n)
losers = df.sort_values("Return", ascending=True).head(top_n)

# -----------------------------
# Display Winners
# -----------------------------
st.subheader(f"Top {top_n} Winners")
gb_top = GridOptionsBuilder.from_dataframe(winners)
gb_top.configure_selection("single", use_checkbox=False)
grid_top = AgGrid(
    winners,
    gridOptions=gb_top.build(),
    update_on=["selectionChanged"],
    fit_columns_on_grid_load=True,
    height=300,
    theme="streamlit",
    key="grid_top",
    show_index=False,   # ✅ hide blank index column
)

# -----------------------------
# Display Losers
# -----------------------------
st.subheader(f"Top {top_n} Losers")
gb_bot = GridOptionsBuilder.from_dataframe(losers)
gb_bot.configure_selection("single", use_checkbox=False)
grid_bot = AgGrid(
    losers,
    gridOptions=gb_bot.build(),
    update_on=["selectionChanged"],
    fit_columns_on_grid_load=True,
    height=300,
    theme="streamlit",
    key="grid_bot",
    show_index=False,   # ✅ hide blank index column
)

# -----------------------------
# Handle selection tracking
# -----------------------------
sel_top = get_selected_ticker(grid_top)
sel_bot = get_selected_ticker(grid_bot)

if "prev_top" not in st.session_state:
    st.session_state["prev_top"] = None
if "prev_bot" not in st.session_state:
    st.session_state["prev_bot"] = None
if "last_clicked" not in st.session_state:
    st.session_state["last_clicked"] = None

if sel_top != st.session_state["prev_top"]:
    st.session_state["prev_top"] = sel_top
    st.session_state["last_clicked"] = "top"

if sel_bot != st.session_state["prev_bot"]:
    st.session_state["prev_bot"] = sel_bot
    st.session_state["last_clicked"] = "bot"

last = st.session_state["last_clicked"]
if last == "top":
    ticker_choice = sel_top
elif last == "bot":
    ticker_choice = sel_bot
else:
    ticker_choice = None

# -----------------------------
# Chart
# -----------------------------
if ticker_choice and ticker_choice in prices.columns:
    st.subheader(f"📊 {ticker_choice} Price Trend ({window} days)")
    prices_to_plot = prices[ticker_choice].dropna()
    fig = px.line(
        prices_to_plot[-window-1:],
        title=f"{ticker_choice} Price Trend ({window} days)",
        labels={"index": "Date", "value": "Price"}
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Click a ticker in Winners or Losers to see its chart.")
