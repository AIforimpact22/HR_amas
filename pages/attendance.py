import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
import datetime, math, pathlib

# ─── DB engine (cached) ──────────────────────────────────────────────
if "pg_engine" not in st.session_state:
    st.session_state.pg_engine = create_engine(
        st.secrets["neon"]["dsn"], pool_pre_ping=True, echo=False
    )
engine = st.session_state.pg_engine

SHIFT_HOURS = 8.5  # normal per‑day shift

# ─── Fetch attendance helper ────────────────────────────────────────
def fetch_day(punch_date: datetime.date) -> pd.DataFrame:
    sql = text("""
        SELECT  e.fullname,
                a.clock_in,
                a.clock_out,
                EXTRACT(EPOCH FROM (COALESCE(a.clock_out, NOW()) - a.clock_in))/3600
                    AS hours_worked
        FROM hr_attendance a
        JOIN hr_employee   e USING (employeeid)
        WHERE a.punch_date = :d
        ORDER BY e.fullname
    """)
    df = pd.read_sql(sql, engine, params={"d": punch_date})
    if df.empty:
        return df
    df["clock_in"]  = pd.to_datetime(df["clock_in"]).dt.strftime("%H:%M")
    df["clock_out"] = pd.to_datetime(df["clock_out"]).dt.strftime("%H:%M")
    df["net"]       = df["hours_worked"] - SHIFT_HOURS
    return df

# ─── UI ─────────────────────────────────────────────────────────────
st.set_page_config("Attendance","⏱",layout="wide")
st.title("⏱ Daily Attendance Grid")

# date picker (defaults to today)
chosen_date = st.date_input("Pick a date", datetime.date.today(),
                            min_value=datetime.date.today()-datetime.timedelta(days=365),
                            max_value=datetime.date.today())

data = fetch_day(chosen_date)

if data.empty:
    st.info("No punches recorded for this day.")
    st.stop()

# CSS for card styling
st.markdown("""
<style>
.att-grid     {margin-top:12px;}
.att-card     {border:1px solid #DDD;border-radius:8px;padding:10px 12px;height:120px;}
.att-card h4  {font-size:0.92rem;margin:0 0 6px 0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.att-card .in  {color:#1a873b;font-weight:600;font-size:0.8rem;}
.att-card .out {color:#c0392b;font-weight:600;font-size:0.8rem;}
.att-card .net {color:#226e9d;font-weight:600;font-size:0.78rem;}
.att-card .lbl {font-size:0.76rem;color:#555;}
</style>
""", unsafe_allow_html=True)

# build 5×6 grid (30 slots)
COLS = 5
ROWS = math.ceil(len(data) / COLS)
cards = data.to_dict("records")
cards_iter = iter(cards)

st.subheader(f"{chosen_date:%A, %B %d %Y}")
grid = st.container()
for _ in range(ROWS):
    row_cols = grid.columns(COLS, gap="small")
    for col in row_cols:
        try:
            c = next(cards_iter)
        except StopIteration:
            col.empty()
            continue
        net_sign = "+" if c["net"] >= 0 else "–"
        col.markdown(f"""
<div class="att-card">
  <h4>{c['fullname']}</h4>
  <div class="lbl">IN  <span class="in">{c['clock_in']}</span></div>
  <div class="lbl">OUT <span class="out">{c['clock_out']}</span></div>
  <div class="lbl">NET <span class="net">{net_sign}{abs(c['net']):.2f} h</span></div>
</div>
""", unsafe_allow_html=True)
