# 📈 Index Movers Dashboard

A lightweight **Streamlit app** to track the **Top Winners and Losers** in major US indices (Nasdaq-100 and S&P 500) over a rolling window of trading days.  

The app fetches index constituents from Wikipedia, downloads stock price data from Yahoo Finance (via `yfinance`), and displays:
- Top **N** gainers and losers in a selected window
- Interactive tables (clickable with AgGrid)
- Line chart of selected ticker’s recent price trend

🚀 Live Demo: (replace with your Streamlit Cloud link)

---

## 📦 Features

- Choose between **Nasdaq-100** and **S&P 500**
- Adjustable trading window (e.g. last 30 days)
- Selectable number of Top Winners/Losers
- Interactive tables powered by **st-aggrid**
- Line chart visualization with **Plotly**
- Robust error handling for Wikipedia & Yahoo data sources

---

## ⚙️ Installation


Clone the repo:

```bash
git clone https://github.com/hucanghe/stock_analysis.git
cd stock_analysis
pip install -r requirements.txt

## ⚙️ Usage

Run the app locally:
```bash
streamlit run app.py

Open your browser at http://localhost:8501
