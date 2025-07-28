import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
import datetime, math

# ─── DB engine (cached) ─────────────────────────────────────────────
if "pg_engine" not in st.session_state:
    st.session_state.pg_engine = create_engine(
        st.secrets["neon"]["dsn"], pool_pre_ping=True, echo=False
    )
engine = st.session_state.pg_engine

SHIFT_HOURS = 8.5  # standard shift length

# ─── Shared helpers ────────────────────────────────────────────────
def fetch_day(day: datetime.date) -> pd.DataFrame:
    """All punches for a given day (all employees)."""
    df = pd.read_sql(
        text("""
            SELECT e.fullname,
                   a.clock_in,
                   a.clock_out,
                   EXTRACT(EPOCH FROM (COALESCE(a.clock_out, NOW()) - a.clock_in)) AS secs
            FROM hr_attendance a
            JOIN hr_employee  e USING (employeeid)
            WHERE a.punch_date = :d
            ORDER BY e.fullname
        """), engine, params={"d": day}
    )
    if df.empty:
        return df
    df["clock_in"]  = pd.to_datetime(df["clock_in"]).dt.strftime("%H:%M")
    df["clock_out"] = pd.to_datetime(df["clock_out"]).dt.strftime("%H:%M")
    df["hours"]     = df["secs"] / 3600.0
    df["net_str"]   = df["secs"].apply(lambda s: f"{int(s//3600):02d} h {int((s%3600)//60):02d} m")
    return df

def fetch_range(emp_id: int, start: datetime.date, end: datetime.date) -> pd.DataFrame:
    """All punches for one employee between dates (inclusive)."""
    df = pd.read_sql(
        text("""
            SELECT a.punch_date,
                   a.clock_in,
                   a.clock_out,
                   EXTRACT(EPOCH FROM (COALESCE(a.clock_out, NOW()) - a.clock_in)) AS secs
            FROM hr_attendance a
            WHERE a.employeeid = :eid
              AND a.punch_date BETWEEN :s AND :e
            ORDER BY a.punch_date
        """), engine, params={"eid": emp_id, "s": start, "e": end}
    )
    if df.empty:
        return df
    df["clock_in"]  = pd.to_datetime(df["clock_in"]).dt.strftime("%H:%M")
    df["clock_out"] = pd.to_datetime(df["clock_out"]).dt.strftime("%H:%M")
    df["hours"]     = df["secs"] / 3600.0
    df["net_str"]   = df["secs"].apply(lambda s: f"{int(s//3600):02d}:{int((s%3600)//60):02d}")
    return df

def list_employees() -> pd.DataFrame:
    return pd.read_sql(text("SELECT employeeid, fullname FROM hr_employee ORDER BY fullname"), engine)

# ─── UI setup ──────────────────────────────────────────────────────
st.set_page_config("Attendance","⏱",layout="wide")
st.title("⏱ Attendance")

tab_grid, tab_history = st.tabs(["🗓 Daily Grid", "📜 Employee Log History"])

# ──────────────────────────────────────────────────────────────────
# TAB 1 • Daily Grid
# ──────────────────────────────────────────────────────────────────
with tab_grid:
    chosen_date = st.date_input(
        "Select date", datetime.date.today(),
        min_value=datetime.date.today()-datetime.timedelta(days=365),
        max_value=datetime.date.today(),
        key="grid_date"
    )

    df = fetch_day(chosen_date)
    if df.empty:
        st.info("No punches recorded for this date.")
    else:
        # CSS
        st.markdown("""
<style>
.att-card{
  border:1px solid #DDD;border-radius:8px;
  padding:14px 16px;height:170px;
  display:flex;flex-direction:column;justify-content:space-between;
  margin-bottom:18px;           /* gap between rows */
}
.att-card h4 {font-size:0.95rem;margin:0 0 6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.small {font-size:0.78rem;margin:1px 0;}
.in  {color:#1f77b4;font-weight:600;}   /* blue */
.out {color:#e0a800;font-weight:600;}   /* yellow */
</style>
""", unsafe_allow_html=True)

        # Render grid
        COLS = 5
        rows = math.ceil(len(df)/COLS)
        items = df.to_dict("records")
        it = iter(items)

        st.subheader(f"{chosen_date:%A, %B %d %Y}")
        for _ in range(rows):
            cols = st.columns(COLS, gap="small")
            for col in cols:
                try:
                    r = next(it)
                except StopIteration:
                    col.empty(); continue
                net_color = "#1a873b" if r["hours"] >= SHIFT_HOURS else "#c0392b"
                col.markdown(f"""
<div class="att-card">
  <h4>{r['fullname']}</h4>
  <div class="small">IN  <span class="in">{r['clock_in']}</span></div>
  <div class="small">OUT <span class="out">{r['clock_out']}</span></div>
  <div class="small">NET <span style="color:{net_color};font-weight:600;">{r['net_str']}</span></div>
</div>
""", unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────────
# TAB 2 • Log History
# ──────────────────────────────────────────────────────────────────
with tab_history:
    emp_df = list_employees()
    if emp_df.empty:
        st.warning("No employees found in the database."); st.stop()

    emp_display = emp_df["fullname"]
    emp_choice = st.selectbox("Select employee", emp_display, key="hist_emp")
    emp_row = emp_df[emp_df["fullname"] == emp_choice].iloc[0]
    emp_id = emp_row["employeeid"]

    # default range: current month
    today = datetime.date.today()
    default_start = today.replace(day=1)
    rng = st.date_input("Date range", (default_start, today), key="hist_range")
    if isinstance(rng, tuple):
        start_date, end_date = rng
    else:  # Streamlit older versions
        start_date, end_date = rng[0], rng[1]

    if start_date > end_date:
        st.error("Start date must be before end date.")
    else:
        data = fetch_range(emp_id, start_date, end_date)
        st.subheader(f"{emp_choice} • {start_date:%Y-%m-%d} → {end_date:%Y-%m-%d}")

        if data.empty:
            st.info("No attendance records for this interval.")
        else:
            total_hours = data["hours"].sum()
            expected_hours = len(data) * SHIFT_HOURS
            delta = total_hours - expected_hours

            colA, colB, colC = st.columns(3)
            colA.metric("Total hours", f"{total_hours:.2f}")
            colB.metric("Expected", f"{expected_hours:.1f}")
            colC.metric("Δ (overtime)", f"{delta:+.2f}", delta if delta != 0 else None)

            # daily log table
            view = data[["punch_date","clock_in","clock_out","net_str","hours"]].rename(
                columns={
                    "punch_date":"Date",
                    "clock_in":"IN",
                    "clock_out":"OUT",
                    "net_str":"NET",
                    "hours":"Hours"
                }
            )
            view["Hours"] = view["Hours"].map("{:.2f}".format)
            st.dataframe(view, use_container_width=True, hide_index=True)
