import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import requests
import io
from datetime import datetime

# ── Theme ─────────────────────────────────────────────────────────────────────
DM_BG       = "#0e1614"
DM_SURFACE  = "#162019"
DM_SURFACE2 = "#1e2e2a"
DM_BORDER   = "#243328"
DM_TEXT     = "#e4e8f0"
DM_MUTED    = "#7a9990"
JPSI_GREEN  = "#4ade80"

CLASS_COLORS = {
    "STEERS":    "#4ade80",
    "HEIFERS":   "#60a5fa",
    "COWS":      "#f97316",
    "BULLS":     "#a78bfa",
    "CALVES":    "#fbbf24",
    "GE 500 LBS": "#e4e8f0",
}

try:
    API_KEY = st.secrets.get("NASS_API_KEY", "9A6D1EB8-4D94-3221-BA0C-ADD4533EA0C1")
except Exception:
    API_KEY = "9A6D1EB8-4D94-3221-BA0C-ADD4533EA0C1"
BASE_URL = "https://quickstats.nass.usda.gov/api/api_GET/"

CLASSES_WEIGHT = ["GE 500 LBS", "STEERS", "HEIFERS", "COWS", "BULLS", "CALVES"]
CLASSES_VOLUME = ["GE 500 LBS", "STEERS", "HEIFERS", "COWS", "BULLS", "CALVES"]

st.set_page_config(
    page_title="Beef Weight Dashboard",
    page_icon="🐂",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(f"""
<style>
  html, body, [data-testid="stAppViewContainer"] {{
    background-color: {DM_BG}; color: {DM_TEXT};
  }}
  [data-testid="stSidebar"] {{
    background-color: {DM_SURFACE};
    border-right: 1px solid {DM_BORDER};
  }}
  [data-testid="stSidebar"] * {{ color: {DM_TEXT} !important; }}
  .metric-card {{
    background: {DM_SURFACE}; border: 1px solid {DM_BORDER};
    border-radius: 8px; padding: 16px 20px; text-align: center;
  }}
  .metric-label {{ color: {DM_MUTED}; font-size: 0.78rem; text-transform: uppercase;
    letter-spacing: 0.06em; margin-bottom: 4px; }}
  .metric-value {{ color: {DM_TEXT}; font-size: 1.6rem; font-weight: 700; }}
  .metric-delta-pos {{ color: #4ade80; font-size: 0.85rem; }}
  .metric-delta-neg {{ color: #f87171; font-size: 0.85rem; }}
  .metric-delta-neu {{ color: {DM_MUTED}; font-size: 0.85rem; }}
  .section-header {{ color: {DM_MUTED}; font-size: 0.75rem; text-transform: uppercase;
    letter-spacing: 0.1em; margin: 8px 0 4px; }}
  div[data-testid="stDataFrame"] {{ background: {DM_SURFACE}; border-radius: 8px; }}
  .stTabs [data-baseweb="tab-list"] {{ background: {DM_SURFACE}; border-radius: 8px; }}
  .stTabs [data-baseweb="tab"] {{ color: {DM_MUTED}; }}
  .stTabs [aria-selected="true"] {{ color: {JPSI_GREEN} !important; }}
  h1, h2, h3 {{ color: {DM_TEXT}; }}
</style>
""", unsafe_allow_html=True)


# ── Data fetching ─────────────────────────────────────────────────────────────

def _nass_get(params: dict) -> dict:
    for attempt in range(3):
        try:
            r = requests.get(BASE_URL, params=params, timeout=60)
            return r.json()
        except requests.exceptions.Timeout:
            if attempt < 2:
                continue
        except Exception:
            pass
    return {}


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_slaughter_weights(years: tuple) -> pd.DataFrame:
    frames = []
    for year in years:
        params = {
            "key":               API_KEY,
            "source_desc":       "SURVEY",
            "sector_desc":       "ANIMALS & PRODUCTS",
            "group_desc":        "LIVESTOCK",
            "commodity_desc":    "CATTLE",
            "statisticcat_desc": "SLAUGHTERED",
            "freq_desc":         "WEEKLY",
            "state_alpha":       "US",
            "year":              year,
            "format":            "JSON",
        }
        payload = _nass_get(params)
        if "data" in payload and payload["data"]:
            frames.append(pd.DataFrame(payload["data"]))

    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)
    keep = ["year", "week_ending", "class_desc", "unit_desc", "Value", "reference_period_desc"]
    df = df[[c for c in keep if c in df.columns]].copy()
    df["Value"]       = pd.to_numeric(df["Value"].astype(str).str.replace(",", "", regex=False), errors="coerce")
    df["week_ending"] = pd.to_datetime(df["week_ending"], errors="coerce")
    df["year"]        = df["year"].astype(int)
    df["class_desc"]  = df["class_desc"].str.upper().str.strip()
    df["unit_desc"]   = df["unit_desc"].str.strip()
    df = df.dropna(subset=["Value", "week_ending"])
    return df


def weight_df(raw: pd.DataFrame, unit: str) -> pd.DataFrame:
    return raw[raw["unit_desc"].str.contains(unit, case=False, na=False)].copy()


def volume_df(raw: pd.DataFrame) -> pd.DataFrame:
    return raw[raw["unit_desc"].str.strip().str.upper() == "HEAD"].copy()


def _pivot_by_class(df: pd.DataFrame, classes: list, value_col: str = "Value") -> pd.DataFrame:
    df = df[df["class_desc"].isin(classes)].copy()
    return df.pivot_table(
        index=["year", "week_ending"], columns="class_desc",
        values=value_col, aggfunc="mean"
    ).reset_index()


def compute_kpis(df: pd.DataFrame, class_desc: str) -> dict:
    sub = df[df["class_desc"] == class_desc].sort_values("week_ending")
    nan4 = {"current": float("nan"), "wow": float("nan"), "yoy": float("nan"), "avg5": float("nan")}
    if sub.empty:
        return nan4
    latest_date = sub["week_ending"].max()
    latest_year = sub.loc[sub["week_ending"] == latest_date, "year"].iloc[0]
    current     = sub.loc[sub["week_ending"] == latest_date, "Value"].iloc[0]

    # WoW
    prev_week = sub[sub["week_ending"] < latest_date]["week_ending"].max()
    wow = current - sub.loc[sub["week_ending"] == prev_week, "Value"].iloc[0] if pd.notna(prev_week) else float("nan")

    # YoY — same week number last year
    wk_num = latest_date.isocalendar().week
    ly = sub[sub["year"] == latest_year - 1]
    ly_wk = ly.iloc[(ly["week_ending"].apply(lambda d: d.isocalendar().week) - wk_num).abs().argsort()]
    yoy = current - ly_wk.iloc[0]["Value"] if not ly_wk.empty else float("nan")

    # 5-yr avg for same week
    avg5_years = range(latest_year - 5, latest_year)
    vals = []
    for yr in avg5_years:
        yrdf = sub[sub["year"] == yr]
        wks  = yrdf.iloc[(yrdf["week_ending"].apply(lambda d: d.isocalendar().week) - wk_num).abs().argsort()]
        if not wks.empty:
            vals.append(wks.iloc[0]["Value"])
    avg5 = sum(vals) / len(vals) if vals else float("nan")
    return {"current": current, "wow": wow, "yoy": yoy, "avg5": avg5}


def _delta_html(val: float, unit: str = "lb") -> str:
    if pd.isna(val):
        return f'<div class="metric-delta-neu">— {unit}</div>'
    color_cls = "metric-delta-pos" if val >= 0 else "metric-delta-neg"
    sign = "+" if val >= 0 else ""
    return f'<div class="{color_cls}">{sign}{val:.1f} {unit}</div>'


def _metric_card(label: str, value: str, delta_html: str) -> str:
    return f"""
    <div class="metric-card">
      <div class="metric-label">{label}</div>
      <div class="metric-value">{value}</div>
      {delta_html}
    </div>
    """


AXIS_STYLE = dict(gridcolor=DM_BORDER, linecolor=DM_BORDER, showgrid=True)


def _chart_layout(title: str = "") -> dict:
    return dict(
        title=dict(text=title, font=dict(color=DM_TEXT, size=14), x=0),
        paper_bgcolor=DM_SURFACE2,
        plot_bgcolor=DM_SURFACE2,
        font=dict(color=DM_TEXT, size=11),
        legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor=DM_BORDER, borderwidth=0),
        margin=dict(l=50, r=20, t=40, b=40),
        hovermode="x unified",
    )


def _apply_chart(fig, title: str = "", height: int = 420, y_title: str = ""):
    fig.update_layout(**_chart_layout(title), height=height)
    fig.update_xaxes(**AXIS_STYLE)
    fig.update_yaxes(**AXIS_STYLE, title_text=y_title)


def _to_excel(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False)
    return buf.getvalue()


# ── Sidebar ───────────────────────────────────────────────────────────────────

st.sidebar.image(
    "https://upload.wikimedia.org/wikipedia/commons/thumb/7/7d/USDA_logo.svg/100px-USDA_logo.svg.png",
    width=60,
)
st.sidebar.markdown(f"### Beef Weight Dashboard")
st.sidebar.markdown(f'<span style="color:{DM_MUTED}; font-size:0.75rem;">Source: USDA NASS QuickStats</span>', unsafe_allow_html=True)
st.sidebar.divider()

current_year = datetime.now().year
all_years    = list(range(2000, current_year + 1))
default_start = max(2015, min(all_years))

year_range = st.sidebar.slider(
    "Year Range",
    min_value=2000,
    max_value=current_year,
    value=(default_start, current_year),
    step=1,
)
selected_years = tuple(range(year_range[0], year_range[1] + 1))

st.sidebar.divider()
st.sidebar.markdown('<div class="section-header">Weight Metric</div>', unsafe_allow_html=True)
weight_unit = st.sidebar.radio(
    "Basis",
    ["Dressed Weight", "Live Weight"],
    label_visibility="collapsed",
)
unit_filter = "DRESSED" if weight_unit == "Dressed Weight" else "LIVE"

st.sidebar.divider()
st.sidebar.markdown('<div class="section-header">Classes</div>', unsafe_allow_html=True)
selected_classes = st.sidebar.multiselect(
    "Classes",
    CLASSES_WEIGHT,
    default=["GE 500 LBS", "STEERS", "HEIFERS"],
    label_visibility="collapsed",
)
if not selected_classes:
    selected_classes = ["GE 500 LBS"]

st.sidebar.divider()
overlay_years_back = st.sidebar.slider("Years to overlay on chart", 1, 10, 5)


# ── Load data ─────────────────────────────────────────────────────────────────

with st.spinner("Loading USDA NASS data…"):
    raw = fetch_slaughter_weights(selected_years)

if raw.empty:
    st.error("No data returned from USDA NASS. Check your API key in st.secrets.")
    st.stop()

wt_df = weight_df(raw, unit_filter)
vol_df_raw = volume_df(raw)


# ── Header ────────────────────────────────────────────────────────────────────

st.markdown(f"""
<h1 style="margin-bottom:0">🐂 Beef Slaughter Weight Dashboard</h1>
<p style="color:{DM_MUTED}; margin-top:4px">
  Weekly federally-inspected commercial slaughter weights &nbsp;·&nbsp;
  USDA NASS QuickStats &nbsp;·&nbsp;
  Updated weekly
</p>
""", unsafe_allow_html=True)
st.divider()


# ── KPI row ───────────────────────────────────────────────────────────────────

kpi_classes = ["GE 500 LBS", "STEERS", "HEIFERS", "COWS"]
kpi_cols = st.columns(len(kpi_classes))
for col, cls in zip(kpi_cols, kpi_classes):
    sub = wt_df[wt_df["class_desc"] == cls]
    if sub.empty:
        with col:
            st.markdown(_metric_card(cls, "N/A", ""), unsafe_allow_html=True)
        continue
    kpi = compute_kpis(wt_df, cls)
    value_str = f"{kpi['current']:,.0f} lb" if pd.notna(kpi["current"]) else "N/A"
    label = f"{cls.title()} ({weight_unit[:7]})"
    with col:
        wow_html  = _delta_html(kpi["wow"])
        avg5_str  = f'<div class="metric-delta-neu">5yr avg: {kpi["avg5"]:,.0f} lb</div>' if pd.notna(kpi["avg5"]) else ""
        st.markdown(_metric_card(label, value_str, wow_html + avg5_str), unsafe_allow_html=True)


# ── Tabs ──────────────────────────────────────────────────────────────────────

tab_wt, tab_vol, tab_yoy, tab_data = st.tabs([
    "📈 Weight Trends", "🔢 Slaughter Volume", "📊 Year-over-Year", "📋 Data Table"
])


# ── Tab 1 — Weight Trends ─────────────────────────────────────────────────────

with tab_wt:
    if wt_df.empty:
        st.warning(f"No {weight_unit.lower()} data found for the selected years/classes.")
    else:
        fig = go.Figure()
        for cls in selected_classes:
            cls_data = wt_df[wt_df["class_desc"] == cls].sort_values("week_ending")
            if cls_data.empty:
                continue
            fig.add_trace(go.Scatter(
                x=cls_data["week_ending"],
                y=cls_data["Value"],
                name=cls.title(),
                mode="lines",
                line=dict(color=CLASS_COLORS.get(cls, DM_MUTED), width=2),
                hovertemplate="%{y:,.0f} lb<extra>%{fullData.name}</extra>",
            ))
        _apply_chart(fig, f"Weekly Avg {weight_unit} — Federally Inspected Commercial", 420, "lb / head")
        st.plotly_chart(fig, use_container_width=True)

        # Rolling 4-week avg overlay
        st.markdown(f'<div class="section-header">4-Week Rolling Average</div>', unsafe_allow_html=True)
        fig2 = go.Figure()
        for cls in selected_classes:
            cls_data = wt_df[wt_df["class_desc"] == cls].sort_values("week_ending").copy()
            if cls_data.empty:
                continue
            cls_data["rolling4"] = cls_data["Value"].rolling(4).mean()
            fig2.add_trace(go.Scatter(
                x=cls_data["week_ending"],
                y=cls_data["rolling4"],
                name=cls.title(),
                mode="lines",
                line=dict(color=CLASS_COLORS.get(cls, DM_MUTED), width=2.5),
                hovertemplate="%{y:,.0f} lb<extra>%{fullData.name} (4wk avg)</extra>",
            ))
        _apply_chart(fig2, "4-Week Rolling Average", 360, "lb / head")
        st.plotly_chart(fig2, use_container_width=True)


# ── Tab 2 — Slaughter Volume ──────────────────────────────────────────────────

with tab_vol:
    if vol_df_raw.empty:
        st.warning("No slaughter volume data found.")
    else:
        vol_classes = st.multiselect(
            "Classes to display",
            CLASSES_VOLUME,
            default=["GE 500 LBS", "STEERS", "HEIFERS"],
            key="vol_classes",
        )
        if not vol_classes:
            vol_classes = ["GE 500 LBS"]

        fig3 = go.Figure()
        for cls in vol_classes:
            cls_data = vol_df_raw[vol_df_raw["class_desc"] == cls].sort_values("week_ending")
            if cls_data.empty:
                continue
            fig3.add_trace(go.Scatter(
                x=cls_data["week_ending"],
                y=cls_data["Value"],
                name=cls.title(),
                mode="lines",
                line=dict(color=CLASS_COLORS.get(cls, DM_MUTED), width=2),
                hovertemplate="%{y:,.0f} head<extra>%{fullData.name}</extra>",
            ))
        _apply_chart(fig3, "Weekly Federally Inspected Commercial Slaughter — Head Count", 420, "Head")
        st.plotly_chart(fig3, use_container_width=True)

        # Latest week volume breakdown
        latest_vol_date = vol_df_raw["week_ending"].max()
        latest_vol = vol_df_raw[
            (vol_df_raw["week_ending"] == latest_vol_date) &
            (vol_df_raw["class_desc"].isin(["STEERS", "HEIFERS", "COWS", "BULLS", "CALVES"]))
        ].copy()
        if not latest_vol.empty:
            st.markdown(f'<div class="section-header">Week of {latest_vol_date.strftime("%B %d, %Y")} — Class Breakdown</div>', unsafe_allow_html=True)
            fig4 = go.Figure(go.Pie(
                labels=latest_vol["class_desc"].str.title(),
                values=latest_vol["Value"],
                marker_colors=[CLASS_COLORS.get(c, DM_MUTED) for c in latest_vol["class_desc"]],
                hole=0.45,
                textinfo="label+percent",
                hovertemplate="%{label}: %{value:,.0f} head (%{percent})<extra></extra>",
            ))
            fig4.update_layout(
                paper_bgcolor=DM_SURFACE2,
                plot_bgcolor=DM_SURFACE2,
                font=dict(color=DM_TEXT),
                showlegend=False,
                height=320,
                margin=dict(l=20, r=20, t=20, b=20),
            )
            st.plotly_chart(fig4, use_container_width=True)


# ── Tab 3 — Year-over-Year Overlay ────────────────────────────────────────────

with tab_yoy:
    yoy_class = st.selectbox(
        "Class",
        [c for c in CLASSES_WEIGHT if not wt_df[wt_df["class_desc"] == c].empty],
        index=0,
        key="yoy_class",
    )

    yoy_data = wt_df[wt_df["class_desc"] == yoy_class].copy()
    if yoy_data.empty:
        st.warning("No data for selected class.")
    else:
        yoy_data["day_of_year"] = yoy_data["week_ending"].dt.dayofyear
        yoy_data["month_day"]   = yoy_data["week_ending"].dt.strftime("%-m/%-d")

        latest_yr  = yoy_data["year"].max()
        overlay_yr = list(range(latest_yr - overlay_years_back, latest_yr + 1))
        overlay_yr = [y for y in overlay_yr if y in yoy_data["year"].unique()]

        fig5 = go.Figure()
        for yr in overlay_yr:
            yr_data = yoy_data[yoy_data["year"] == yr].sort_values("day_of_year")
            if yr_data.empty:
                continue
            is_current = yr == latest_yr
            fig5.add_trace(go.Scatter(
                x=yr_data["day_of_year"],
                y=yr_data["Value"],
                name=str(yr),
                mode="lines",
                line=dict(
                    color=JPSI_GREEN if is_current else None,
                    width=2.5 if is_current else 1.2,
                    dash="solid" if is_current else "dot",
                ),
                opacity=1.0 if is_current else 0.55,
                hovertemplate=f"{yr}: %{{y:,.0f}} lb<extra></extra>",
            ))

        # 5yr avg band
        avg5_data = yoy_data[yoy_data["year"].isin(range(latest_yr - 5, latest_yr))]
        if not avg5_data.empty:
            avg_by_doy = avg5_data.groupby("day_of_year")["Value"].agg(["mean", "std"]).reset_index()
            fig5.add_trace(go.Scatter(
                x=pd.concat([avg_by_doy["day_of_year"], avg_by_doy["day_of_year"][::-1]]),
                y=pd.concat([avg_by_doy["mean"] + avg_by_doy["std"],
                             (avg_by_doy["mean"] - avg_by_doy["std"])[::-1]]),
                fill="toself",
                fillcolor=f"rgba(74,222,128,0.08)",
                line=dict(color="rgba(0,0,0,0)"),
                name="±1 Std Dev (5yr)",
                showlegend=True,
                hoverinfo="skip",
            ))
            fig5.add_trace(go.Scatter(
                x=avg_by_doy["day_of_year"],
                y=avg_by_doy["mean"],
                name="5yr Avg",
                mode="lines",
                line=dict(color=f"rgba(74,222,128,0.5)", width=1.5, dash="dash"),
                hovertemplate="5yr avg: %{y:,.0f} lb<extra></extra>",
            ))

        month_ticks = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335]
        month_labels = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
        _apply_chart(fig5, f"Year-over-Year — {yoy_class.title()} {weight_unit}", 460, "lb / head")
        fig5.update_xaxes(tickmode="array", tickvals=month_ticks, ticktext=month_labels)
        st.plotly_chart(fig5, use_container_width=True)

        # YoY delta chart
        if latest_yr - 1 in yoy_data["year"].unique():
            curr_yr_data = yoy_data[yoy_data["year"] == latest_yr].set_index("day_of_year")["Value"]
            prev_yr_data = yoy_data[yoy_data["year"] == latest_yr - 1].set_index("day_of_year")["Value"]
            delta        = (curr_yr_data - prev_yr_data).dropna().reset_index()
            delta.columns = ["day_of_year", "delta"]

            fig6 = go.Figure(go.Bar(
                x=delta["day_of_year"],
                y=delta["delta"],
                marker_color=[JPSI_GREEN if v >= 0 else "#f87171" for v in delta["delta"]],
                hovertemplate="%{y:+.1f} lb vs prior year<extra></extra>",
            ))
            fig6.add_hline(y=0, line_color=DM_BORDER)
            _apply_chart(fig6, f"{latest_yr} vs {latest_yr-1} — Weekly \u0394 lb/head", 280, "\u0394 lb / head")
            fig6.update_xaxes(tickmode="array", tickvals=month_ticks, ticktext=month_labels)
            st.plotly_chart(fig6, use_container_width=True)


# ── Tab 4 — Data Table ────────────────────────────────────────────────────────

with tab_data:
    col_a, col_b = st.columns([2, 1])
    with col_a:
        tbl_classes = st.multiselect(
            "Filter by class",
            CLASSES_WEIGHT,
            default=["GE 500 LBS", "STEERS", "HEIFERS"],
            key="tbl_classes",
        )
    with col_b:
        tbl_unit = st.selectbox(
            "Unit",
            ["LB / HEAD, DRESSED BASIS", "LB / HEAD, LIVE BASIS", "HEAD"],
            key="tbl_unit",
        )

    tbl_df = raw[
        (raw["class_desc"].isin(tbl_classes if tbl_classes else CLASSES_WEIGHT)) &
        (raw["unit_desc"] == tbl_unit)
    ][["year", "week_ending", "class_desc", "unit_desc", "Value"]].copy()

    tbl_df = tbl_df.sort_values(["week_ending", "class_desc"], ascending=[False, True])
    tbl_df.columns = ["Year", "Week Ending", "Class", "Unit", "Value"]

    st.dataframe(
        tbl_df,
        use_container_width=True,
        height=420,
        column_config={
            "Value": st.column_config.NumberColumn(format="%.0f"),
            "Week Ending": st.column_config.DateColumn(format="MM/DD/YYYY"),
        },
    )

    dl_col1, dl_col2 = st.columns([1, 4])
    with dl_col1:
        st.download_button(
            "⬇ Download Excel",
            data=_to_excel(tbl_df),
            file_name=f"beef_weight_{year_range[0]}_{year_range[1]}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

# ── Footer ────────────────────────────────────────────────────────────────────

st.divider()
st.markdown(
    f'<p style="color:{DM_MUTED}; font-size:0.72rem; text-align:center">'
    f'Data: USDA NASS QuickStats · Federally Inspected Commercial Slaughter · '
    f'Refreshed hourly &nbsp;|&nbsp; '
    f'John Stewart &amp; Associates</p>',
    unsafe_allow_html=True,
)
