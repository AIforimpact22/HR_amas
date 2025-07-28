import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
import datetime, math, os

# ─── DB engine (cached) ───────────────────────────────────────────
if "pg_engine" not in st.session_state:
    st.session_state.pg_engine = create_engine(
        st.secrets["neon"]["dsn"], pool_pre_ping=True, echo=False
    )
engine = st.session_state.pg_engine

SHIFT_HOURS = 8.5  # standard shift length

# ─── Data fetch helper ───────────────────────────────────────────
def fetch_day(punch_date: datetime.date) -> pd.DataFrame:
    sql = text("""
        SELECT e.fullname,
               a.clock_in,
               a.clock_out,
               EXTRACT(EPOCH FROM (COALESCE(a.clock_out, NOW()) - a.clock_in)) AS seconds_worked
        FROM hr_attendance a
        JOIN hr_employee  e USING (employeeid)
        WHERE a.punch_date = :d
        ORDER BY e.fullname
    """)
    df = pd.read_sql(sql, engine, params={"d": punch_date})
    if df.empty:
        return df
    df["clock_in"]  = pd.to_datetime(df["clock_in"]).dt.strftime("%H:%M")
    df["clock_out"] = pd.to_datetime(df["clock_out"]).dt.strftime("%H:%M")
    df["hours_float"] = df["seconds_worked"] / 3600
    # format HH:MM
    df["net_str"] = df["seconds_worked"].apply(lambda s: f"{int(s//3600):02d} h {int((s%3600)//60):02d} m")
    return df

# ─── UI setup ────────────────────────────────────────────────────
st.set_page_config("Attendance","⏱",layout="wide")
st.title("⏱ Daily Attendance Grid")

sel_date = st.date_input(
    "Select date", datetime.date.today(),
    min_value=datetime.date.today() - datetime.timedelta(days=365),
    max_value=datetime.date.today()
)

df = fetch_day(sel_date)
if df.empty:
    st.info("No punches recorded for this date.")
    st.stop()

# ─── CSS styling ────────────────────────────────────────────────
st.markdown("""
<style>
.att-card{
  border:1px solid #DDD;border-radius:8px;
  padding:18px 16px;height:170px;           /* more vertical space */
  display:flex;flex-direction:column;justify-content:space-between;
}
.att-card h4  {font-size:0.95rem;margin:0 0 8px 0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.small {font-size:0.8rem;margin:2px 0;}
.in   {color:#1f77b4;font-weight:600;}     /* blue */
.out  {color:#e0a800;font-weight:600;}     /* yellow */
</style>
""", unsafe_allow_html=True)

# ─── Render 5×6 grid ────────────────────────────────────────────
COLS = 5
ROWS = math.ceil(len(df) / COLS)
records = df.to_dict("records")
rec_iter = iter(records)

st.subheader(f"{sel_date:%A, %B %d %Y}")
for _ in range(ROWS):
    cols = st.columns(COLS, gap="small")
    for col in cols:
        try:
            r = next(rec_iter)
        except StopIteration:
            col.empty(); continue
        # choose net colour
        net_color = "#1a873b" if r["hours_float"] >= SHIFT_HOURS else "#c0392b"
        col.markdown(f"""
<div class="att-card">
  <h4>{r['fullname']}</h4>
  <div class="small">IN  <span class="in">{r['clock_in']}</span></div>
  <div class="small">OUT <span class="out">{r['clock_out']}</span></div>
  <div class="small">NET <span class="net" style="color:{net_color};font-weight:600;">{r['net_str']}</span></div>
</div>
""", unsafe_allow_html=True)
