import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import requests
import io
from datetime import datetime

# ── JSA Brand Colors ───────────────────────────────────────────────────────────
# Extracted from jpsi.com logo: sage green #5e7164, charcoal #333132
JSA_GREEN    = "#5e7164"   # exact logo monogram green
JSA_GREEN_LT = "#8db89a"   # lightened for dark-bg readability
JSA_CHARCOAL = "#333132"   # logo text color

DM_BG       = "#0d1210"    # near-black with green tint
DM_SURFACE  = "#141c18"    # card / sidebar surface
DM_SURFACE2 = "#1a2620"    # chart background
DM_BORDER   = "#253328"    # borders — JSA green tint
DM_TEXT     = "#e8ede9"    # primary text — slight warm white
DM_MUTED    = "#7a9485"    # muted text — sage
COL_POS     = "#8db89a"    # positive delta — JSA light green
COL_NEG     = "#e07070"    # negative delta — muted red
COL_NEU     = "#7a9485"

JPSI_GREEN  = JSA_GREEN_LT  # alias used throughout

JSA_LOGO_FULL  = "https://www.jpsi.com/wp-content/themes/gate39media/img/logo-full.png"
JSA_LOGO_WHITE = "https://www.jpsi.com/wp-content/themes/gate39media/img/logo-white.png"

CLASS_COLORS = {
    "STEERS":     "#8db89a",   # JSA light green
    "HEIFERS":    "#6fa8c4",   # steel blue
    "COWS":       "#c98a56",   # warm amber
    "BULLS":      "#9b89c4",   # muted purple
    "CALVES":     "#c4b456",   # muted gold
    "GE 500 LBS": "#c8d4ca",   # light sage — headline class
}
CLASS_ORDER = ["GE 500 LBS", "STEERS", "HEIFERS", "COWS", "BULLS", "CALVES"]
CLASS_DISPLAY = {
    "GE 500 LBS": "Actual Carcass Weights",
    "STEERS":     "Steers",
    "HEIFERS":    "Heifers",
    "COWS":       "Cows",
    "BULLS":      "Bulls",
    "CALVES":     "Calves",
}
VOL_DISPLAY = {**CLASS_DISPLAY, "GE 500 LBS": "All Cattle"}
FILTER_DISPLAY = {**CLASS_DISPLAY, "GE 500 LBS": "All Cattle"}

def _fmt_cls(c: str) -> str:
    return FILTER_DISPLAY.get(c, c.title())

try:
    API_KEY = st.secrets.get("NASS_API_KEY", "9A6D1EB8-4D94-3221-BA0C-ADD4533EA0C1")
except Exception:
    API_KEY = "9A6D1EB8-4D94-3221-BA0C-ADD4533EA0C1"

BASE_URL = "https://quickstats.nass.usda.gov/api/api_GET/"

st.set_page_config(
    page_title="JSA Beef Weight Dashboard",
    page_icon="🐂",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(f"""
<style>
  html, body, [data-testid="stAppViewContainer"] {{
    background-color:{DM_BG}; color:{DM_TEXT};
  }}
  [data-testid="stSidebar"] {{
    background-color:{DM_SURFACE}; border-right:1px solid {DM_BORDER};
  }}
  [data-testid="stSidebar"] * {{ color:{DM_TEXT} !important; }}

  /* ── Snapshot card ── */
  .snap-card {{
    background:{DM_SURFACE}; border:1px solid {DM_BORDER};
    border-top:2px solid {JSA_GREEN}; border-radius:10px;
    padding:18px 16px 14px; height:100%;
  }}
  .snap-class {{
    color:{DM_MUTED}; font-size:0.72rem; text-transform:uppercase;
    letter-spacing:.08em; margin-bottom:6px;
  }}
  .snap-value {{
    color:{DM_TEXT}; font-size:2rem; font-weight:700; line-height:1.1;
    margin-bottom:10px;
  }}
  .snap-grid {{
    display:grid; grid-template-columns:1fr 1fr; gap:6px 10px;
  }}
  .snap-item {{ display:flex; flex-direction:column; }}
  .snap-lbl {{
    color:{DM_MUTED}; font-size:0.65rem; text-transform:uppercase;
    letter-spacing:.06em;
  }}
  .snap-pos {{ color:{COL_POS}; font-size:0.88rem; font-weight:600; }}
  .snap-neg {{ color:{COL_NEG}; font-size:0.88rem; font-weight:600; }}
  .snap-neu {{ color:{COL_NEU}; font-size:0.88rem; }}

  /* ── Summary table ── */
  .sum-table {{ width:100%; border-collapse:collapse; font-size:0.82rem; }}
  .sum-table th {{
    color:{DM_MUTED}; font-weight:500; text-transform:uppercase;
    font-size:0.68rem; letter-spacing:.06em; padding:6px 10px;
    border-bottom:1px solid {DM_BORDER}; text-align:right;
  }}
  .sum-table th:first-child {{ text-align:left; }}
  .sum-table td {{
    padding:7px 10px; border-bottom:1px solid {DM_BORDER};
    text-align:right; color:{DM_TEXT};
  }}
  .sum-table td:first-child {{ text-align:left; font-weight:600; }}
  .sum-table tr:last-child td {{ border-bottom:none; }}
  .pos {{ color:{COL_POS}; }} .neg {{ color:{COL_NEG}; }}

  .stTabs [data-baseweb="tab-list"] {{ background:{DM_SURFACE}; border-radius:8px; }}
  .stTabs [data-baseweb="tab"] {{ color:{DM_MUTED}; }}
  .stTabs [aria-selected="true"] {{ color:{JPSI_GREEN} !important; }}
  .sec-hdr {{
    color:{DM_MUTED}; font-size:0.72rem; text-transform:uppercase;
    letter-spacing:.1em; margin:14px 0 6px;
  }}
  div[data-testid="stDataFrame"] {{ background:{DM_SURFACE}; border-radius:8px; }}
</style>
""", unsafe_allow_html=True)


# ── Data fetching ──────────────────────────────────────────────────────────────

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
def fetch_data(years: tuple) -> pd.DataFrame:
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
    keep = ["year", "week_ending", "class_desc", "unit_desc", "Value"]
    df = df[[c for c in keep if c in df.columns]].copy()
    df["Value"]       = pd.to_numeric(
        df["Value"].astype(str).str.replace(",", "", regex=False), errors="coerce"
    )
    df["week_ending"] = pd.to_datetime(df["week_ending"], errors="coerce")
    df["year"]        = df["year"].astype(int)
    df["class_desc"]  = df["class_desc"].str.upper().str.strip()
    df["unit_desc"]   = df["unit_desc"].str.strip()
    df["iso_week"]    = df["week_ending"].dt.isocalendar().week.astype(int)
    return df.dropna(subset=["Value", "week_ending"])


# ── Analytics helpers ──────────────────────────────────────────────────────────

def _nearest_week(df: pd.DataFrame, year: int, iso_week: int) -> float:
    """Return the value for the closest ISO week in a given year."""
    sub = df[df["year"] == year]
    if sub.empty:
        return float("nan")
    idx = (sub["iso_week"] - iso_week).abs().idxmin()
    return sub.loc[idx, "Value"]


def olympic_avg(df: pd.DataFrame, ref_year: int, iso_week: int, n: int = 5) -> float:
    """Drop highest + lowest of the n prior years, average the rest."""
    vals = [_nearest_week(df, ref_year - i, iso_week) for i in range(1, n + 1)]
    vals = [v for v in vals if not pd.isna(v)]
    if len(vals) < 3:
        return float("nan")
    return (sum(vals) - max(vals) - min(vals)) / (len(vals) - 2)


def olympic_series(df: pd.DataFrame, ref_year: int, n: int = 5) -> pd.Series:
    """Olympic avg for every ISO week, returned as Series indexed by iso_week."""
    weeks = sorted(df["iso_week"].unique())
    return pd.Series(
        {w: olympic_avg(df, ref_year, w, n) for w in weeks},
        name="olympic_avg",
    )


def trailing_4wk(df: pd.DataFrame) -> pd.DataFrame:
    """4-week rolling average per class, sorted by week_ending."""
    return (
        df.sort_values("week_ending")
        .assign(t4w=lambda d: d.groupby("class_desc")["Value"]
                .transform(lambda s: s.rolling(4, min_periods=1).mean()))
    )


def week_kpis(wt: pd.DataFrame, cls: str) -> dict:
    """Compute all snapshot KPIs for one class."""
    nan = dict(current=float("nan"), wow=float("nan"), wow_pct=float("nan"),
               yoy=float("nan"), yoy_pct=float("nan"), t4w=float("nan"),
               olympic=float("nan"), vs_olympic=float("nan"), vs_olympic_pct=float("nan"),
               latest_date=None, latest_year=None, iso_week=None)

    sub = wt[wt["class_desc"] == cls].sort_values("week_ending")
    if sub.empty:
        return nan

    latest_date = sub["week_ending"].max()
    latest_year = int(sub.loc[sub["week_ending"] == latest_date, "year"].iloc[0])
    iso_week    = int(sub.loc[sub["week_ending"] == latest_date, "iso_week"].iloc[0])
    current     = float(sub.loc[sub["week_ending"] == latest_date, "Value"].iloc[0])

    # WoW
    prev_dates = sub[sub["week_ending"] < latest_date]
    if not prev_dates.empty:
        prev_val = float(sub.loc[sub["week_ending"] == prev_dates["week_ending"].max(), "Value"].iloc[0])
        wow = current - prev_val
        wow_pct = wow / prev_val * 100 if prev_val else float("nan")
    else:
        wow = wow_pct = float("nan")

    # YoY — same ISO week, prior year
    ly_val = _nearest_week(sub, latest_year - 1, iso_week)
    yoy = current - ly_val if not pd.isna(ly_val) else float("nan")
    yoy_pct = yoy / ly_val * 100 if (not pd.isna(ly_val) and ly_val) else float("nan")

    # Trailing 4-week avg (including current week)
    recent4 = sub.tail(4)["Value"]
    t4w = float(recent4.mean()) if len(recent4) >= 1 else float("nan")

    # Olympic avg
    olym = olympic_avg(sub, latest_year, iso_week)
    vs_olympic = current - olym if not pd.isna(olym) else float("nan")
    vs_olympic_pct = vs_olympic / olym * 100 if (not pd.isna(olym) and olym) else float("nan")

    return dict(current=current, wow=wow, wow_pct=wow_pct, yoy=yoy, yoy_pct=yoy_pct,
                t4w=t4w, olympic=olym, vs_olympic=vs_olympic, vs_olympic_pct=vs_olympic_pct,
                latest_date=latest_date, latest_year=latest_year, iso_week=iso_week)


# ── Formatting helpers ─────────────────────────────────────────────────────────

def _dc(val: float, fmt: str = "+.1f", suffix: str = "") -> str:
    """Return a delta value with color class."""
    if pd.isna(val):
        return f'<span class="snap-neu">—</span>'
    cls = "snap-pos" if val >= 0 else "snap-neg"
    sign = "+" if val >= 0 else ""
    return f'<span class="{cls}">{sign}{val:{fmt[1:]}}{suffix}</span>'


def _snap_item(label: str, delta_html: str) -> str:
    return f'<div class="snap-item"><span class="snap-lbl">{label}</span>{delta_html}</div>'


def _snap_card(cls: str, kpi: dict, unit_label: str) -> str:
    val_str = f'{kpi["current"]:,.1f}' if not pd.isna(kpi["current"]) else "—"
    t4w_str = f'{kpi["t4w"]:,.1f}' if not pd.isna(kpi["t4w"]) else "—"
    olym_str = f'{kpi["olympic"]:,.1f}' if not pd.isna(kpi["olympic"]) else "—"
    color = CLASS_COLORS.get(cls, DM_MUTED)
    return f"""
    <div class="snap-card">
      <div class="snap-class" style="color:{color}">{CLASS_DISPLAY.get(cls, cls.title())}</div>
      <div class="snap-value">{val_str} <span style="font-size:0.9rem;color:{DM_MUTED}">lb</span></div>
      <div class="snap-grid">
        {_snap_item("WoW", _dc(kpi['wow'], '+.1f', ' lb') + ' ' + _dc(kpi['wow_pct'], '+.1f', '%'))}
        {_snap_item("YoY", _dc(kpi['yoy'], '+.1f', ' lb') + ' ' + _dc(kpi['yoy_pct'], '+.1f', '%'))}
        {_snap_item("4-Wk Avg", f'<span class="snap-neu">{t4w_str} lb</span>')}
        {_snap_item("vs Olympic Avg", _dc(kpi['vs_olympic'], '+.1f', ' lb') + ' ' + _dc(kpi['vs_olympic_pct'], '+.1f', '%'))}
      </div>
      <div style="margin-top:8px;font-size:0.7rem;color:{DM_MUTED}">
        Olympic avg: {olym_str} lb &nbsp;·&nbsp; {unit_label}
      </div>
    </div>"""


# ── Chart helpers ──────────────────────────────────────────────────────────────

AXIS_STYLE = dict(gridcolor=DM_BORDER, linecolor=DM_BORDER, showgrid=True)


def _base_layout(title: str = "", height: int = 420, y_title: str = "") -> dict:
    return dict(
        title=dict(text=title, font=dict(color=DM_TEXT, size=13), x=0),
        paper_bgcolor=DM_SURFACE2, plot_bgcolor=DM_SURFACE2,
        font=dict(color=DM_TEXT, size=11),
        legend=dict(bgcolor="rgba(0,0,0,0)", borderwidth=0, font=dict(size=11)),
        margin=dict(l=50, r=20, t=40, b=40),
        hovermode="x unified", height=height,
    )


def _apply(fig, title="", height=420, y_title=""):
    fig.update_layout(**_base_layout(title, height, y_title))
    fig.update_xaxes(**AXIS_STYLE)
    fig.update_yaxes(**AXIS_STYLE, title_text=y_title)


def _to_excel(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False)
    return buf.getvalue()


# ── Sidebar ────────────────────────────────────────────────────────────────────

st.sidebar.markdown(
    f'<div style="padding:10px 0 6px">'
    f'<img src="{JSA_LOGO_WHITE}" style="width:160px;opacity:0.92" /></div>',
    unsafe_allow_html=True,
)
st.sidebar.markdown(
    f'<div style="background:{JSA_GREEN};border-radius:4px;padding:5px 10px;'
    f'font-size:.7rem;color:#fff;font-weight:600;letter-spacing:.08em;'
    f'text-transform:uppercase;margin-bottom:10px">Beef Weight Dashboard</div>',
    unsafe_allow_html=True,
)
st.sidebar.markdown(
    f'<span style="color:{DM_MUTED};font-size:.72rem">USDA NASS · Federally Inspected</span>',
    unsafe_allow_html=True,
)
st.sidebar.divider()

current_year = datetime.now().year
# Always load enough history for 5-yr olympic avg + trend charts
LOAD_YEARS = tuple(range(current_year - 7, current_year + 1))

weight_unit = st.sidebar.radio("Weight basis", ["Dressed Weight", "Live Weight"])
unit_filter = "DRESSED" if weight_unit == "Dressed Weight" else "LIVE"
unit_label  = "dressed basis" if unit_filter == "DRESSED" else "live basis"

st.sidebar.divider()
st.sidebar.markdown(f'<span style="color:{DM_MUTED};font-size:.72rem;text-transform:uppercase;letter-spacing:.06em">Classes — Snapshot</span>',
                    unsafe_allow_html=True)
snap_classes = st.sidebar.multiselect(
    "Snapshot classes", CLASS_ORDER,
    default=["GE 500 LBS", "STEERS", "HEIFERS", "COWS"],
    format_func=_fmt_cls,
    label_visibility="collapsed",
)
if not snap_classes:
    snap_classes = ["GE 500 LBS"]

st.sidebar.divider()
trend_weeks = st.sidebar.slider("Trend window (weeks)", 8, 52, 26)
trend_class = st.sidebar.selectbox("Trend class", CLASS_ORDER, format_func=_fmt_cls)


# ── Load data ──────────────────────────────────────────────────────────────────

with st.spinner("Loading USDA NASS data…"):
    raw = fetch_data(LOAD_YEARS)

if raw.empty:
    st.error("No data returned from USDA NASS. Check your API key in st.secrets.")
    st.stop()

wt  = raw[raw["unit_desc"].str.contains(unit_filter, case=False, na=False)].copy()
vol = raw[raw["unit_desc"].str.upper() == "HEAD"].copy()
wt  = trailing_4wk(wt)

latest_date = wt["week_ending"].max()
latest_year = int(wt.loc[wt["week_ending"] == latest_date, "year"].iloc[0])
latest_iso  = int(wt.loc[wt["week_ending"] == latest_date, "iso_week"].iloc[0])

# ── Next Friday calculation ────────────────────────────────────────────────────
_today      = datetime.now().date()
_days_ahead = (4 - _today.weekday()) % 7   # 4 = Friday
_days_ahead = 7 if _days_ahead == 0 else _days_ahead  # if today is Friday, next Friday
_next_friday = _today + __import__("datetime").timedelta(days=_days_ahead)

# ── Sidebar data info panel ────────────────────────────────────────────────────
st.sidebar.divider()
st.sidebar.markdown(f"""
<div style="background:{DM_SURFACE2};border:1px solid {DM_BORDER};
  border-left:3px solid {JSA_GREEN};border-radius:6px;padding:12px 14px;font-size:0.78rem">
  <div style="color:{DM_MUTED};font-size:0.65rem;text-transform:uppercase;
    letter-spacing:.08em;margin-bottom:8px">Data Status</div>

  <div style="display:flex;justify-content:space-between;margin-bottom:6px">
    <span style="color:{DM_MUTED}">Data as of</span>
    <span style="color:{DM_TEXT};font-weight:600">{latest_date.strftime('%b %d, %Y')}</span>
  </div>

  <div style="display:flex;justify-content:space-between;margin-bottom:6px">
    <span style="color:{DM_MUTED}">ISO Week</span>
    <span style="color:{DM_TEXT};font-weight:600">Wk {latest_iso}, {latest_year}</span>
  </div>

  <div style="border-top:1px solid {DM_BORDER};margin:8px 0"></div>

  <div style="display:flex;justify-content:space-between;margin-bottom:6px">
    <span style="color:{DM_MUTED}">Next update</span>
    <span style="color:{DM_TEXT};font-weight:600">{_next_friday.strftime('%b %d, %Y')}</span>
  </div>

  <div style="display:flex;justify-content:space-between;margin-bottom:6px">
    <span style="color:{DM_MUTED}">Update day</span>
    <span style="color:{DM_TEXT};font-weight:600">Fridays</span>
  </div>

  <div style="border-top:1px solid {DM_BORDER};margin:8px 0"></div>

  <div style="color:{DM_MUTED};font-size:0.68rem;line-height:1.5">
    Source: USDA NASS<br>
    Livestock Slaughter report<br>
    Cache refreshes every hour
  </div>
</div>
""", unsafe_allow_html=True)


# ── Header ─────────────────────────────────────────────────────────────────────

hdr_l, hdr_r = st.columns([3, 1])
with hdr_l:
    st.markdown(f"""
    <div style="display:flex;align-items:center;gap:18px;padding:6px 0 2px">
      <img src="{JSA_LOGO_FULL}" style="height:48px" />
      <div>
        <div style="font-size:1.45rem;font-weight:700;color:{DM_TEXT};line-height:1.1">
          Beef Slaughter Weight
        </div>
        <div style="color:{DM_MUTED};font-size:0.8rem;margin-top:2px">
          Weekly snapshot &nbsp;·&nbsp; USDA NASS QuickStats &nbsp;·&nbsp; Federally Inspected
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)
with hdr_r:
    st.markdown(f"""
    <div style="text-align:right;padding-top:10px">
      <div style="color:{DM_MUTED};font-size:0.7rem;text-transform:uppercase;letter-spacing:.08em">Week Ending</div>
      <div style="color:{DM_TEXT};font-size:1.1rem;font-weight:700">{latest_date.strftime('%B %d, %Y')}</div>
      <div style="display:inline-block;background:{JSA_GREEN};color:#fff;font-size:.68rem;
        font-weight:600;padding:2px 8px;border-radius:3px;margin-top:4px;letter-spacing:.06em">
        {weight_unit.upper()}
      </div>
    </div>
    """, unsafe_allow_html=True)
st.divider()


# ── Weekly Snapshot cards ──────────────────────────────────────────────────────

cols = st.columns(len(snap_classes))
for col, cls in zip(cols, snap_classes):
    kpi = week_kpis(wt, cls)
    col.markdown(_snap_card(cls, kpi, unit_label), unsafe_allow_html=True)

st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)


# ── Slaughter Volume Snapshot ──────────────────────────────────────────────────

def vol_kpis(vol_df: pd.DataFrame, cls: str) -> dict:
    nan = dict(current=float("nan"), wow=float("nan"), wow_pct=float("nan"),
               yoy=float("nan"), yoy_pct=float("nan"), t4w=float("nan"),
               olympic=float("nan"), vs_olympic=float("nan"), vs_olympic_pct=float("nan"))
    sub = vol_df[vol_df["class_desc"] == cls].sort_values("week_ending")
    if sub.empty:
        return nan
    latest_d  = sub["week_ending"].max()
    latest_y  = int(sub.loc[sub["week_ending"] == latest_d, "year"].iloc[0])
    iso_w     = int(sub.loc[sub["week_ending"] == latest_d, "iso_week"].iloc[0])
    current   = float(sub.loc[sub["week_ending"] == latest_d, "Value"].iloc[0])

    prev_d = sub[sub["week_ending"] < latest_d]
    if not prev_d.empty:
        prev_val = float(sub.loc[sub["week_ending"] == prev_d["week_ending"].max(), "Value"].iloc[0])
        wow = current - prev_val
        wow_pct = wow / prev_val * 100 if prev_val else float("nan")
    else:
        wow = wow_pct = float("nan")

    ly_val = _nearest_week(sub, latest_y - 1, iso_w)
    yoy = current - ly_val if not pd.isna(ly_val) else float("nan")
    yoy_pct = yoy / ly_val * 100 if (not pd.isna(ly_val) and ly_val) else float("nan")

    t4w   = float(sub.tail(4)["Value"].mean())
    olym  = olympic_avg(sub, latest_y, iso_w)
    vs_ol = current - olym if not pd.isna(olym) else float("nan")
    vs_ol_pct = vs_ol / olym * 100 if (not pd.isna(olym) and olym) else float("nan")
    return dict(current=current, wow=wow, wow_pct=wow_pct, yoy=yoy, yoy_pct=yoy_pct,
                t4w=t4w, olympic=olym, vs_olympic=vs_ol, vs_olympic_pct=vs_ol_pct)


def _vol_card(cls: str, kpi: dict) -> str:
    val_str  = f'{kpi["current"]:,.0f}' if not pd.isna(kpi["current"]) else "—"
    t4w_str  = f'{kpi["t4w"]:,.0f}' if not pd.isna(kpi["t4w"]) else "—"
    olym_str = f'{kpi["olympic"]:,.0f}' if not pd.isna(kpi["olympic"]) else "—"
    color = CLASS_COLORS.get(cls, DM_MUTED)
    return f"""
    <div class="snap-card">
      <div class="snap-class" style="color:{color}">{VOL_DISPLAY.get(cls, cls.title())}</div>
      <div class="snap-value">{val_str} <span style="font-size:0.9rem;color:{DM_MUTED}">head</span></div>
      <div class="snap-grid">
        {_snap_item("WoW", _dc(kpi['wow'], '+.0f', ' hd') + ' ' + _dc(kpi['wow_pct'], '+.1f', '%'))}
        {_snap_item("YoY", _dc(kpi['yoy'], '+.0f', ' hd') + ' ' + _dc(kpi['yoy_pct'], '+.1f', '%'))}
        {_snap_item("4-Wk Avg", f'<span class="snap-neu">{t4w_str} hd</span>')}
        {_snap_item("vs Olympic Avg", _dc(kpi['vs_olympic'], '+.0f', ' hd') + ' ' + _dc(kpi['vs_olympic_pct'], '+.1f', '%'))}
      </div>
      <div style="margin-top:8px;font-size:0.7rem;color:{DM_MUTED}">
        Olympic avg: {olym_str} head
      </div>
    </div>"""


st.markdown(f'<div class="sec-hdr">Slaughter Volume — Weekly Snapshot (Head)</div>', unsafe_allow_html=True)
vol_snap_classes = ["GE 500 LBS", "STEERS", "HEIFERS", "COWS", "BULLS"]
vol_cols = st.columns(len(vol_snap_classes))
for col, cls in zip(vol_cols, vol_snap_classes):
    kpi = vol_kpis(vol, cls)
    col.markdown(_vol_card(cls, kpi), unsafe_allow_html=True)

st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)


# ── Weight Summary table ───────────────────────────────────────────────────────

def _fmt_delta(val: float, pct: float, suffix: str = " lb") -> str:
    if pd.isna(val):
        return "—"
    sign = "+" if val >= 0 else ""
    css  = "pos" if val >= 0 else "neg"
    p    = f" ({sign}{pct:.1f}%)" if not pd.isna(pct) else ""
    return f'<span class="{css}">{sign}{val:.1f}{suffix}{p}</span>'


def _build_summary(classes: list) -> str:
    rows = ""
    for cls in classes:
        kpi = week_kpis(wt, cls)
        cur = f'{kpi["current"]:,.1f}' if not pd.isna(kpi["current"]) else "—"
        t4  = f'{kpi["t4w"]:,.1f}' if not pd.isna(kpi["t4w"]) else "—"
        rows += f"""<tr>
          <td>{CLASS_DISPLAY.get(cls, cls.title())}</td>
          <td>{cur} lb</td>
          <td>{_fmt_delta(kpi['wow'], kpi['wow_pct'])}</td>
          <td>{t4} lb</td>
          <td>{_fmt_delta(kpi['yoy'], kpi['yoy_pct'])}</td>
          <td>{_fmt_delta(kpi['vs_olympic'], kpi['vs_olympic_pct'])}</td>
        </tr>"""
    return f"""
    <table class="sum-table">
      <thead><tr>
        <th>Class</th>
        <th>This Week</th>
        <th>WoW Change</th>
        <th>4-Wk Avg</th>
        <th>vs Last Year</th>
        <th>vs Olympic Avg</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>"""


def _build_vol_summary(classes: list) -> str:
    rows = ""
    for cls in classes:
        kpi = vol_kpis(vol, cls)
        cur = f'{kpi["current"]:,.0f}' if not pd.isna(kpi["current"]) else "—"
        t4  = f'{kpi["t4w"]:,.0f}' if not pd.isna(kpi["t4w"]) else "—"
        rows += f"""<tr>
          <td>{VOL_DISPLAY.get(cls, cls.title())}</td>
          <td>{cur} hd</td>
          <td>{_fmt_delta(kpi['wow'], kpi['wow_pct'], ' hd')}</td>
          <td>{t4} hd</td>
          <td>{_fmt_delta(kpi['yoy'], kpi['yoy_pct'], ' hd')}</td>
          <td>{_fmt_delta(kpi['vs_olympic'], kpi['vs_olympic_pct'], ' hd')}</td>
        </tr>"""
    return f"""
    <table class="sum-table">
      <thead><tr>
        <th>Class</th>
        <th>This Week</th>
        <th>WoW Change</th>
        <th>4-Wk Avg</th>
        <th>vs Last Year</th>
        <th>vs Olympic Avg</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>"""


vol_sum_classes = ["GE 500 LBS", "STEERS", "HEIFERS", "COWS", "BULLS", "CALVES"]

st.markdown(f'<div class="sec-hdr">Volume Summary — All Classes (Head)</div>', unsafe_allow_html=True)
st.markdown(
    f'<div style="background:{DM_SURFACE};border:1px solid {DM_BORDER};border-radius:8px;padding:12px 16px">'
    + _build_vol_summary(vol_sum_classes)
    + "</div>",
    unsafe_allow_html=True,
)

st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)

st.markdown(f'<div class="sec-hdr">Weight Summary — All Classes</div>', unsafe_allow_html=True)
st.markdown(
    f'<div style="background:{DM_SURFACE};border:1px solid {DM_BORDER};border-radius:8px;padding:12px 16px">'
    + _build_summary(CLASS_ORDER)
    + "</div>",
    unsafe_allow_html=True,
)

st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)


# ── Tabs ───────────────────────────────────────────────────────────────────────

tab_trend, tab_yoy, tab_vol, tab_data = st.tabs([
    "📈 Weekly Trend", "📊 Year-over-Year", "🔢 Slaughter Volume", "📋 Data"
])


# ── Tab 1 — Weekly Trend ───────────────────────────────────────────────────────

with tab_trend:
    cls = trend_class
    sub = wt[wt["class_desc"] == cls].sort_values("week_ending")

    if sub.empty:
        st.warning("No data for selected class.")
    else:
        # Slice to trend window for current + prior year
        cutoff = sub["week_ending"].max() - pd.Timedelta(weeks=trend_weeks)
        curr_yr_full = sub[sub["year"] == latest_year]
        curr_yr = curr_yr_full[curr_yr_full["week_ending"] > cutoff]
        prev_yr = sub[
            (sub["year"] == latest_year - 1) &
            (sub["iso_week"].isin(curr_yr["iso_week"]))
        ]

        # Olympic avg for weeks in window
        olym_map = olympic_series(sub, latest_year)
        olym_weeks = curr_yr["iso_week"].values
        olym_x = curr_yr["week_ending"].values
        olym_y = [olym_map.get(w, float("nan")) for w in olym_weeks]

        # 4-week rolling avg for current year (full series → slice)
        sub_roll = sub.copy()
        sub_roll["t4w"] = sub_roll["Value"].rolling(4, min_periods=1).mean()
        curr_roll = sub_roll[
            (sub_roll["year"] == latest_year) &
            (sub_roll["week_ending"] > cutoff)
        ]

        fig = go.Figure()

        # Olympic avg band (high/low of the 5 prior years per week)
        olym_highs, olym_lows = [], []
        for w, x in zip(olym_weeks, olym_x):
            yr_vals = [_nearest_week(sub, latest_year - i, w) for i in range(1, 6)]
            yr_vals = [v for v in yr_vals if not pd.isna(v)]
            olym_highs.append(max(yr_vals) if yr_vals else float("nan"))
            olym_lows.append(min(yr_vals) if yr_vals else float("nan"))

        fig.add_trace(go.Scatter(
            x=list(olym_x) + list(olym_x)[::-1],
            y=olym_highs + olym_lows[::-1],
            fill="toself", fillcolor="rgba(122,153,144,0.12)",
            line=dict(color="rgba(0,0,0,0)"),
            name="5yr Range", hoverinfo="skip", showlegend=True,
        ))

        # Olympic avg line
        fig.add_trace(go.Scatter(
            x=olym_x, y=olym_y,
            name="Olympic Avg (5yr)",
            mode="lines",
            line=dict(color="rgba(122,153,144,0.7)", width=1.8, dash="dash"),
            hovertemplate="Olympic avg: %{y:,.1f} lb<extra></extra>",
        ))

        # Prior year
        if not prev_yr.empty:
            fig.add_trace(go.Scatter(
                x=prev_yr["week_ending"], y=prev_yr["Value"],
                name=str(latest_year - 1),
                mode="lines",
                line=dict(color="rgba(224,232,240,0.4)", width=1.5, dash="dot"),
                hovertemplate=f"{latest_year-1}: %{{y:,.1f}} lb<extra></extra>",
            ))

        # Current year
        fig.add_trace(go.Scatter(
            x=curr_yr["week_ending"], y=curr_yr["Value"],
            name=str(latest_year),
            mode="lines+markers",
            line=dict(color=JPSI_GREEN, width=2.5),
            marker=dict(size=5, color=JPSI_GREEN),
            hovertemplate=f"{latest_year}: %{{y:,.1f}} lb<extra></extra>",
        ))

        # 4-week rolling avg
        fig.add_trace(go.Scatter(
            x=curr_roll["week_ending"], y=curr_roll["t4w"],
            name="4-Wk Rolling Avg",
            mode="lines",
            line=dict(color="#fbbf24", width=2, dash="dashdot"),
            hovertemplate="4-wk avg: %{y:,.1f} lb<extra></extra>",
        ))

        _apply(fig, f"{cls.title()} — {weight_unit} · Last {trend_weeks} Weeks", 440, "lb / head")
        st.plotly_chart(fig, use_container_width=True)

        # WoW delta bars
        recent = sub[sub["week_ending"] > cutoff].copy()
        recent["wow_delta"] = recent["Value"].diff()
        recent = recent.dropna(subset=["wow_delta"])

        fig2 = go.Figure(go.Bar(
            x=recent["week_ending"],
            y=recent["wow_delta"],
            marker_color=[COL_POS if v >= 0 else COL_NEG for v in recent["wow_delta"]],
            hovertemplate="WoW: %{y:+.1f} lb<extra></extra>",
        ))
        fig2.add_hline(y=0, line_color=DM_BORDER)
        _apply(fig2, "Week-over-Week Change", 240, "\u0394 lb / head")
        st.plotly_chart(fig2, use_container_width=True)


# ── Tab 2 — Year-over-Year ─────────────────────────────────────────────────────

with tab_yoy:
    yoy_cls = st.selectbox(
        "Class",
        [c for c in CLASS_ORDER if not wt[wt["class_desc"] == c].empty],
        format_func=_fmt_cls,
        key="yoy_cls",
    )
    n_years = st.slider("Years to compare", 3, 10, 6, key="yoy_n")

    yoy_sub = wt[wt["class_desc"] == yoy_cls].copy()
    if yoy_sub.empty:
        st.warning("No data.")
    else:
        yoy_sub["day_of_year"] = yoy_sub["week_ending"].dt.dayofyear
        ly_max  = yoy_sub["year"].max()
        yr_list = [y for y in range(ly_max - n_years + 1, ly_max + 1)
                   if y in yoy_sub["year"].unique()]

        month_ticks  = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335]
        month_labels = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

        # ── Multi-year overlay ────────────────────────────────────────────────
        fig3 = go.Figure()

        # Olympic avg band
        olym_all = olympic_series(yoy_sub, ly_max, n=5)
        all_doys = sorted(yoy_sub["day_of_year"].unique())
        doy_to_iso = yoy_sub.groupby("day_of_year")["iso_week"].first().to_dict()
        olym_y_all = [olym_all.get(doy_to_iso.get(d, 0), float("nan")) for d in all_doys]

        # Range band
        olym_high_all, olym_low_all = [], []
        for d in all_doys:
            iw = doy_to_iso.get(d, 0)
            yr_vals = [_nearest_week(yoy_sub, ly_max - i, iw) for i in range(1, 6)]
            yr_vals = [v for v in yr_vals if not pd.isna(v)]
            olym_high_all.append(max(yr_vals) if yr_vals else float("nan"))
            olym_low_all.append(min(yr_vals) if yr_vals else float("nan"))

        fig3.add_trace(go.Scatter(
            x=all_doys + all_doys[::-1],
            y=olym_high_all + olym_low_all[::-1],
            fill="toself", fillcolor="rgba(122,153,144,0.10)",
            line=dict(color="rgba(0,0,0,0)"),
            name="5yr Range", hoverinfo="skip",
        ))
        fig3.add_trace(go.Scatter(
            x=all_doys, y=olym_y_all,
            name="Olympic Avg",
            mode="lines",
            line=dict(color="rgba(122,153,144,0.7)", width=1.8, dash="dash"),
            hovertemplate="Olympic avg: %{y:,.1f} lb<extra></extra>",
        ))

        for yr in yr_list:
            yd = yoy_sub[yoy_sub["year"] == yr].sort_values("day_of_year")
            is_cur = yr == ly_max
            fig3.add_trace(go.Scatter(
                x=yd["day_of_year"], y=yd["Value"],
                name=str(yr), mode="lines",
                line=dict(
                    color=JPSI_GREEN if is_cur else CLASS_COLORS.get(yoy_cls, DM_MUTED),
                    width=2.5 if is_cur else 1.2,
                    dash="solid" if is_cur else "dot",
                ),
                opacity=1.0 if is_cur else 0.5,
                hovertemplate=f"{yr}: %{{y:,.1f}} lb<extra></extra>",
            ))

        _apply(fig3, f"{yoy_cls.title()} — Year-over-Year Overlay", 460, "lb / head")
        fig3.update_xaxes(tickmode="array", tickvals=month_ticks, ticktext=month_labels)
        st.plotly_chart(fig3, use_container_width=True)

        # ── Same-week YoY comparison bar chart ───────────────────────────────
        st.markdown('<div class="sec-hdr">Same Week — Value by Year</div>', unsafe_allow_html=True)
        wk_vals = []
        for yr in range(ly_max - n_years + 1, ly_max + 1):
            v = _nearest_week(yoy_sub, yr, latest_iso)
            olym = olympic_avg(yoy_sub, yr, latest_iso)
            wk_vals.append({"Year": yr, "Value": v, "Olympic": olym})
        wk_df = pd.DataFrame(wk_vals).dropna(subset=["Value"])

        fig4 = go.Figure()
        fig4.add_trace(go.Bar(
            x=wk_df["Year"], y=wk_df["Value"],
            name="Actual",
            marker_color=[JPSI_GREEN if yr == ly_max else "rgba(74,222,128,0.45)"
                          for yr in wk_df["Year"]],
            hovertemplate="%{x}: %{y:,.1f} lb<extra></extra>",
        ))
        fig4.add_trace(go.Scatter(
            x=wk_df["Year"], y=wk_df["Olympic"],
            name="Olympic Avg",
            mode="lines+markers",
            line=dict(color=DM_MUTED, dash="dash", width=1.5),
            hovertemplate="Olympic avg: %{y:,.1f} lb<extra></extra>",
        ))
        _apply(fig4, f"ISO Week {latest_iso} — Historical Comparison", 300, "lb / head")
        fig4.update_xaxes(tickmode="linear", dtick=1)
        st.plotly_chart(fig4, use_container_width=True)

        # ── YoY delta vs Olympic avg ──────────────────────────────────────────
        st.markdown('<div class="sec-hdr">Current Year vs Olympic Avg — Weekly Delta</div>', unsafe_allow_html=True)
        curr_full = yoy_sub[yoy_sub["year"] == ly_max].sort_values("iso_week")
        olym_curr = [olympic_avg(yoy_sub, ly_max, w) for w in curr_full["iso_week"]]
        curr_full = curr_full.copy()
        curr_full["vs_olympic"] = curr_full["Value"].values - pd.array(olym_curr)

        fig5 = go.Figure(go.Bar(
            x=curr_full["week_ending"],
            y=curr_full["vs_olympic"],
            marker_color=[COL_POS if v >= 0 else COL_NEG for v in curr_full["vs_olympic"]],
            hovertemplate="%{x|%b %d}: %{y:+.1f} lb vs Olympic avg<extra></extra>",
        ))
        fig5.add_hline(y=0, line_color=DM_BORDER)
        _apply(fig5, f"{ly_max} vs Olympic Avg — Weekly \u0394", 260, "\u0394 lb / head")
        st.plotly_chart(fig5, use_container_width=True)


# ── Tab 3 — Slaughter Volume ───────────────────────────────────────────────────

with tab_vol:
    if vol.empty:
        st.warning("No slaughter volume data.")
    else:
        vol_cls = st.multiselect(
            "Classes",
            CLASS_ORDER,
            default=["GE 500 LBS", "STEERS", "HEIFERS"],
            format_func=_fmt_cls,
            key="vol_cls",
        )
        if not vol_cls:
            vol_cls = ["GE 500 LBS"]

        vol_cutoff = vol["week_ending"].max() - pd.Timedelta(weeks=trend_weeks)

        fig6 = go.Figure()
        for cls in vol_cls:
            cd = vol[(vol["class_desc"] == cls) & (vol["week_ending"] > vol_cutoff)].sort_values("week_ending")
            if cd.empty:
                continue
            fig6.add_trace(go.Scatter(
                x=cd["week_ending"], y=cd["Value"],
                name=VOL_DISPLAY.get(cls, cls.title()), mode="lines",
                line=dict(color=CLASS_COLORS.get(cls, DM_MUTED), width=2),
                hovertemplate="%{y:,.0f} head<extra>%{fullData.name}</extra>",
            ))
        _apply(fig6, f"Weekly Slaughter — Head Count · Last {trend_weeks} Weeks", 420, "Head")
        st.plotly_chart(fig6, use_container_width=True)

        # Latest week pie
        latest_vol_date = vol["week_ending"].max()
        pie_data = vol[
            (vol["week_ending"] == latest_vol_date) &
            (vol["class_desc"].isin(["STEERS", "HEIFERS", "COWS", "BULLS", "CALVES"]))
        ]
        if not pie_data.empty:
            st.markdown(f'<div class="sec-hdr">Week of {latest_vol_date.strftime("%B %d, %Y")} — Class Mix</div>',
                        unsafe_allow_html=True)
            fig7 = go.Figure(go.Pie(
                labels=pie_data["class_desc"].map(lambda c: VOL_DISPLAY.get(c, c.title())),
                values=pie_data["Value"],
                marker_colors=[CLASS_COLORS.get(c, DM_MUTED) for c in pie_data["class_desc"]],
                hole=0.45, textinfo="label+percent",
                hovertemplate="%{label}: %{value:,.0f} head<extra></extra>",
            ))
            fig7.update_layout(
                paper_bgcolor=DM_SURFACE2, plot_bgcolor=DM_SURFACE2,
                font=dict(color=DM_TEXT), showlegend=False,
                height=300, margin=dict(l=20, r=20, t=10, b=10),
            )
            st.plotly_chart(fig7, use_container_width=True)


# ── Tab 4 — Data ───────────────────────────────────────────────────────────────

with tab_data:
    c1, c2 = st.columns([2, 1])
    with c1:
        tbl_cls = st.multiselect(
            "Classes", CLASS_ORDER,
            default=["GE 500 LBS", "STEERS", "HEIFERS"],
            format_func=_fmt_cls,
            key="tbl_cls",
        )
    with c2:
        tbl_unit = st.selectbox(
            "Unit",
            ["LB / HEAD, DRESSED BASIS", "LB / HEAD, LIVE BASIS", "HEAD"],
            key="tbl_unit",
        )

    tbl = raw[
        (raw["class_desc"].isin(tbl_cls or CLASS_ORDER)) &
        (raw["unit_desc"] == tbl_unit)
    ][["year", "week_ending", "class_desc", "unit_desc", "Value"]].copy()
    tbl = tbl.sort_values(["week_ending", "class_desc"], ascending=[False, True])
    tbl.columns = ["Year", "Week Ending", "Class", "Unit", "Value"]

    st.dataframe(
        tbl, use_container_width=True, height=440,
        column_config={
            "Value": st.column_config.NumberColumn(format="%.1f"),
            "Week Ending": st.column_config.DateColumn(format="MM/DD/YYYY"),
        },
    )
    st.download_button(
        "⬇ Download Excel",
        data=_to_excel(tbl),
        file_name=f"beef_weight_{current_year}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ── Footer ──────────────────────────────────────────────────────────────────────

st.divider()
st.markdown(
    f'<p style="color:{DM_MUTED};font-size:.72rem;text-align:center">'
    f'<img src="{JSA_LOGO_WHITE}" style="height:18px;opacity:0.5;vertical-align:middle;margin-right:8px" />'
    f'John Stewart &amp; Associates &nbsp;·&nbsp; USDA NASS QuickStats &nbsp;·&nbsp; '
    f'Federally Inspected Commercial Slaughter &nbsp;·&nbsp; Cached 1 hr</p>',
    unsafe_allow_html=True,
)
