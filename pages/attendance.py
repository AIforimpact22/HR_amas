import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
import datetime, math

# ─── DB engine (cached) ────────────────────────────────────────────────────
if "pg_engine" not in st.session_state:
    st.session_state.pg_engine = create_engine(
        st.secrets["neon"]["dsn"], pool_pre_ping=True, echo=False
    )
engine = st.session_state.pg_engine

SHIFT_HOURS = 8.5  # normal hours per shift

# ─── Data helpers ──────────────────────────────────────────────────────────
def fetch_attendance(start: datetime.date, end: datetime.date) -> pd.DataFrame:
    sql = text("""
        SELECT  a.employeeid,
                e.fullname,
                a.punch_date,
                a.clock_in,
                a.clock_out,
            EXTRACT(EPOCH FROM (COALESCE(a.clock_out, NOW()) - a.clock_in))/3600
                AS hours_worked
        FROM hr_attendance a
        JOIN hr_employee   e USING (employeeid)
        WHERE a.punch_date BETWEEN :start AND :end
        ORDER BY a.employeeid
    """)
    return pd.read_sql(sql, engine, params={"start": start, "end": end})

def aggregate(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["employeeid","fullname","days","hours","expected","delta"])
    g = df.groupby(["employeeid","fullname"])
    agg = g.agg(
        days=("punch_date","nunique"),
        hours=("hours_worked","sum")
    ).reset_index()
    agg["expected"] = agg["days"] * SHIFT_HOURS
    agg["delta"] = agg["hours"] - agg["expected"]
    return agg.sort_values("fullname")

# ─── Date helpers ─────────────────────────────────────────────────────────
TODAY = datetime.date.today()
PAST_30 = TODAY - datetime.timedelta(days=365*30)
FUTURE_30 = TODAY + datetime.timedelta(days=365*30)

# ─── UI ───────────────────────────────────────────────────────────────────
st.set_page_config("Attendance","⏱",layout="wide")
st.title("⏱ Attendance Dashboard")

scope = st.radio(
    "Time scope",
    ["Today","This week","This month","This year","Custom"],
    horizontal=True
)

if scope == "Today":
    start = end = TODAY
elif scope == "This week":
    start = TODAY - datetime.timedelta(days=TODAY.weekday())
    end = TODAY
elif scope == "This month":
    start = TODAY.replace(day=1)
    end = TODAY
elif scope == "This year":
    start = TODAY.replace(month=1, day=1)
    end = TODAY
else:  # custom
    start, end = st.date_input("Pick date range", (TODAY, TODAY))
    if isinstance(start, tuple): start, end = start
    if start > end: st.error("Start date after end date"); st.stop()
    if (end-start).days > 365: st.error("≤ 365‑day range only"); st.stop()

raw = fetch_attendance(start, end)
summary = aggregate(raw)

st.subheader(f"Summary  {start:%Y‑%m‑%d} → {end:%Y‑%m‑%d}")
st.dataframe(
    summary.style.format({"hours":"{:.2f}","expected":"{:.1f}","delta":"{:+.2f}"}),
    use_container_width=True
)

# ─── Single‑day card grid ────────────────────────────────────────────────
if start == end:
    st.subheader("Detail cards (in/out/hours)")
    if raw.empty:
        st.info("No punches for this day.")
    else:
        # tidy for card rendering
        raw["clock_in"]  = pd.to_datetime(raw["clock_in"]).dt.strftime("%H:%M")
        raw["clock_out"] = pd.to_datetime(raw["clock_out"]).dt.strftime("%H:%M")
        # ensure uniqueOne row per employee (UNIQUE constraint)
        cards = raw.sort_values("fullname").to_dict("records")

        COLS = 5
        ROWS = math.ceil(len(cards) / COLS)
        card_iter = iter(cards)

        card_css = """
        <style>
        .att-card {
            border:1px solid #DDD; border-radius:6px; padding:8px 10px;
            height:100px;
        }
        .att-card h4 {font-size:0.9rem; margin:0 0 4px;}
        .att-card .small {font-size:0.78rem; color:#555;}
        </style>
        """
        st.markdown(card_css, unsafe_allow_html=True)

        for _ in range(ROWS):
            cols = st.columns(COLS, gap="small")
            for col in cols:
                try:
                    c = next(card_iter)
                except StopIteration:
                    col.empty()
                    continue
                with col.container():
                    col.markdown(f"""
<div class="att-card">
  <h4>{c['fullname']}</h4>
  <div class="small">In: <b>{c['clock_in']}</b></div>
  <div class="small">Out: <b>{c['clock_out']}</b></div>
  <div class="small">Hours: <b>{c['hours_worked']:.2f}</b></div>
</div>
""", unsafe_allow_html=True)
else:
    st.caption("Choose **Today** to see card grid with punch details.")
