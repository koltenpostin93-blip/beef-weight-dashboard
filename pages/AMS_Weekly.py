import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import requests
import re
from datetime import datetime

# ── Brand colors (mirror app.py) ──────────────────────────────────────────────
JSA_GREEN    = "#5e7164"
JSA_GREEN_LT = "#8db89a"
DM_BG        = "#0d1210"
DM_SURFACE   = "#141c18"
DM_SURFACE2  = "#1a2620"
DM_BORDER    = "#253328"
DM_TEXT      = "#e8ede9"
DM_MUTED     = "#7a9485"
COL_POS      = "#8db89a"
COL_NEG      = "#e07070"

CLASS_COLORS = {
    "STEERS":  "#8db89a",
    "HEIFERS": "#6fa8c4",
    "COWS":    "#c98a56",
    "BULLS":   "#9b89c4",
}

JSA_LOGO_FULL = "https://www.jpsi.com/wp-content/themes/gate39media/img/logo-full.png"
AMS_URL       = "https://www.ams.usda.gov/mnreports/sj_ls712.txt"

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="AMS Weekly Slaughter",
    page_icon="🐄",
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
  .sec-hdr {{
    color:{DM_MUTED}; font-size:0.72rem; text-transform:uppercase;
    letter-spacing:.1em; margin:14px 0 6px;
  }}
  div[data-testid="stDataFrame"] {{ background:{DM_SURFACE}; border-radius:8px; }}
</style>
""", unsafe_allow_html=True)

AXIS_STYLE = dict(gridcolor=DM_BORDER, linecolor=DM_BORDER, showgrid=True)

def _base_layout(title="", height=400):
    return dict(
        title=dict(text=title, font=dict(color=DM_TEXT, size=13), x=0),
        paper_bgcolor=DM_SURFACE2, plot_bgcolor=DM_SURFACE2,
        font=dict(color=DM_TEXT, size=11),
        legend=dict(bgcolor="rgba(0,0,0,0)", borderwidth=0),
        margin=dict(l=50, r=20, t=40, b=40),
        hovermode="x unified", height=height,
    )

def _hex_to_rgba(h, a=1.0):
    h = h.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{a})"

# ── Data fetch & parse ────────────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_ams_weekly() -> dict:
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

    # Report date
    m = re.search(r"(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\w+\s+\d+,\s+\d{4})", text)
    if m:
        try:
            result["report_date"] = datetime.strptime(m.group(2).strip(), "%b %d, %Y").date()
        except ValueError:
            result["report_date"] = None

    # Slaughter head counts
    slaughter = {}
    m = re.search(r"Livestock Slaughter \(head\)(.*?)(?:----)", text, re.DOTALL)
    if m:
        cols = ["Cattle", "Calves", "Hogs", "Sheep"]
        for line in m.group(1).splitlines():
            parts = line.strip().split()
            if not parts:
                continue
            d = _parse_date(parts[0])
            if d and len(parts) >= 5:
                slaughter[d] = dict(zip(cols, [_num(p) for p in parts[1:5]]))
            elif len(parts) >= 6 and parts[1] == "YTD":
                slaughter[f"YTD_{parts[0]}"] = dict(zip(cols, [_num(p) for p in parts[2:6]]))
    result["slaughter"] = slaughter

    # Average weights
    weights = {"live": {}, "dressed": {}}
    m = re.search(r"Average Weights \(lbs\)(.*?)(?:----)", text, re.DOTALL)
    if m:
        mode = None
        for line in m.group(1).splitlines():
            line = line.strip()
            if not line:
                continue
            if re.search(r"Live:", line, re.IGNORECASE):
                mode = "live"
            elif re.search(r"Dressed:", line, re.IGNORECASE):
                mode = "dressed"
            if mode is None:
                continue
            parts = line.split()
            d = _parse_date(parts[0]) if parts else None
            if d:
                nums = []
                for p in parts[1:]:
                    try:
                        nums.append(float(p.replace(",", "")))
                    except ValueError:
                        continue
                if len(nums) >= 4:
                    weights[mode][d] = {
                        "Cattle": nums[0], "Calves": nums[1],
                        "Hogs": nums[2], "Sheep": nums[3],
                    }
    result["weights"] = weights

    # Cattle class mix %
    class_mix = {}
    m = re.search(r"Percentage of Total Cattle Slaughtered by Class(.*?)(?:----|\Z)", text, re.DOTALL)
    if m:
        for line in m.group(1).splitlines():
            parts = line.strip().split()
            d = _parse_date(parts[0]) if parts else None
            if d and len(parts) >= 5:
                class_mix[d] = dict(zip(["Steers", "Heifers", "Cows", "Bulls"],
                                        [_num(p) for p in parts[1:5]]))
    result["class_mix"] = class_mix

    # Meat production
    meat_prod = {}
    m = re.search(r"Meat Production \(millions of pounds\)(.*?)(?:----)", text, re.DOTALL)
    if m:
        for line in m.group(1).splitlines():
            parts = line.strip().split()
            d = _parse_date(parts[0]) if parts else None
            if d and len(parts) >= 5:
                vals = [_num(p) for p in parts[1:6]]
                meat_prod[d] = {
                    "Beef": vals[0], "Calf/Veal": vals[1],
                    "Pork": vals[2], "Lamb": vals[3], "Total": vals[4],
                }
    result["meat_prod"] = meat_prod

    return result


# ── Load ──────────────────────────────────────────────────────────────────────
with st.spinner("Loading AMS weekly report…"):
    ams = fetch_ams_weekly()

if "error" in ams:
    st.error(f"Could not load AMS report: {ams['error']}")
    st.stop()

slaughter = ams.get("slaughter", {})
wts       = ams.get("weights", {})
class_mix = ams.get("class_mix", {})
meat_prod = ams.get("meat_prod", {})
rpt_date  = ams.get("report_date")

dated_keys = sorted([k for k in slaughter if not isinstance(k, str)], reverse=True)
curr_date  = dated_keys[0] if dated_keys else None
prev_date  = dated_keys[1] if len(dated_keys) > 1 else None
yago_date  = dated_keys[2] if len(dated_keys) > 2 else None

# ── Header ────────────────────────────────────────────────────────────────────
hdr_l, hdr_r = st.columns([3, 1])
with hdr_l:
    st.markdown(f"""
    <div style="display:flex;align-items:center;gap:18px;padding:6px 0 2px">
      <img src="{JSA_LOGO_FULL}" style="height:48px" />
      <div>
        <div style="font-size:1.45rem;font-weight:700;color:{DM_TEXT};line-height:1.1">
          AMS Weekly Livestock Slaughter
        </div>
        <div style="color:{DM_MUTED};font-size:0.8rem;margin-top:2px">
          USDA Agricultural Marketing Service · Livestock, Poultry &amp; Grain Market News · Federally Inspected
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)
with hdr_r:
    wk_str  = curr_date.strftime("%b %d, %Y") if curr_date else "N/A"
    rpt_str = rpt_date.strftime("%b %d, %Y") if rpt_date else "N/A"
    st.markdown(f"""
    <div style="text-align:right;padding-top:6px;font-size:0.75rem">
      <div style="display:flex;justify-content:flex-end;gap:8px;align-items:baseline;margin-bottom:3px">
        <span style="color:{DM_MUTED}">Week ending</span>
        <span style="color:{DM_TEXT};font-weight:700;font-size:0.95rem">{wk_str}</span>
      </div>
      <div style="display:flex;justify-content:flex-end;gap:8px;align-items:baseline">
        <span style="color:{DM_MUTED}">Report date</span>
        <span style="color:{DM_TEXT};font-weight:700;font-size:0.95rem">{rpt_str}</span>
      </div>
    </div>
    """, unsafe_allow_html=True)

st.divider()

# ── Helpers ───────────────────────────────────────────────────────────────────
def _fd(v, pct=False):
    if pd.isna(v): return "—"
    return f"{v:+.1f}%" if pct else f"{v:+,.0f}"

def _fc(v): return COL_POS if (not pd.isna(v) and v >= 0) else COL_NEG

# ── Slaughter head count tiles ────────────────────────────────────────────────
st.markdown(f'<div class="sec-hdr">Slaughter Head Count — Week Ending {wk_str}</div>',
            unsafe_allow_html=True)

sp_colors = {"Cattle": JSA_GREEN_LT, "Calves": "#c4b456", "Hogs": "#c98a56", "Sheep": "#6fa8c4"}
species   = ["Cattle", "Calves", "Hogs", "Sheep"]

cols_sp = st.columns(4)
for col, sp in zip(cols_sp, species):
    curr_val = slaughter.get(curr_date, {}).get(sp, float("nan")) if curr_date else float("nan")
    prev_val = slaughter.get(prev_date, {}).get(sp, float("nan")) if prev_date else float("nan")
    yago_val = slaughter.get(yago_date, {}).get(sp, float("nan")) if yago_date else float("nan")
    wow      = curr_val - prev_val if not (pd.isna(curr_val) or pd.isna(prev_val)) else float("nan")
    wow_pct  = wow / prev_val * 100 if (not pd.isna(prev_val) and prev_val != 0) else float("nan")
    yoy      = curr_val - yago_val if not (pd.isna(curr_val) or pd.isna(yago_val)) else float("nan")
    yoy_pct  = yoy / yago_val * 100 if (not pd.isna(yago_val) and yago_val != 0) else float("nan")
    ytd_curr = slaughter.get(f"YTD_{curr_date.year if curr_date else ''}", {}).get(sp, float("nan"))
    ytd_prev = slaughter.get(f"YTD_{(curr_date.year - 1) if curr_date else ''}", {}).get(sp, float("nan"))
    ytd_chg  = (ytd_curr - ytd_prev) / ytd_prev * 100 if (not (pd.isna(ytd_curr) or pd.isna(ytd_prev)) and ytd_prev != 0) else float("nan")

    cv_str   = "—" if pd.isna(curr_val) else f"{curr_val:,.0f}"
    top_col  = sp_colors.get(sp, JSA_GREEN)

    col.markdown(f"""
    <div style="background:{DM_SURFACE};border:1px solid {DM_BORDER};
      border-top:3px solid {top_col};border-radius:6px;padding:14px 16px">
      <div style="color:{DM_MUTED};font-size:0.68rem;text-transform:uppercase;
        letter-spacing:.07em;margin-bottom:6px">{sp}</div>
      <div style="color:{DM_TEXT};font-size:1.7rem;font-weight:700;margin-bottom:10px">
        {cv_str}
      </div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:6px">
        <span style="background:{DM_SURFACE2};border-radius:3px;
          padding:2px 8px;font-size:0.7rem;color:{_fc(wow)}">
          WoW {_fd(wow_pct, True)}
        </span>
        <span style="background:{DM_SURFACE2};border-radius:3px;
          padding:2px 8px;font-size:0.7rem;color:{_fc(yoy)}">
          YoY {_fd(yoy_pct, True)}
        </span>
      </div>
      <div style="color:{DM_MUTED};font-size:0.7rem">
        YTD vs prior yr: <span style="color:{_fc(ytd_chg)}">{_fd(ytd_chg, True)}</span>
      </div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)

# ── Average weight tiles — Cattle ─────────────────────────────────────────────
st.markdown(f'<div class="sec-hdr">Cattle Average Weights</div>', unsafe_allow_html=True)

wt_cols = st.columns(4)
wt_meta = [
    ("Live — Current Wk",    "live",    curr_date, prev_date, yago_date),
    ("Live — Prior Wk",      "live",    prev_date, yago_date, None),
    ("Dressed — Current Wk", "dressed", curr_date, prev_date, yago_date),
    ("Dressed — Prior Wk",   "dressed", prev_date, yago_date, None),
]
for col, (label, basis, c_d, p_d, y_d) in zip(wt_cols, wt_meta):
    cv = wts.get(basis, {}).get(c_d, {}).get("Cattle", float("nan")) if c_d else float("nan")
    pv = wts.get(basis, {}).get(p_d, {}).get("Cattle", float("nan")) if p_d else float("nan")
    yv = wts.get(basis, {}).get(y_d, {}).get("Cattle", float("nan")) if y_d else float("nan")
    wow_w = cv - pv if not (pd.isna(cv) or pd.isna(pv)) else float("nan")
    yoy_w = cv - yv if not (pd.isna(cv) or pd.isna(yv)) else float("nan")

    cv_s   = "—" if pd.isna(cv) else f"{cv:,.0f} lb"
    wow_s  = "—" if pd.isna(wow_w) else f"{wow_w:+.1f} lb"
    yoy_s  = "—" if pd.isna(yoy_w) else f"{yoy_w:+.1f} lb"
    yoy_sp = f'<span style="background:{DM_SURFACE2};border-radius:3px;padding:2px 8px;font-size:0.7rem;color:{_fc(yoy_w)}">YoY {yoy_s}</span>' if y_d else ""

    col.markdown(f"""
    <div style="background:{DM_SURFACE};border:1px solid {DM_BORDER};
      border-top:3px solid {JSA_GREEN};border-radius:6px;padding:14px 16px">
      <div style="color:{DM_MUTED};font-size:0.68rem;text-transform:uppercase;
        letter-spacing:.07em;margin-bottom:6px">{label}</div>
      <div style="color:{DM_TEXT};font-size:1.7rem;font-weight:700;margin-bottom:10px">
        {cv_s}
      </div>
      <div style="display:flex;gap:6px;flex-wrap:wrap">
        <span style="background:{DM_SURFACE2};border-radius:3px;
          padding:2px 8px;font-size:0.7rem;color:{_fc(wow_w)}">
          WoW {wow_s}
        </span>
        {yoy_sp}
      </div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)

# ── Charts ────────────────────────────────────────────────────────────────────
chart_l, chart_r = st.columns([1, 1])

with chart_l:
    # Head count trend — current wk vs prior wk vs year ago
    if dated_keys:
        st.markdown(f'<div class="sec-hdr">Slaughter Head Count Comparison</div>',
                    unsafe_allow_html=True)
        sp_list = ["Cattle", "Calves", "Hogs", "Sheep"]
        curr_vals = [slaughter.get(curr_date, {}).get(s, 0) for s in sp_list]
        prev_vals = [slaughter.get(prev_date, {}).get(s, 0) for s in sp_list] if prev_date else [0]*4
        yago_vals = [slaughter.get(yago_date, {}).get(s, 0) for s in sp_list] if yago_date else [0]*4

        fig_bar = go.Figure()
        for label, vals, color in [
            (curr_date.strftime("Wk %b %d, %Y") if curr_date else "Current", curr_vals, JSA_GREEN_LT),
            (prev_date.strftime("Wk %b %d, %Y") if prev_date else "Prior Wk", prev_vals, _hex_to_rgba(JSA_GREEN_LT, 0.55)),
            (yago_date.strftime("Wk %b %d, %Y") if yago_date else "Year Ago", yago_vals, _hex_to_rgba(JSA_GREEN_LT, 0.25)),
        ]:
            fig_bar.add_trace(go.Bar(name=label, x=sp_list, y=vals, marker_color=color))
        fig_bar.update_layout(barmode="group", **_base_layout("Head Count by Species", 360),
                              xaxis=dict(**AXIS_STYLE), yaxis=dict(**AXIS_STYLE))
        st.plotly_chart(fig_bar, use_container_width=True)

with chart_r:
    # Cattle class mix
    if class_mix:
        st.markdown(f'<div class="sec-hdr">Cattle Class Mix (%)</div>', unsafe_allow_html=True)
        mix_dates  = sorted(class_mix.keys(), reverse=True)
        mix_labels = ["Steers", "Heifers", "Cows", "Bulls"]
        mix_colors = [CLASS_COLORS["STEERS"], CLASS_COLORS["HEIFERS"],
                      CLASS_COLORS["COWS"],   CLASS_COLORS["BULLS"]]

        fig_mix = go.Figure()
        for i, md in enumerate(mix_dates[:2]):
            row    = class_mix[md]
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
            barmode="group", showlegend=True,
            **_base_layout("Cattle Slaughtered by Class", 360),
            xaxis=dict(**AXIS_STYLE),
            yaxis=dict(ticksuffix="%", **AXIS_STYLE),
        )
        st.plotly_chart(fig_mix, use_container_width=True)

st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

# ── Meat production table ─────────────────────────────────────────────────────
if meat_prod:
    st.markdown(f'<div class="sec-hdr">Weekly Meat Production (million lbs)</div>',
                unsafe_allow_html=True)
    mp_rows = [{"Week Ending": d, **vals} for d, vals in sorted(meat_prod.items(), reverse=True)]
    mp_df   = pd.DataFrame(mp_rows)
    st.dataframe(
        mp_df, use_container_width=True, hide_index=True,
        column_config={"Week Ending": st.column_config.DateColumn(format="MM/DD/YYYY")},
    )

# ── Sidebar info ──────────────────────────────────────────────────────────────
st.sidebar.markdown(f"""
<div style="background:{DM_SURFACE2};border:1px solid {DM_BORDER};
  border-left:3px solid {JSA_GREEN};border-radius:6px;padding:12px 14px;font-size:0.78rem">
  <div style="color:{DM_MUTED};font-size:0.65rem;text-transform:uppercase;
    letter-spacing:.08em;margin-bottom:8px">Data Status</div>

  <div style="display:flex;justify-content:space-between;margin-bottom:6px">
    <span style="color:{DM_MUTED}">Week ending</span>
    <span style="color:{DM_TEXT};font-weight:600">{wk_str}</span>
  </div>
  <div style="display:flex;justify-content:space-between;margin-bottom:6px">
    <span style="color:{DM_MUTED}">Report date</span>
    <span style="color:{DM_TEXT};font-weight:600">{rpt_str}</span>
  </div>
  <div style="display:flex;justify-content:space-between;margin-bottom:6px">
    <span style="color:{DM_MUTED}">Update day</span>
    <span style="color:{DM_TEXT};font-weight:600">Fridays</span>
  </div>

  <div style="border-top:1px solid {DM_BORDER};margin:8px 0"></div>
  <div style="color:{DM_MUTED};font-size:0.68rem;line-height:1.5">
    Source: USDA AMS<br>
    Livestock, Poultry &amp; Grain Market News<br>
    Report SJ_LS712<br>
    Cache refreshes every hour
  </div>
</div>
""", unsafe_allow_html=True)

st.markdown(f"""
<div style="color:{DM_MUTED};font-size:0.68rem;margin-top:16px">
  Source: USDA AMS Livestock, Poultry &amp; Grain Market News ·
  Report <code style="color:{DM_MUTED}">SJ_LS712</code> · Updated Fridays
</div>
""", unsafe_allow_html=True)
