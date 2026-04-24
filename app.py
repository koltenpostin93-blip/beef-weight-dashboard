import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import requests
import io
import re
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


# ── AMS Weekly Meat Production / Slaughter (sj_ls712) ─────────────────────────

AMS_URL = "https://www.ams.usda.gov/mnreports/sj_ls712.txt"

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_ams_weekly() -> dict:
    """Parse the AMS sj_ls712 weekly meat production / slaughter text report."""
    try:
        r = requests.get(AMS_URL, timeout=20)
        r.raise_for_status()
        text = r.text
    except Exception as e:
        return {"error": str(e)}

    def _num(s):
        try:
            return float(str(s).replace(",", "").replace("%", "").strip())
        except Exception:
            return float("nan")

    def _parse_date(s):
        s = s.strip()
        for fmt in ("%d-%b-%y", "%d-%b-%Y"):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                pass
        return None

    result = {}

    # ── Report date line ────────────────────────────────────────────────────────
    m = re.search(r"(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\w+\s+\d+,\s+\d{4})", text)
    if m:
        try:
            result["report_date"] = datetime.strptime(m.group(2).strip(), "%b %d, %Y").date()
        except ValueError:
            result["report_date"] = None

    # ── Livestock Slaughter (head) ───────────────────────────────────────────────
    slaughter = {}
    m = re.search(r"Livestock Slaughter \(head\)(.*?)(?:----)", text, re.DOTALL)
    if m:
        block = m.group(1)
        cols = ["Cattle", "Calves", "Hogs", "Sheep"]
        for line in block.splitlines():
            line = line.strip()
            parts = line.split()
            if not parts:
                continue
            # rows like:  25-Apr-26     529,000  5,000  2,469,000  34,000
            d = _parse_date(parts[0])
            if d and len(parts) >= 5:
                vals = [_num(p) for p in parts[1:5]]
                slaughter[d] = dict(zip(cols, vals))
            # YTD rows like:  2026 YTD   8,620,000   36,000   40,931,000   614,000
            elif len(parts) >= 6 and parts[1] == "YTD":
                yr = parts[0]
                vals = [_num(p) for p in parts[2:6]]
                slaughter[f"YTD_{yr}"] = dict(zip(cols, vals))
    result["slaughter"] = slaughter

    # ── Average Weights ──────────────────────────────────────────────────────────
    weights = {"live": {}, "dressed": {}}
    m = re.search(r"Average Weights \(lbs\)(.*?)(?:----)", text, re.DOTALL)
    if m:
        block = m.group(1)
        mode = None
        for line in block.splitlines():
            line = line.strip()
            if not line:
                continue
            if re.search(r"Live:", line, re.IGNORECASE):
                mode = "live"
            elif re.search(r"Dressed:", line, re.IGNORECASE):
                mode = "dressed"
            if mode is None:
                continue
            # Rows like:  25-Apr-26   Estimate   1473  362  293  117
            parts = line.split()
            d = _parse_date(parts[0]) if parts else None
            if d:
                # find numeric run after the date and optional label word
                nums = []
                for p in parts[1:]:
                    p = p.replace(",", "")
                    try:
                        nums.append(float(p))
                    except ValueError:
                        continue
                if len(nums) >= 4:
                    weights[mode][d] = {
                        "Cattle": nums[0], "Calves": nums[1],
                        "Hogs": nums[2], "Sheep": nums[3],
                    }
    result["weights"] = weights

    # ── Cattle class mix (%) ────────────────────────────────────────────────────
    class_mix = {}
    m = re.search(r"Percentage of Total Cattle Slaughtered by Class(.*?)(?:----|\Z)", text, re.DOTALL)
    if m:
        block = m.group(1)
        for line in block.splitlines():
            line = line.strip()
            parts = line.split()
            d = _parse_date(parts[0]) if parts else None
            if d and len(parts) >= 5:
                pcts = [_num(p) for p in parts[1:5]]
                class_mix[d] = dict(zip(["Steers", "Heifers", "Cows", "Bulls"], pcts))
    result["class_mix"] = class_mix

    # ── Meat production (million lbs) ───────────────────────────────────────────
    meat_prod = {}
    m = re.search(r"Meat Production \(millions of pounds\)(.*?)(?:----)", text, re.DOTALL)
    if m:
        block = m.group(1)
        for line in block.splitlines():
            line = line.strip()
            parts = line.split()
            d = _parse_date(parts[0]) if parts else None
            if d and len(parts) >= 5:
                vals = [_num(p) for p in parts[1:6]]
                meat_prod[d] = {
                    "Beef": vals[0], "Calf/Veal": vals[1],
                    "Pork": vals[2], "Lamb": vals[3], "Total": vals[4],
                }
    result["meat_prod"] = meat_prod

    return result


def _build_df(frames: list) -> pd.DataFrame:
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
    return _build_df(frames)


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_vol_data(years: tuple) -> pd.DataFrame:
    """Separate fetch for head-count slaughter data — may update ahead of weight data."""
    frames = []
    for year in years:
        params = {
            "key":               API_KEY,
            "source_desc":       "SURVEY",
            "sector_desc":       "ANIMALS & PRODUCTS",
            "group_desc":        "LIVESTOCK",
            "commodity_desc":    "CATTLE",
            "statisticcat_desc": "SLAUGHTERED",
            "unit_desc":         "HEAD",
            "freq_desc":         "WEEKLY",
            "state_alpha":       "US",
            "year":              year,
            "format":            "JSON",
        }
        payload = _nass_get(params)
        if "data" in payload and payload["data"]:
            frames.append(pd.DataFrame(payload["data"]))
    return _build_df(frames)


# ── Analytics helpers ──────────────────────────────────────────────────────────

def _nearest_week(df: pd.DataFrame, year: int, iso_week: int) -> float:
    """Return the value for the closest ISO week in a given year."""
    sub = df[df["year"] == year]
    if sub.empty:
        return float("nan")
    idx = (sub["iso_week"] - iso_week).abs().idxmin()
    return sub.loc[idx, "Value"]


def olympic_avg(df: pd.DataFrame, ref_year: int, iso_week: int, n: int = 5) -> float:
    """Simple average of the n prior years for the same ISO week."""
    vals = [_nearest_week(df, ref_year - i, iso_week) for i in range(1, n + 1)]
    vals = [v for v in vals if not pd.isna(v)]
    if not vals:
        return float("nan")
    return sum(vals) / len(vals)


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
        {_snap_item("vs 5yr Avg", _dc(kpi['vs_olympic'], '+.1f', ' lb') + ' ' + _dc(kpi['vs_olympic_pct'], '+.1f', '%'))}
      </div>
      <div style="margin-top:8px;font-size:0.7rem;color:{DM_MUTED}">
        5yr avg: {olym_str} lb &nbsp;·&nbsp; {unit_label}
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


def _apply(fig, title="", height=420, y_title="", y_range=None):
    fig.update_layout(**_base_layout(title, height, y_title))
    fig.update_xaxes(**AXIS_STYLE)
    if y_range:
        fig.update_yaxes(**AXIS_STYLE, title_text=y_title, range=y_range)
    else:
        fig.update_yaxes(**AXIS_STYLE, title_text=y_title, autorange=True)


def _tight_range(series, pad_pct=0.04):
    """Return [min, max] with a small padding for a tight Y axis."""
    vals = [v for v in series if v is not None and not pd.isna(v)]
    if not vals:
        return None
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * pad_pct if hi != lo else hi * pad_pct
    return [lo - pad, hi + pad]


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
    default=["GE 500 LBS", "STEERS", "HEIFERS", "COWS", "BULLS"],
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
    raw     = fetch_data(LOAD_YEARS)
    raw_vol = fetch_vol_data(LOAD_YEARS)

if raw.empty:
    st.error("No data returned from USDA NASS. Check your API key in st.secrets.")
    st.stop()

wt  = raw[raw["unit_desc"].str.contains(unit_filter, case=False, na=False)].copy()
# Use dedicated volume fetch; fall back to weight dataset if empty
vol = raw_vol if not raw_vol.empty else raw[raw["unit_desc"].str.upper() == "HEAD"].copy()
wt  = trailing_4wk(wt)

latest_date = wt["week_ending"].max()
latest_year = int(wt.loc[wt["week_ending"] == latest_date, "year"].iloc[0])
latest_iso  = int(wt.loc[wt["week_ending"] == latest_date, "iso_week"].iloc[0])

vol_latest_date = vol["week_ending"].max() if not vol.empty else None

# ── Next Friday calculation ────────────────────────────────────────────────────
_today      = datetime.now().date()
_days_ahead = (4 - _today.weekday()) % 7   # 4 = Friday; 0 means today IS Friday
_next_friday = _today + __import__("datetime").timedelta(days=_days_ahead)

# ── Sidebar data info panel ────────────────────────────────────────────────────
st.sidebar.divider()
st.sidebar.markdown(f"""
<div style="background:{DM_SURFACE2};border:1px solid {DM_BORDER};
  border-left:3px solid {JSA_GREEN};border-radius:6px;padding:12px 14px;font-size:0.78rem">
  <div style="color:{DM_MUTED};font-size:0.65rem;text-transform:uppercase;
    letter-spacing:.08em;margin-bottom:8px">Data Status</div>

  <div style="color:{DM_MUTED};font-size:0.62rem;text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px">Weights</div>
  <div style="display:flex;justify-content:space-between;margin-bottom:2px">
    <span style="color:{DM_MUTED}">Report date</span>
    <span style="color:{DM_TEXT};font-weight:600">{latest_date.strftime('%b %d, %Y')}</span>
  </div>
  <div style="display:flex;justify-content:space-between;margin-bottom:8px">
    <span style="color:{DM_MUTED}">ISO Week</span>
    <span style="color:{DM_TEXT};font-weight:600">Wk {latest_iso}, {latest_year}</span>
  </div>

  <div style="color:{DM_MUTED};font-size:0.62rem;text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px">Slaughter Volume</div>
  <div style="display:flex;justify-content:space-between;margin-bottom:2px">
    <span style="color:{DM_MUTED}">Report date</span>
    <span style="color:{'#fbbf24' if vol_latest_date is not None and vol_latest_date != latest_date else DM_TEXT};font-weight:600">{vol_latest_date.strftime('%b %d, %Y') if vol_latest_date is not None else 'N/A'}</span>
  </div>
  <div style="display:flex;justify-content:space-between;margin-bottom:8px">
    <span style="color:{DM_MUTED}">ISO Week</span>
    <span style="color:{DM_TEXT};font-weight:600">{f"Wk {int(vol_latest_date.isocalendar()[1])}, {vol_latest_date.year}" if vol_latest_date is not None else 'N/A'}</span>
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
          USDA Beef Slaughter Weights
        </div>
        <div style="color:{DM_MUTED};font-size:0.8rem;margin-top:2px">
          Weekly snapshot &nbsp;·&nbsp; USDA NASS QuickStats &nbsp;·&nbsp; Federally Inspected
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)
with hdr_r:
    _vol_str = vol_latest_date.strftime('%b %d, %Y') if vol_latest_date is not None else "N/A"
    _wt_str  = latest_date.strftime('%b %d, %Y')
    _dates_match = vol_latest_date is not None and vol_latest_date == latest_date
    st.markdown(f"""
    <div style="text-align:right;padding-top:6px;font-size:0.75rem">
      <div style="display:flex;justify-content:flex-end;gap:8px;align-items:baseline;margin-bottom:3px">
        <span style="color:{DM_MUTED}">Weights as of</span>
        <span style="color:{DM_TEXT};font-weight:700;font-size:0.95rem">{_wt_str}</span>
      </div>
      <div style="display:flex;justify-content:flex-end;gap:8px;align-items:baseline;margin-bottom:6px">
        <span style="color:{DM_MUTED}">Slaughter vol as of</span>
        <span style="color:{'#fbbf24' if not _dates_match else DM_TEXT};font-weight:700;font-size:0.95rem">{_vol_str}</span>
      </div>
      <div style="display:inline-block;background:{JSA_GREEN};color:#fff;font-size:.68rem;
        font-weight:600;padding:2px 8px;border-radius:3px;letter-spacing:.06em">
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
        {_snap_item("vs 5yr Avg", _dc(kpi['vs_olympic'], '+.0f', ' hd') + ' ' + _dc(kpi['vs_olympic_pct'], '+.1f', '%'))}
      </div>
      <div style="margin-top:8px;font-size:0.7rem;color:{DM_MUTED}">
        5yr avg: {olym_str} head
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
        <th>vs 5yr Avg</th>
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
        <th>vs 5yr Avg</th>
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

tab_trend, tab_yoy, tab_vol, tab_ams, tab_data = st.tabs([
    "📈 Weekly Trend", "📊 Year-over-Year", "🔢 Slaughter Volume",
    "🗓️ AMS Weekly", "📋 Data"
])


# ── Tab 1 — Weekly Trend ───────────────────────────────────────────────────────

with tab_trend:
    cls = trend_class
    sub = wt[wt["class_desc"] == cls].sort_values("week_ending")

    if sub.empty:
        st.warning("No data for selected class.")
    else:
        # Build current year window — all weeks available for latest_year
        curr_yr = sub[sub["year"] == latest_year].sort_values("week_ending")
        # Apply trend window cutoff
        cutoff = curr_yr["week_ending"].max() - pd.Timedelta(weeks=trend_weeks)
        curr_yr = curr_yr[curr_yr["week_ending"] > cutoff]

        # Build an ISO-week → current-year date lookup for aligning all series to same X axis
        iso_to_date = curr_yr.set_index("iso_week")["week_ending"].to_dict()
        x_dates = curr_yr["week_ending"].values
        iso_weeks = curr_yr["iso_week"].values

        # Prior year — map onto current year dates by ISO week
        prev_lookup = sub[sub["year"] == latest_year - 1].set_index("iso_week")["Value"].to_dict()
        prev_y = [prev_lookup.get(w, float("nan")) for w in iso_weeks]

        # 5yr avg and range — mapped to current year dates
        olym_map = olympic_series(sub, latest_year)
        olym_y    = [olym_map.get(w, float("nan")) for w in iso_weeks]
        olym_highs, olym_lows = [], []
        for w in iso_weeks:
            yr_vals = [_nearest_week(sub, latest_year - i, w) for i in range(1, 6)]
            yr_vals = [v for v in yr_vals if not pd.isna(v)]
            olym_highs.append(max(yr_vals) if yr_vals else float("nan"))
            olym_lows.append(min(yr_vals) if yr_vals else float("nan"))

        # 4-week rolling avg for current year
        sub_roll = sub[sub["year"] == latest_year].sort_values("week_ending").copy()
        sub_roll["t4w"] = sub_roll["Value"].rolling(4, min_periods=1).mean()
        roll_lookup = sub_roll.set_index("iso_week")["t4w"].to_dict()
        roll_y = [roll_lookup.get(w, float("nan")) for w in iso_weeks]

        fig = go.Figure()

        # 5yr range band
        fig.add_trace(go.Scatter(
            x=list(x_dates) + list(x_dates)[::-1],
            y=olym_highs + olym_lows[::-1],
            fill="toself", fillcolor="rgba(122,153,144,0.12)",
            line=dict(color="rgba(0,0,0,0)"),
            name="5yr Range", hoverinfo="skip", showlegend=True,
        ))

        # 5yr avg line
        fig.add_trace(go.Scatter(
            x=x_dates, y=olym_y,
            name="5yr Avg", mode="lines",
            line=dict(color="rgba(122,153,144,0.7)", width=1.8, dash="dash"),
            hovertemplate="5yr avg: %{y:,.1f} lb<extra></extra>",
        ))

        # Prior year — same X dates as current year
        fig.add_trace(go.Scatter(
            x=x_dates, y=prev_y,
            name=str(latest_year - 1), mode="lines",
            line=dict(color="rgba(224,232,240,0.5)", width=1.5, dash="dot"),
            hovertemplate=f"{latest_year-1}: %{{y:,.1f}} lb<extra></extra>",
        ))

        # Current year
        fig.add_trace(go.Scatter(
            x=x_dates, y=curr_yr["Value"].values,
            name=str(latest_year), mode="lines+markers",
            line=dict(color=JPSI_GREEN, width=2.5),
            marker=dict(size=5, color=JPSI_GREEN),
            hovertemplate=f"{latest_year}: %{{y:,.1f}} lb<extra></extra>",
        ))

        # 4-week rolling avg
        fig.add_trace(go.Scatter(
            x=x_dates, y=roll_y,
            name="4-Wk Rolling Avg", mode="lines",
            line=dict(color="#fbbf24", width=2, dash="dashdot"),
            hovertemplate="4-wk avg: %{y:,.1f} lb<extra></extra>",
        ))

        _wt_vals = list(curr_yr["Value"]) + [v for v in prev_y if not pd.isna(v)] + [v for v in olym_y if not pd.isna(v)]
        _apply(fig, f"{cls.title()} — {weight_unit} · Last {trend_weeks} Weeks", 440, "lb / head",
               y_range=_tight_range(_wt_vals))
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
            name="5yr Avg",
            mode="lines",
            line=dict(color="rgba(122,153,144,0.7)", width=1.8, dash="dash"),
            hovertemplate="5yr avg: %{y:,.1f} lb<extra></extra>",
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
            name="5yr Avg",
            mode="lines+markers",
            line=dict(color=DM_MUTED, dash="dash", width=1.5),
            hovertemplate="5yr avg: %{y:,.1f} lb<extra></extra>",
        ))
        _apply(fig4, f"ISO Week {latest_iso} — Historical Comparison", 300, "lb / head")
        fig4.update_xaxes(tickmode="linear", dtick=1)
        st.plotly_chart(fig4, use_container_width=True)

        # ── YoY delta vs Olympic avg ──────────────────────────────────────────
        st.markdown('<div class="sec-hdr">Current Year vs 5yr Avg — Weekly Delta</div>', unsafe_allow_html=True)
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
        _apply(fig5, f"{ly_max} vs 5yr Avg — Weekly \u0394", 260, "\u0394 lb / head")
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
        _vol_vals = [v for cls in vol_cls
                     for v in vol[(vol["class_desc"]==cls)&(vol["week_ending"]>vol_cutoff)]["Value"]]
        _apply(fig6, f"Weekly Slaughter — Head Count · Last {trend_weeks} Weeks", 420, "Head",
               y_range=_tight_range(_vol_vals))
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


# ── Tab 4 — AMS Weekly ────────────────────────────────────────────────────────

with tab_ams:
    with st.spinner("Loading AMS weekly report…"):
        ams = fetch_ams_weekly()

    if "error" in ams:
        st.error(f"Could not load AMS report: {ams['error']}")
    else:
        slaughter  = ams.get("slaughter", {})
        wts        = ams.get("weights", {})
        class_mix  = ams.get("class_mix", {})
        meat_prod  = ams.get("meat_prod", {})
        rpt_date   = ams.get("report_date")

        # ── Header ──────────────────────────────────────────────────────────────
        dated_keys = [k for k in slaughter if isinstance(k, __builtins__.__class__.__mro__[0] if False else type(rpt_date)) and not isinstance(k, str)]
        dated_keys = sorted([k for k in slaughter if not isinstance(k, str)], reverse=True)
        curr_date  = dated_keys[0] if dated_keys else None
        prev_date  = dated_keys[1] if len(dated_keys) > 1 else None
        yago_date  = dated_keys[2] if len(dated_keys) > 2 else None

        st.markdown(f"""
        <div style="display:flex;align-items:center;justify-content:space-between;
          background:{DM_SURFACE2};border:1px solid {DM_BORDER};
          border-left:4px solid {JSA_GREEN};border-radius:6px;
          padding:12px 18px;margin-bottom:16px">
          <div>
            <div style="color:{DM_TEXT};font-size:1.05rem;font-weight:700">
              AMS Weekly — Livestock Slaughter &amp; Weights
            </div>
            <div style="color:{DM_MUTED};font-size:0.75rem;margin-top:2px">
              USDA Agricultural Marketing Service · Livestock, Poultry &amp; Grain Market News ·
              More current than NASS — updated weekly (Fridays)
            </div>
          </div>
          <div style="text-align:right">
            <div style="color:{DM_MUTED};font-size:0.68rem;text-transform:uppercase;letter-spacing:.06em">Week Ending</div>
            <div style="color:{JSA_GREEN_LT};font-size:1.1rem;font-weight:700">
              {curr_date.strftime('%b %d, %Y') if curr_date else 'N/A'}
            </div>
            <div style="color:{DM_MUTED};font-size:0.68rem">
              Report date: {rpt_date.strftime('%b %d, %Y') if rpt_date else 'N/A'}
            </div>
          </div>
        </div>
        """, unsafe_allow_html=True)

        # ── Slaughter Head Count tiles ────────────────────────────────────────
        species = ["Cattle", "Calves", "Hogs", "Sheep"]
        sp_colors = {"Cattle": JSA_GREEN_LT, "Calves": "#c4b456", "Hogs": "#c98a56", "Sheep": "#6fa8c4"}

        st.markdown(f'<div class="sec-hdr">Slaughter Head Count</div>', unsafe_allow_html=True)
        cols_sp = st.columns(4)
        for col, sp in zip(cols_sp, species):
            curr_val = slaughter.get(curr_date, {}).get(sp, float("nan")) if curr_date else float("nan")
            prev_val = slaughter.get(prev_date, {}).get(sp, float("nan")) if prev_date else float("nan")
            yago_val = slaughter.get(yago_date, {}).get(sp, float("nan")) if yago_date else float("nan")
            wow      = curr_val - prev_val if not (pd.isna(curr_val) or pd.isna(prev_val)) else float("nan")
            wow_pct  = wow / prev_val * 100 if prev_val else float("nan")
            yoy      = curr_val - yago_val if not (pd.isna(curr_val) or pd.isna(yago_val)) else float("nan")
            yoy_pct  = yoy / yago_val * 100 if yago_val else float("nan")
            ytd_curr = slaughter.get(f"YTD_{curr_date.year if curr_date else ''}", {}).get(sp, float("nan"))
            ytd_prev = slaughter.get(f"YTD_{(curr_date.year-1) if curr_date else ''}", {}).get(sp, float("nan"))
            ytd_chg  = (ytd_curr - ytd_prev) / ytd_prev * 100 if not (pd.isna(ytd_curr) or pd.isna(ytd_prev) or ytd_prev == 0) else float("nan")

            def _fd(v, pct=False):
                if pd.isna(v): return "—"
                return f"{v:+.1f}%" if pct else f"{v:+,.0f}"
            def _fc(v): return COL_POS if (not pd.isna(v) and v >= 0) else COL_NEG

            cv_str      = "—" if pd.isna(curr_val) else f"{curr_val:,.0f}"
            wow_str     = _fd(wow_pct, True)
            yoy_str     = _fd(yoy_pct, True)
            ytd_str     = _fd(ytd_chg, True)
            wow_col     = _fc(wow)
            yoy_col     = _fc(yoy)
            ytd_col     = _fc(ytd_chg)
            top_color   = sp_colors.get(sp, JSA_GREEN)

            col.markdown(f"""
            <div style="background:{DM_SURFACE};border:1px solid {DM_BORDER};
              border-top:3px solid {top_color};
              border-radius:6px;padding:14px 16px;height:100%">
              <div style="color:{DM_MUTED};font-size:0.68rem;text-transform:uppercase;
                letter-spacing:.07em;margin-bottom:6px">{sp}</div>
              <div style="color:{DM_TEXT};font-size:1.5rem;font-weight:700;margin-bottom:8px">
                {cv_str}
              </div>
              <div style="display:flex;gap:6px;flex-wrap:wrap">
                <span style="background:{DM_SURFACE2};border-radius:3px;
                  padding:2px 7px;font-size:0.68rem;color:{wow_col}">
                  WoW {wow_str}
                </span>
                <span style="background:{DM_SURFACE2};border-radius:3px;
                  padding:2px 7px;font-size:0.68rem;color:{yoy_col}">
                  YoY {yoy_str}
                </span>
              </div>
              <div style="margin-top:8px;color:{DM_MUTED};font-size:0.7rem">
                YTD: <span style="color:{ytd_col}">{ytd_str}</span>
                vs prior year
              </div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)

        # ── Average Weight tiles (Cattle only — most relevant) ─────────────────
        st.markdown(f'<div class="sec-hdr">Cattle Average Weights</div>', unsafe_allow_html=True)
        wt_cols = st.columns(4)
        wt_meta = [
            ("Live — Current Wk",    "live",    "Cattle", curr_date, prev_date, yago_date),
            ("Live — Prev Wk",       "live",    "Cattle", prev_date, yago_date, None),
            ("Dressed — Current Wk", "dressed", "Cattle", curr_date, prev_date, yago_date),
            ("Dressed — Prev Wk",    "dressed", "Cattle", prev_date, yago_date, None),
        ]
        for col, (label, basis, sp, c_d, p_d, y_d) in zip(wt_cols, wt_meta):
            cv = wts.get(basis, {}).get(c_d, {}).get(sp, float("nan")) if c_d else float("nan")
            pv = wts.get(basis, {}).get(p_d, {}).get(sp, float("nan")) if p_d else float("nan")
            yv = wts.get(basis, {}).get(y_d, {}).get(sp, float("nan")) if y_d else float("nan")
            wow_w = cv - pv if not (pd.isna(cv) or pd.isna(pv)) else float("nan")
            yoy_w = cv - yv if not (pd.isna(cv) or pd.isna(yv)) else float("nan")

            cv_str_w  = "—" if pd.isna(cv) else f"{cv:,.0f} lb"
            wow_str_w = "—" if pd.isna(wow_w) else f"{wow_w:+.1f} lb"
            yoy_str_w = "—" if pd.isna(yoy_w) else f"{yoy_w:+.1f} lb"
            wow_col_w = COL_POS if (not pd.isna(wow_w) and wow_w >= 0) else COL_NEG
            yoy_col_w = COL_POS if (not pd.isna(yoy_w) and yoy_w >= 0) else COL_NEG
            yoy_span  = f'<span style="background:{DM_SURFACE2};border-radius:3px;padding:2px 7px;font-size:0.68rem;color:{yoy_col_w}">YoY {yoy_str_w}</span>' if y_d else ""

            col.markdown(f"""
            <div style="background:{DM_SURFACE};border:1px solid {DM_BORDER};
              border-top:3px solid {JSA_GREEN};border-radius:6px;padding:14px 16px">
              <div style="color:{DM_MUTED};font-size:0.68rem;text-transform:uppercase;
                letter-spacing:.07em;margin-bottom:6px">{label}</div>
              <div style="color:{DM_TEXT};font-size:1.5rem;font-weight:700;margin-bottom:8px">
                {cv_str_w}
              </div>
              <div style="display:flex;gap:6px;flex-wrap:wrap">
                <span style="background:{DM_SURFACE2};border-radius:3px;
                  padding:2px 7px;font-size:0.68rem;color:{wow_col_w}">
                  WoW {wow_str_w}
                </span>
                {yoy_span}
              </div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)

        # ── Cattle Class Mix chart ────────────────────────────────────────────
        if class_mix:
            st.markdown(f'<div class="sec-hdr">Cattle Class Mix</div>', unsafe_allow_html=True)
            mix_dates = sorted(class_mix.keys(), reverse=True)
            mix_labels = ["Steers", "Heifers", "Cows", "Bulls"]
            mix_colors = [CLASS_COLORS["STEERS"], CLASS_COLORS["HEIFERS"],
                          CLASS_COLORS["COWS"], CLASS_COLORS["BULLS"]]

            def _hex_to_rgba(h, a=1.0):
                h = h.lstrip("#")
                r, g, b = int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)
                return f"rgba({r},{g},{b},{a})"

            fig_mix = go.Figure()
            for i, md in enumerate(mix_dates[:2]):
                row = class_mix[md]
                colors = mix_colors if i == 0 else [_hex_to_rgba(c, 0.45) for c in mix_colors]
                fig_mix.add_trace(go.Bar(
                    name=md.strftime("Wk %b %d, %Y"),
                    x=mix_labels,
                    y=[row.get(l, 0) for l in mix_labels],
                    marker_color=colors,
                    text=[f"{row.get(l, 0):.1f}%" for l in mix_labels],
                    textposition="outside",
                ))
            fig_mix.update_layout(
                barmode="group",
                **_base_layout("Cattle Slaughtered by Class (%)", 340),
                yaxis=dict(ticksuffix="%", **AXIS_STYLE),
                xaxis=dict(**AXIS_STYLE),
                showlegend=True,
            )
            st.plotly_chart(fig_mix, use_container_width=True)

        # ── Meat Production table ─────────────────────────────────────────────
        if meat_prod:
            st.markdown(f'<div class="sec-hdr">Weekly Meat Production (million lbs)</div>',
                        unsafe_allow_html=True)
            mp_rows = []
            for d, vals in sorted(meat_prod.items(), reverse=True):
                mp_rows.append({"Week Ending": d, **vals})
            mp_df = pd.DataFrame(mp_rows)
            st.dataframe(
                mp_df, use_container_width=True, hide_index=True,
                column_config={"Week Ending": st.column_config.DateColumn(format="MM/DD/YYYY")},
            )

        st.markdown(f"""
        <div style="color:{DM_MUTED};font-size:0.68rem;margin-top:12px">
          Source: USDA AMS Livestock, Poultry &amp; Grain Market News ·
          Report <code style="color:{DM_MUTED}">SJ_LS712</code> · Updated Fridays
        </div>
        """, unsafe_allow_html=True)


# ── Tab 5 — Data ───────────────────────────────────────────────────────────────

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
