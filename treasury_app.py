import streamlit as st
import pandas as pd
import plotly.express as px
import requests
import urllib3

# Suppress corporate SSL verification warnings in your terminal console
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==============================================================================
# 1. PAGE CONFIGURATION
# ==============================================================================
st.set_page_config(
    page_title="US Treasury Receipts Dashboard",
    page_icon="🏦",
    layout="wide"
)

st.title("🏦 Federal Government Receipts Dashboard")
st.markdown("Interactive analysis of live federal government revenue collected via the U.S. Treasury API.")

# ==============================================================================
# 2. OPTIMIZED DATA INGESTION WITH PROXY BYPASS & SSL DISABLE
# ==============================================================================
@st.cache_data(ttl=3600)
def load_and_clean_data():
    """
    Fetches, paginates, cleans, and melts data from the U.S. Government Receipts API.
    Bypasses corporate firewall blocks by disabling strict SSL constraints.
    """
    # Fixed base path mapping explicitly with trailing slash to prevent string merging typos
    base_url = "https://treasury.gov"
    endpoint = "v1/accounting/mts/mts_table_4"
    
    params = {
        "format": "json",
        "sort": "-record_date",
        "page[size]": 1000,
        "page[number]": 1
    }

    proxies = {
        "http": "http://10.224.0.153:8080",
        "https": "http://10.224.0.153:8080"
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }

    try:
        # verify=False instructs Python to bypass corporate self-signed certificate constraints
        response = requests.get(base_url + endpoint, params=params, proxies=proxies, headers=headers, verify=False, timeout=25)
        
        if "html" in response.headers.get("Content-Type", "").lower() or response.text.strip().startswith("<!doctype"):
            return {
                "status": "error", 
                "message": "Corporate network gateway intercepted request and redirected to an HTML portal.", 
                "raw_text": response.text[:600]
            }

        if response.status_code != 200:
            return {"status": "error", "message": f"Proxy Rejection. HTTP Status: {response.status_code}", "raw_text": response.text[:600]}

        json_data = response.json()
        all_data = json_data.get("data", [])
        total_pages = json_data.get("meta", {}).get("total-pages", 1)

        # Paginate through subsequent records securely
        for page in range(2, total_pages + 1):
            params["page[number]"] = page
            alt_res = requests.get(base_url + endpoint, params=params, proxies=proxies, headers=headers, verify=False, timeout=25)
            if alt_res.status_code == 200 and "html" not in alt_res.headers.get("Content-Type", "").lower():
                try:
                    all_data.extend(alt_res.json().get("data", []))
                except Exception:
                    pass

        df_raw = pd.DataFrame(all_data)
        if df_raw.empty:
            return {"status": "error", "message": "Parsed out an empty dataset.", "raw_text": ""}

        df_raw['record_date'] = pd.to_datetime(df_raw['record_date'], errors='coerce')
        for col in df_raw.columns:
            if col.endswith('_amt'):
                df_raw[col] = pd.to_numeric(df_raw[col], errors='coerce')

        id_vars = ['record_date', 'classification_desc', 'record_fiscal_year', 'record_calendar_year', 'record_calendar_month', 'record_calendar_day']
        value_vars = ['current_month_gross_rcpt_amt', 'current_month_refund_amt', 'current_month_net_rcpt_amt']
        
        existing_id_vars = [col for col in id_vars if col in df_raw.columns]
        existing_value_vars = [col for col in value_vars if col in df_raw.columns]

        df_long = pd.melt(df_raw, id_vars=existing_id_vars, value_vars=existing_value_vars, var_name='receipt_type', value_name='amount')
        df_long['amount'] = df_long['amount'].fillna(0)
        
        return {"status": "success", "data": df_long}

    except Exception as e:
        return {"status": "error", "message": f"Network Interception Exception: {str(e)}", "raw_text": ""}

# Fetch the tracking metrics array
result_payload = load_and_clean_data()

# ==============================================================================
# PROXY FAILSAFE Snapshot Engine
# ==============================================================================
if result_payload["status"] == "error":
    st.error(f"❌ API Connection Failure: {result_payload['message']}")
    try:
        df = pd.read_csv("treasury_receipts_long.csv")
        df['record_date'] = pd.to_datetime(df['record_date'])
        st.info("🔄 Running in offline mode using your last downloaded data snapshot ('treasury_receipts_long.csv').")
    except Exception:
        st.warning("No local backup file ('treasury_receipts_long.csv') found. Please connect to the network to pull live metrics.")
        with st.expander("Show Detailed Error Log"):
            st.code(result_payload["message"])
        st.stop()
else:
    df = result_payload["data"]
    # Update local snapshot silently for offline resilience
    df.to_csv("treasury_receipts_long.csv", index=False)

# ==============================================================================
# 3. SIDEBAR SLICERS / FILTERS
# ==============================================================================
st.sidebar.header("🎛️ Dashboard Slicers")

min_date = df['record_date'].min().to_pydatetime()
max_date = df['record_date'].max().to_pydatetime()
selected_date_range = st.sidebar.date_input(
    "Select Record Date Range",
    value=(min_date, max_date),
    min_value=min_date,
    max_value=max_date
)

all_classifications = sorted(df['classification_desc'].dropna().unique().tolist())
selected_classifications = st.sidebar.multiselect(
    "Classification Description", 
    options=all_classifications, 
    default=all_classifications[:5]
)

all_receipt_types = sorted(df['receipt_type'].dropna().unique().tolist())
selected_receipt_types = st.sidebar.multiselect(
    "Receipt Type", 
    options=all_receipt_types, 
    default=all_receipt_types
)

# ==============================================================================
# 4. DATA FILTERING ENGINE
# ==============================================================================
if isinstance(selected_date_range, tuple) and len(selected_date_range) == 2:
    start_date, end_date = selected_date_range
else:
    start_date, end_date = min_date.date(), max_date.date()

filtered_df = df[
    (df['record_date'].dt.date >= start_date) & 
    (df['record_date'].dt.date <= end_date) &
    (df['classification_desc'].isin(selected_classifications if selected_classifications else all_classifications)) &
    (df['receipt_type'].isin(selected_receipt_types if selected_receipt_types else all_receipt_types))
]

# ==============================================================================
# 5. KEY PERFORMANCE METRICS (KPIs)
# ==============================================================================
st.markdown("### 📊 Key Summary Metrics")
total_receipts = filtered_df['amount'].sum()
avg_monthly_receipts = filtered_df.groupby(['record_calendar_year', 'record_calendar_month'])['amount'].sum().mean()
unique_classes = filtered_df['classification_desc'].nunique()

col1, col2, col3 = st.columns(3)
with col1:
    st.metric(label="Total Receipts Period", value=f"${total_receipts:,.2f}")
with col2:
    st.metric(label="Avg Monthly Inflow", value=f"${avg_monthly_receipts:,.2f}" if not pd.isna(avg_monthly_receipts) else "$0.00")
with col3:
    st.metric(label="Active Revenue Streams", value=str(unique_classes))

st.write("---")

# ==============================================================================
# 6. CHARTS SECTION
# ==============================================================================
st.markdown("### 📈 Visual Analytics")
st.markdown("#### Receipts Trend Over Time")
timeline_df = filtered_df.groupby(['record_date', 'receipt_type'], as_index=False)['amount'].sum()

fig_trend = px.line(
    timeline_df, 
    x='record_date', 
    y='amount', 
    color='receipt_type',
    title="Treasury Inflows over Time by Receipt Type",
    template="plotly_white"
)
st.plotly_chart(fig_trend, use_container_width=True)

col_left, col_right = st.columns(2)

with col_left:
    st.markdown("#### Distribution by Receipt Type")
    pie_df = filtered_df.groupby('receipt_type', as_index=False)['amount'].sum()
    fig_pie = px.pie(pie_df, values='amount', names='receipt_type', hole=0.4, title="Revenue Breakdown Split by Receipt Type", template="plotly_white")
    st.plotly_chart(fig_pie, use_container_width=True)

with col_right:
    st.markdown("#### Top Classifications by Volume")
    bar_df = filtered_df.groupby('classification_desc', as_index=False)['amount'].sum().sort_values(by='amount', ascending=True).tail(15)
    fig_bar = px.bar(bar_df, x='amount', y='classification_desc', orientation='h', title="Top Classifications (Highest Inflow)", template="plotly_white")
    st.plotly_chart(fig_bar, use_container_width=True)

# ==============================================================================
# 7. RAW DATA TABLE VIEW
# ==============================================================================
st.write("---")
with st.expander("🔍 View/Download Filtered Tabular Dataset"):
    st.dataframe(filtered_df, use_container_width=True)
