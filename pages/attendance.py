import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
import datetime, math

# ── DB engine (cached) ──────────────────────────────────────────
if "pg_engine" not in st.session_state:
    st.session_state.pg_engine = create_engine(
        st.secrets["neon"]["dsn"], pool_pre_ping=True, echo=False
    )
engine = st.session_state.pg_engine

SHIFT_HOURS = 8.5  # expected per day

# ── Data fetch helper ──────────────────────────────────────────
def fetch_day(day: datetime.date) -> pd.DataFrame:
    df = pd.read_sql(
        text("""
            SELECT e.fullname,
                   a.clock_in,
                   a.clock_out,
                   EXTRACT(EPOCH FROM (COALESCE(a.clock_out,NOW())-a.clock_in)) AS secs
            FROM hr_attendance a
            JOIN hr_employee  e USING (employeeid)
            WHERE a.punch_date = :d
            ORDER BY e.fullname
        """),
        engine,
        params={"d": day},
    )
    if df.empty:
        return df
    df["clock_in"]  = pd.to_datetime(df["clock_in"]).dt.strftime("%H:%M")
    df["clock_out"] = pd.to_datetime(df["clock_out"]).dt.strftime("%H:%M")
    df["hours"]     = df["secs"] / 3600
    df["net_str"]   = df["secs"].apply(lambda s: f"{int(s//3600):02d} h {int((s%3600)//60):02d} m")
    return df

# ── UI ─────────────────────────────────────────────────────────
st.set_page_config("Attendance","⏱",layout="wide")
st.title("⏱ Daily Attendance Grid")

chosen_date = st.date_input(
    "Select date", datetime.date.today(),
    min_value=datetime.date.today()-datetime.timedelta(days=365),
    max_value=datetime.date.today()
)

df = fetch_day(chosen_date)
if df.empty:
    st.info("No punches recorded for this date.")
    st.stop()

# ── CSS styling ───────────────────────────────────────────────
st.markdown("""
<style>
.att-card{
  border:1px solid #DDD;border-radius:8px;
  padding:14px 16px;height:170px;          /* card height */
  display:flex;flex-direction:column;justify-content:space-between;
  margin-bottom:18px;                      /* extra gap between rows */
}
.att-card h4 {font-size:0.95rem;margin:0 0 6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.small      {font-size:0.78rem;margin:1px 0;}  /* tighter line spacing */
.in  {color:#1f77b4;font-weight:600;}     /* blue */
.out {color:#e0a800;font-weight:600;}     /* yellow */
</style>
""", unsafe_allow_html=True)

# ── Render 5×6 grid ───────────────────────────────────────────
COLS = 5
rows = math.ceil(len(df)/COLS)
records = df.to_dict("records")
it = iter(records)

st.subheader(f"{chosen_date:%A, %B %d %Y}")
for _ in range(rows):
    cols = st.columns(COLS, gap="small")
    for col in cols:
        try:
            rec = next(it)
        except StopIteration:
            col.empty(); continue
        net_color = "#1a873b" if rec["hours"] >= SHIFT_HOURS else "#c0392b"
        col.markdown(f"""
<div class="att-card">
  <h4>{rec['fullname']}</h4>
  <div class="small">IN  <span class="in">{rec['clock_in']}</span></div>
  <div class="small">OUT <span class="out">{rec['clock_out']}</span></div>
  <div class="small">NET <span style="color:{net_color};font-weight:600;">{rec['net_str']}</span></div>
</div>
""", unsafe_allow_html=True)
