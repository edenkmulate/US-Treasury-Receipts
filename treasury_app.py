import requests
import pandas as pd
import time

# Define API base URL and endpoint for Receipts of the U.S. Government
base_url = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/"
endpoint = "/v1/accounting/mts/mts_table_4"

# Set parameters: get all rows, all columns (omit 'fields')
params = {
    "format": "json",
    "sort": "-record_date",
    "page[size]": 1000,
    "page[number]" : 1
}




# First request to get total number of pages
response = requests.get(base_url + endpoint, params=params)
response.raise_for_status()
json_data = response.json()

# Collect first page
all_data = json_data["data"]
total_pages = json_data.get("meta", {}).get("total-pages", 1)

# Paginate through all pages
for page in range(2, total_pages + 1):
    params["page[number]"] = page
    response = requests.get(base_url + endpoint, params=params) 
    response.raise_for_status()
    all_data.extend(response.json()["data"])

# Convert to DataFrame
df = pd.DataFrame(all_data)

# Clean up columns
df['record_date'] = pd.to_datetime(df['record_date'], errors='coerce')
for col in df.columns:
    if col.endswith('_amt'):
        df[col] = pd.to_numeric(df[col], errors='coerce')


# Melt to long format
id_vars = [
    'record_date', 'classification_desc',
    'record_fiscal_year', 'record_calendar_year',
    'record_calendar_month', 'record_calendar_day'
]

value_vars = [
    'current_month_gross_rcpt_amt',
    'current_month_refund_amt',
    'current_month_net_rcpt_amt'
]

df_long = pd.melt(
    df,
    id_vars=id_vars,
    value_vars=value_vars,
    var_name='receipt_type',
    value_name='amount'
)
df = df_long.copy()

df.to_csv("treasury_receipts_long.csv", index=False)

import streamlit as st
import pandas as pd
import plotly.express as px
import os

# ==============================================================================
# 1. PAGE CONFIGURATION
# ==============================================================================
st.set_page_config(
    page_title="US Treasury Receipts Dashboard",
    page_icon="🏦",
    layout="wide"
)

st.title("🏦 Federal Government Receipts Dashboard")
st.markdown("Interactive analysis of federal government revenue collected via the U.S. Treasury.")

# ==============================================================================
# 2. LOCAL CSV DATA INGESTION ENGINE
# ==============================================================================
def format_runtime_dataframe(input_df):
    """
    Applies structural column datatypes and chronological index mappings
    directly to your pre-cleaned in-memory DataFrame object.
    """
    try:
        # Create a safe copy of your upstream variable
        df_clean = input_df.copy()
        
        # Enforce strict visual slicing datetime types
        df_clean['record_date'] = pd.to_datetime(df_clean['record_date'], errors='coerce')
        df_clean['amount'] = pd.to_numeric(df_clean['amount'], errors='coerce').fillna(0)
        
        # Explicitly build chronological calendar dimensions
        df_clean['record_calendar_year'] = df_clean['record_date'].dt.year
        df_clean['record_calendar_month'] = df_clean['record_date'].dt.strftime('%B')
        df_clean['month_num'] = df_clean['record_date'].dt.month
        
        return df_clean
    except Exception as e:
        st.error(f"Error parsing dataframe layout layout schema: {e}")
        return pd.DataFrame()

# 🌟 Automatically process your upstream 'df' structure directly
df = format_runtime_dataframe(df)

if df.empty:
    st.warning("The upstream data structure appears to be empty or missing required schema values.")
    st.stop()

# ==============================================================================
# 3. SIDEBAR SLICERS / FILTERS
# ==============================================================================
st.sidebar.header("🎛️ Dashboard Slicers")

# --- Dynamic Year and Month Slicers ---
all_years = sorted(df['record_calendar_year'].dropna().unique().tolist(), reverse=True)
selected_year = st.sidebar.selectbox("Select Calendar Year", options=all_years, index=0)

# Isolate months available for the selected year and sort chronologically
year_filtered_df = df[df['record_calendar_year'] == selected_year]
unique_months_df = year_filtered_df[['record_calendar_month', 'month_num']].drop_duplicates().sort_values('month_num')
all_months = unique_months_df['record_calendar_month'].tolist()

# Add an option to view the whole year at once
month_options = ["All Months"] + all_months
selected_month = st.sidebar.selectbox("Select Calendar Month", options=month_options, index=0)

# Multi-select Slicer: Classification (Pre-selecting Corporation Income Taxes)
all_classifications = sorted(df['classification_desc'].dropna().unique().tolist())

target_class_default = "Corporation Income Taxes"
if target_class_default in all_classifications:
    class_default_selection = [target_class_default]
else:
    class_default_selection = [all_classifications[0]] if all_classifications else []

selected_classifications = st.sidebar.multiselect(
    "Classification Description", 
    options=all_classifications, 
    default=class_default_selection
)

# Multi-select Slicer: Receipt Type (Pre-selecting current_month_net_rcpt_amt)
all_receipt_types = sorted(df['receipt_type'].dropna().unique().tolist())

target_receipt_default = "current_month_net_rcpt_amt"
if target_receipt_default in all_receipt_types:
    receipt_default_selection = [target_receipt_default]
else:
    # Fallback to all options if the specific column naming varies
    receipt_default_selection = all_receipt_types

selected_receipt_types = st.sidebar.multiselect(
    "Receipt Type", 
    options=all_receipt_types, 
    default=receipt_default_selection  # 🌟 Pre-sets Net Receipts on boot
)

# ==============================================================================
# 4. DATA FILTERING ENGINE
# ==============================================================================
# Base filtering map
filter_mask = (
    (df['record_calendar_year'] == selected_year) &
    (df['classification_desc'].isin(selected_classifications if selected_classifications else all_classifications)) &
    (df['receipt_type'].isin(selected_receipt_types if selected_receipt_types else all_receipt_types))
)

# Apply specific month filter if "All Months" is not selected
if selected_month != "All Months":
    filter_mask = filter_mask & (df['record_calendar_month'] == selected_month)

filtered_df = df[filter_mask]

# ==============================================================================
# 5. KEY PERFORMANCE METRICS (KPIs) - Whole Millions (M) & Y/Y Delta
# ==============================================================================
st.markdown("### 📊 Key Summary Metrics")

# 1. Compute baseline trend averages
avg_monthly_receipts = filtered_df.groupby(['record_calendar_year', 'record_calendar_month'])['amount'].sum().mean()
unique_classes = filtered_df['classification_desc'].nunique()

# 2. Determine timeframe context for Total Receipts
if not filtered_df.empty:
    if selected_month != "All Months":
        # Target the explicitly selected month
        target_month_name = selected_month
        target_year = selected_year
        target_df = filtered_df
        label_suffix = f" ({target_month_name} {target_year})"
    else:
        # Fallback to the maximum month within that year if "All Months" is active
        latest_date = filtered_df['record_date'].max()
        target_month_name = latest_date.strftime('%B')
        target_year = latest_date.year
        target_df = filtered_df[filtered_df['record_calendar_month'] == target_month_name]
        label_suffix = f" (Latest Month: {target_month_name} {target_year})"

    # Calculate Current period total
    total_receipts = target_df['amount'].sum()
    total_receipts_m = total_receipts / 1_000_000

    # Previous year's same calendar month total (Y/Y Context)
    prev_year = target_year - 1
    prev_year_month_df = df[
        (df['record_date'].dt.year == prev_year) & 
        (df['record_date'].dt.strftime('%B') == target_month_name) &
        (df['classification_desc'].isin(selected_classifications if selected_classifications else all_classifications)) &
        (df['receipt_type'].isin(selected_receipt_types if selected_receipt_types else all_receipt_types))
    ]
    prev_total_receipts = prev_year_month_df['amount'].sum()

    # Formulate percentages change logic safely
    if prev_total_receipts > 0:
        pct_change = ((total_receipts - prev_total_receipts) / prev_total_receipts) * 100
        delta_display = f"{pct_change:+.1f}% Y/Y"
    else:
        delta_display = "No historical Y/Y data"
else:
    total_receipts_m = 0
    delta_display = "No data available"
    label_suffix = ""

avg_monthly_receipts_m = avg_monthly_receipts / 1_000_000 if not pd.isna(avg_monthly_receipts) else 0

# Render metric layout cards
col1, col2, col3 = st.columns(3)
with col1:
    st.metric(
        label=f"Total Receipts{label_suffix}", 
        value=f"${total_receipts_m:,.0f}M",
        delta=delta_display
    )
with col2:
    st.metric(label="Avg Monthly Inflow", value=f"${avg_monthly_receipts_m:,.0f}M")
with col3:
    st.metric(label="Active Revenue Streams", value=str(unique_classes))

st.write("---")

# ==============================================================================
# 6. CHARTS SECTION
# ==============================================================================
st.markdown("### 📈 Visual Analytics")
# --- ROW 1: Side-by-Side Calendar Year-over-Year Level vs Growth Analytics ---
if selected_month != "All Months":
    st.markdown(f"#### Historical Year-over-Year Analytics: {selected_month}")
    
    historical_month_df = df[
        (df['record_calendar_month'] == selected_month) &
        (df['classification_desc'].isin(selected_classifications if selected_classifications else all_classifications)) &
        (df['receipt_type'].isin(selected_receipt_types if selected_receipt_types else all_receipt_types))
    ]
    hist_bar_df = historical_month_df.groupby('record_calendar_year', as_index=False)['amount'].sum().sort_values('record_calendar_year')
    hist_bar_df['pct_growth'] = hist_bar_df['amount'].pct_change() * 100

    col_chart_left, col_chart_right = st.columns(2)

    with col_chart_left:
        hist_bar_df['amount_b'] = hist_bar_df['amount'] / 1_000_000_000
        fig_levels = px.bar(
            hist_bar_df,
            x='record_calendar_year',
            y='amount_b',
            title=f"Total Volume ($ Billions) - {selected_month}",
            labels={'amount_b': 'Receipts (Billions USD)', 'record_calendar_year': 'Calendar Year'},
            template="plotly_white"
        )
        fig_levels.update_traces(texttemplate='%{y:,.0f}B', textposition="outside")
        fig_levels.update_layout(xaxis_type='category', yaxis_ticksuffix="B")
        st.plotly_chart(fig_levels, use_container_width=True)

    with col_chart_right:
        growth_df = hist_bar_df.dropna(subset=['pct_growth'])
        fig_growth = px.bar(
            growth_df,
            x='record_calendar_year',
            y='pct_growth',
            title=f"Year-over-Year Growth Rate (%) - {selected_month}",
            labels={'pct_growth': 'YoY Growth (%)', 'record_calendar_year': 'Calendar Year'},
            template="plotly_white",
            color='pct_growth',
            color_continuous_scale=['#EF553B', '#636EFA']
        )
        fig_growth.update_traces(texttemplate='%{y:+.1f}%', textposition="outside")
        fig_growth.update_layout(xaxis_type='category', yaxis_ticksuffix="%", coloraxis_showscale=False)
        st.plotly_chart(fig_growth, use_container_width=True)

else:
    st.markdown("#### Macro Historical Trend: Annual Receipts")
    macro_year_df = df[
        (df['classification_desc'].isin(selected_classifications if selected_classifications else all_classifications)) &
        (df['receipt_type'].isin(selected_receipt_types if selected_receipt_types else all_receipt_types))
    ]
    hist_macro_df = macro_year_df.groupby('record_calendar_year', as_index=False)['amount'].sum().sort_values('record_calendar_year')
    
    col_chart_left, col_chart_right = st.columns(2)
    
    with col_chart_left:
        hist_macro_df['amount_b'] = hist_macro_df['amount'] / 1_000_000_000
        fig_macro_lvl = px.bar(
            hist_macro_df,
            x='record_calendar_year',
            y='amount_b',
            title="Total Annual Volume ($ Billions)",
            labels={'amount_b': 'Annual Receipts (Billions USD)', 'record_calendar_year': 'Calendar Year'},
            template="plotly_white"
        )
        fig_macro_lvl.update_traces(texttemplate='%{y:,.0f}B', textposition="outside")
        fig_macro_lvl.update_layout(xaxis_type='category', yaxis_ticksuffix="B")
        st.plotly_chart(fig_macro_lvl, use_container_width=True)
        
    with col_chart_right:
        hist_macro_df['pct_growth'] = hist_macro_df['amount'].pct_change() * 100
        macro_growth_df = hist_macro_df.dropna(subset=['pct_growth'])
        fig_macro_gr = px.bar(
            macro_growth_df,
            x='record_calendar_year',
            y='pct_growth',
            title="Annual Year-over-Year Growth Rate (%)",
            labels={'pct_growth': 'YoY Growth (%)', 'record_calendar_year': 'Calendar Year'},
            template="plotly_white",
            color='pct_growth',
            color_continuous_scale=['#EF553B', '#636EFA']
        )
        fig_macro_gr.update_traces(texttemplate='%{y:+.1f}%', textposition="outside")
        fig_macro_gr.update_layout(xaxis_type='category', yaxis_ticksuffix="%", coloraxis_showscale=False)
        st.plotly_chart(fig_macro_gr, use_container_width=True)

st.write("---")

# --- ROW 2: Side-by-Side Cumulative Calendar Year YTD Levels vs Growth ---
if selected_month != "All Months":
    st.markdown(f"#### Multi-Year Cumulative Calendar YTD Analytics (Jan - {selected_month})")
    selected_month_num = int(df[df['record_calendar_month'] == selected_month]['month_num'].iloc[0])
    
    multi_ytd_df = df[
        (df['month_num'] <= selected_month_num) &
        (df['classification_desc'].isin(selected_classifications if selected_classifications else all_classifications)) &
        (df['receipt_type'].isin(selected_receipt_types if selected_receipt_types else all_receipt_types))
    ]
else:
    st.markdown("#### Cumulative Analytics Across Full Calendar Years")
    multi_ytd_df = df[
        (df['classification_desc'].isin(selected_classifications if selected_classifications else all_classifications)) &
        (df['receipt_type'].isin(selected_receipt_types if selected_receipt_types else all_receipt_types))
    ].copy()

ytd_timeline = multi_ytd_df.groupby(['record_calendar_year', 'month_num', 'record_calendar_month', 'receipt_type'], as_index=False)['amount'].sum()
ytd_timeline = ytd_timeline.sort_values(['record_calendar_year', 'receipt_type', 'month_num'])

ytd_timeline['cumulative_amount'] = ytd_timeline.groupby(['record_calendar_year', 'receipt_type'])['amount'].cumsum()
ytd_timeline['cumulative_amount_b'] = ytd_timeline['cumulative_amount'] / 1_000_000_000

all_available_types = sorted(ytd_timeline['receipt_type'].unique().tolist())
if all_available_types:
    # 🌟 Calculate default index for net receipts safely
    target_radio_default = "current_month_net_rcpt_amt"
    calendar_radio_idx = all_available_types.index(target_radio_default) if target_radio_default in all_available_types else 0

    selected_stream_visual = st.radio(
        "Select Cumulative Receipt Type Series to Focus Visualizations:", 
        options=all_available_types, 
        horizontal=True,
        index=calendar_radio_idx,  # Default selection assigned here
        key="calendar_ytd_radio"
    )
    
    chart_ytd_df = ytd_timeline[ytd_timeline['receipt_type'] == selected_stream_visual]
    col_ytd_left, col_ytd_right = st.columns(2)
    
    with col_ytd_left:
        fig_trend = px.line(
            chart_ytd_df, 
            x='record_calendar_month', 
            y='cumulative_amount_b', 
            color='record_calendar_year',
            title=f"Calendar YTD Cumulative Progression ($ Billions)",
            labels={'cumulative_amount_b': 'Aggregated Volume (Billions)', 'record_calendar_month': 'Months Timeline', 'record_calendar_year': 'Year'},
            markers=True,
            template="plotly_white"
        )
        fig_trend.update_layout(yaxis_ticksuffix="B", xaxis={'categoryorder':'array', 'categoryarray': ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']})
        st.plotly_chart(fig_trend, use_container_width=True)
        
    with col_ytd_right:
        if not chart_ytd_df.empty:
            max_month_reached = chart_ytd_df['month_num'].max()
            ytd_caps_df = chart_ytd_df[chart_ytd_df['month_num'] == max_month_reached].sort_values('record_calendar_year')
            ytd_caps_df['ytd_pct_growth'] = ytd_caps_df['cumulative_amount'].pct_change() * 100
            ytd_growth_clean_df = ytd_caps_df.dropna(subset=['ytd_pct_growth'])
            
            fig_ytd_growth = px.bar(
                ytd_growth_clean_df,
                x='record_calendar_year',
                y='ytd_pct_growth',
                title=f"Total Calendar YTD YoY Growth Rate (%) through {selected_month if selected_month != 'All Months' else 'December'}",
                labels={'ytd_pct_growth': 'YTD YoY Growth (%)', 'record_calendar_year': 'Calendar Year'},
                template="plotly_white",
                color='ytd_pct_growth',
                color_continuous_scale=['#EF553B', '#636EFA']
            )
            fig_ytd_growth.update_traces(texttemplate='%{y:+.1f}%', textposition="outside")
            fig_ytd_growth.update_layout(xaxis_type='category', yaxis_ticksuffix="%", coloraxis_showscale=False)
            st.plotly_chart(fig_ytd_growth, use_container_width=True)

st.write("---")

# --- ROW 3: Side-by-Side Cumulative Federal Fiscal Year YTD Levels vs Growth ---
if selected_month != "All Months":
    st.markdown(f"#### Multi-Year Cumulative Federal Fiscal YTD Analytics (Oct - {selected_month})")
    
    fiscal_month_order = {10:1, 11:2, 12:3, 1:4, 2:5, 3:6, 4:7, 5:8, 6:9, 7:10, 8:11, 9:12}
    selected_month_raw_num = int(df[df['record_calendar_month'] == selected_month]['month_num'].iloc[0])
    selected_fiscal_order_num = fiscal_month_order[selected_month_raw_num]
    
    df['fiscal_month_order_idx'] = df['month_num'].map(fiscal_month_order)
    
    multi_fy_ytd_df = df[
        (df['fiscal_month_order_idx'] <= selected_fiscal_order_num) &
        (df['classification_desc'].isin(selected_classifications if selected_classifications else all_classifications)) &
        (df['receipt_type'].isin(selected_receipt_types if selected_receipt_types else all_receipt_types))
    ]
else:
    st.markdown("#### Cumulative Analytics Across Full Federal Fiscal Years")
    df['fiscal_month_order_idx'] = df['month_num'].map({10:1, 11:2, 12:3, 1:4, 2:5, 3:6, 4:7, 5:8, 6:9, 7:10, 8:11, 9:12})
    multi_fy_ytd_df = df[
        (df['classification_desc'].isin(selected_classifications if selected_classifications else all_classifications)) &
        (df['receipt_type'].isin(selected_receipt_types if selected_receipt_types else all_receipt_types))
    ].copy()

if not multi_fy_ytd_df.empty and 'record_fiscal_year' in multi_fy_ytd_df.columns:
    multi_fy_ytd_df = multi_fy_ytd_df.dropna(subset=['record_fiscal_year'])
    fy_ytd_timeline = multi_fy_ytd_df.groupby(['record_fiscal_year', 'fiscal_month_order_idx', 'record_calendar_month', 'receipt_type'], as_index=False)['amount'].sum()
    fy_ytd_timeline = fy_ytd_timeline.sort_values(['record_fiscal_year', 'receipt_type', 'fiscal_month_order_idx'])
    fy_ytd_timeline['cumulative_amount'] = fy_ytd_timeline.groupby(['record_fiscal_year', 'receipt_type'])['amount'].cumsum()
    fy_ytd_timeline['cumulative_amount_b'] = fy_ytd_timeline['cumulative_amount'] / 1_000_000_000
# 🌟 Calculate default index for fiscal net receipts safely
fiscal_radio_idx = all_available_types.index(target_radio_default) if target_radio_default in all_available_types else 0
selected_fy_stream = st.radio(
	"Select Cumulative Fiscal Receipt Type Series to Focus Visualizations:",
	options=all_available_types,
	horizontal=True,
	index=fiscal_radio_idx,  # Default selection assigned here
	key="fiscal_ytd_radio"
	)


chart_fy_df = fy_ytd_timeline[fy_ytd_timeline['receipt_type'] == selected_fy_stream]
col_fy_left, col_fy_right = st.columns(2)

with col_fy_left:
    fig_fy_trend = px.line(
        chart_fy_df,
        x='record_calendar_month',
        y='cumulative_amount_b',
        color='record_fiscal_year',
        title="Federal Fiscal YTD Cumulative Progression ($ Billions)",
        labels={'cumulative_amount_b': 'Aggregated Volume (Billions)', 'record_calendar_month': 'Fiscal Months Timeline', 'record_fiscal_year': 'Federal Fiscal Year'},
        markers=True,
        template="plotly_white"
    )
    fig_fy_trend.update_layout(yaxis_ticksuffix="B", xaxis={'categoryorder':'array', 'categoryarray': ['October', 'November', 'December', 'January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September']})
    st.plotly_chart(fig_fy_trend, use_container_width=True)

with col_fy_right:
    if not chart_fy_df.empty:
        max_fy_month_reached = chart_fy_df['fiscal_month_order_idx'].max()
        fy_caps_df = chart_fy_df[chart_fy_df['fiscal_month_order_idx'] == max_fy_month_reached].sort_values('record_fiscal_year')
        fy_caps_df['fy_pct_growth'] = fy_caps_df['cumulative_amount'].pct_change() * 100
        fy_growth_clean_df = fy_caps_df.dropna(subset=['fy_pct_growth'])
        
        fig_fy_growth = px.bar(
            fy_growth_clean_df,
            x='record_fiscal_year',
            y='fy_pct_growth',
            title=f"Total Fiscal YTD YoY Growth Rate (%) through {selected_month if selected_month != 'All Months' else 'September'}",
            labels={'fy_pct_growth': 'Fiscal YTD YoY Growth (%)', 'record_fiscal_year': 'Federal Fiscal Year'},
            template="plotly_white",
            color='fy_pct_growth',
            color_continuous_scale=['#EF553B', '#636EFA']
        )
        fig_fy_growth.update_traces(texttemplate='%{y:+.1f}%', textposition="outside")
        fig_fy_growth.update_layout(xaxis_type='category', yaxis_ticksuffix="%", coloraxis_showscale=False)
        st.plotly_chart(fig_fy_growth, use_container_width=True)

st.write("---")

# ==============================================================================
# 7. UNIFIED DATA DOWNLOAD TERMINAL (BOTTOM OF PAGE)
# ==============================================================================
st.write("---")
st.markdown("### 🔍 Unified Data Export Hub")

with st.expander("📂 View / Export Data Tables Associated with This Dashboard", expanded=False):
    # Establish distinct tabs for structural isolation
    tab_full, tab_yoy, tab_cal_ytd, tab_fisc_ytd = st.tabs([
        "📊 Full Filtered Dataset", 
        "📈 YoY Chart Data (Row 1)", 
        "📅 Calendar YTD Data (Row 2)", 
        "🏦 Fiscal YTD Data (Row 3)"
    ])
    
    # --- TAB 1: Full Filtered Dataset ---
    with tab_full:
        st.markdown("#### Complete Filtered Records Snapshot")
        st.dataframe(filtered_df, use_container_width=True)
        st.download_button(
            label="📥 Download Full Filtered Dataset as CSV",
            data=filtered_df.to_csv(index=False).encode('utf-8'),
            file_name="filtered_treasury_receipts.csv",
            mime="text/csv",
            key="download_full_dataset_btn"
        )
        
    # --- TAB 2: Row 1 Chart Data ---
    with tab_yoy:
        st.markdown(f"#### Underlying Metrics for Year-over-Year Analytics ({selected_month})")
        if 'hist_bar_df' in locals() and not hist_bar_df.empty:
            display_row1_df = hist_bar_df[['record_calendar_year', 'amount_b', 'pct_growth']].copy()
            display_row1_df = display_row1_df.rename(columns={
                'record_calendar_year': 'Calendar Year',
                'amount_b': 'Total Volume (Billions USD)',
                'pct_growth': 'YoY Growth Rate (%)'
            })
            st.dataframe(display_row1_df, use_container_width=True)
            st.download_button(
                label="📥 Download YoY Chart Metrics as CSV",
                data=display_row1_df.to_csv(index=False).encode('utf-8'),
                file_name=f"yoy_receipts_chart_metrics_{selected_month}.csv",
                mime="text/csv",
                key="download_row1_hub_btn"
            )
        else:
            st.info("Select a single calendar month in the sidebar to review YoY metric rows.")

    # --- TAB 3: Row 2 Chart Data ---
    with tab_cal_ytd:
        st.markdown("#### Underlying Metrics for Calendar YTD Progressive Tracking")
        if 'chart_ytd_df' in locals() and not chart_ytd_df.empty:
            display_row2_df = chart_ytd_df[['record_calendar_year', 'record_calendar_month', 'cumulative_amount_b']].copy()
            display_row2_df = display_row2_df.rename(columns={
                'record_calendar_year': 'Calendar Year',
                'record_calendar_month': 'Month',
                'cumulative_amount_b': 'Cumulative Receipts YTD (Billions USD)'
            })
            st.dataframe(display_row2_df, use_container_width=True)
            st.download_button(
                label="📥 Download Calendar YTD Chart Metrics as CSV",
                data=display_row2_df.to_csv(index=False).encode('utf-8'),
                file_name=f"calendar_ytd_chart_metrics_{selected_month}.csv",
                mime="text/csv",
                key="download_row2_hub_btn"
            )
        else:
            st.info("No active Calendar YTD tracking data available.")

    # --- TAB 4: Row 3 Chart Data ---
    with tab_fisc_ytd:
        st.markdown("#### Underlying Metrics for Federal Fiscal YTD Progressive Tracking")
        if 'chart_fy_df' in locals() and not chart_fy_df.empty:
            display_row3_df = chart_fy_df[['record_fiscal_year', 'record_calendar_month', 'cumulative_amount_b']].copy()
            display_row3_df = display_row3_df.rename(columns={
                'record_fiscal_year': 'Federal Fiscal Year',
                'record_calendar_month': 'Month',
                'cumulative_amount_b': 'Cumulative Fiscal Receipts YTD (Billions USD)'
            })
            st.dataframe(display_row3_df, use_container_width=True)
            st.download_button(
                label="📥 Download Fiscal YTD Chart Metrics as CSV",
                data=display_row3_df.to_csv(index=False).encode('utf-8'),
                file_name=f"fiscal_ytd_chart_metrics_{selected_month}.csv",
                mime="text/csv",
                key="download_row3_hub_btn"
            )
        else:
            st.info("No active Federal Fiscal YTD tracking data available.")

