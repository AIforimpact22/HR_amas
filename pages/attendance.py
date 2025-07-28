import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
import datetime, math, os

# ─── DB engine (cached) ──────────────────────────────────────────
if "pg_engine" not in st.session_state:
    st.session_state.pg_engine = create_engine(
        st.secrets["neon"]["dsn"], pool_pre_ping=True, echo=False
    )
engine = st.session_state.pg_engine

SHIFT_HOURS = 8.5  # per‑day shift

# ─── Data helper ────────────────────────────────────────────────
def fetch_day(d: datetime.date) -> pd.DataFrame:
    sql = text("""
        SELECT e.fullname,
               a.clock_in,
               a.clock_out,
               EXTRACT(EPOCH FROM (COALESCE(a.clock_out, NOW()) - a.clock_in))/3600
                 AS hrs
        FROM hr_attendance a
        JOIN hr_employee  e USING (employeeid)
        WHERE a.punch_date = :d
        ORDER BY e.fullname
    """)
    df = pd.read_sql(sql, engine, params={"d": d})
    if df.empty:
        return df
    df["clock_in"]  = pd.to_datetime(df["clock_in"]).dt.strftime("%H:%M")
    df["clock_out"] = pd.to_datetime(df["clock_out"]).dt.strftime("%H:%M")
    df["net"]       = df["hrs"] - SHIFT_HOURS
    return df

# ─── UI ─────────────────────────────────────────────────────────
st.set_page_config("Attendance","⏱",layout="wide")
st.title("⏱ Daily Attendance Grid")

sel_date = st.date_input(
    "Select date", datetime.date.today(),
    min_value=datetime.date.today()-datetime.timedelta(days=365),
    max_value=datetime.date.today()
)

df = fetch_day(sel_date)
if df.empty:
    st.info("No punches recorded for this day.")
    st.stop()

# --- styling ---
st.markdown("""
<style>
.att-card{
  border:1px solid #DDD;border-radius:8px;
  padding:14px 14px;height:150px;        /* taller card */
  display:flex;flex-direction:column;justify-content:space-between;
}
.att-card h4  {font-size:0.94rem;margin:0 0 6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.small {font-size:0.78rem;color:#555;margin:2px 0;}
.in   {color:#1a873b;font-weight:600;}
.out  {color:#c0392b;font-weight:600;}
.net  {color:#226e9d;font-weight:600;}
</style>
""", unsafe_allow_html=True)

COLS = 5
ROWS = math.ceil(len(df)/COLS)
records = df.to_dict("records")
it = iter(records)

st.subheader(f"{sel_date:%A, %B %d %Y}")
for _ in range(ROWS):
    cols = st.columns(COLS, gap="small")
    for col in cols:
        try:
            rec = next(it)
        except StopIteration:
            col.empty(); continue
        net_sign = "+" if rec["net"] >= 0 else "–"
        col.markdown(f"""
<div class="att-card">
  <h4>{rec['fullname']}</h4>
  <div class="small">IN  <span class="in">{rec['clock_in']}</span></div>
  <div class="small">OUT <span class="out">{rec['clock_out']}</span></div>
  <div class="small">NET <span class="net">{net_sign}{abs(rec['net']):.2f} h</span></div>
</div>
""", unsafe_allow_html=True)
