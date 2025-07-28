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
    if df.empty: return df
    df["clock_in"]  = pd.to_datetime(df["clock_in"]).dt.strftime("%H:%M")
    df["clock_out"] = pd.to_datetime(df["clock_out"]).dt.strftime("%H:%M")
    df["hours"]     = df["secs"] / 3600.0
    df["net_str"]   = df["secs"].apply(lambda s: f"{int(s//3600):02d} h {int((s%3600)//60):02d} m")
    return df

def fetch_range(emp_id: int, start: datetime.date, end: datetime.date) -> pd.DataFrame:
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
        """),
        engine,
        params={"eid": emp_id, "s": start, "e": end}
    )
    if df.empty: return df
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
        st.markdown("""
<style>
.att-card{border:1px solid #DDD;border-radius:8px;padding:14px 16px;height:170px;
          display:flex;flex-direction:column;justify-content:space-between;margin-bottom:18px;}
.att-card h4{font-size:0.95rem;margin:0 0 6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.small{font-size:0.78rem;margin:1px 0;}
.in{color:#1f77b4;font-weight:600;}
.out{color:#e0a800;font-weight:600;}
</style>
""", unsafe_allow_html=True)
        COLS = 5
        rows = math.ceil(len(df)/COLS)
        recs = df.to_dict("records"); it = iter(recs)
        st.subheader(f"{chosen_date:%A, %B %d %Y}")
        for _ in range(rows):
            cols = st.columns(COLS, gap="small")
            for col in cols:
                try: r = next(it)
                except StopIteration: col.empty(); continue
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
# TAB 2 • Log History   ← only this block changed
# ──────────────────────────────────────────────────────────────────
with tab_history:
    emp_df = list_employees()
    if emp_df.empty:
        st.warning("No employees found."); st.stop()

    emp_choice = st.selectbox("Select employee", emp_df["fullname"], key="hist_emp")
    emp_row = emp_df[emp_df["fullname"] == emp_choice].iloc[0]
    emp_id = int(emp_row["employeeid"])          # numpy.int64 → int

    today = datetime.date.today()
    default_start = today.replace(day=1)
    rng = st.date_input("Date range", (default_start, today), key="hist_rng")
    start_date, end_date = rng if isinstance(rng, tuple) else (rng[0], rng[1])

    if start_date > end_date:
        st.error("Start date must be before end date.")
        st.stop()

    data = fetch_range(emp_id, start_date, end_date)
    st.subheader(f"{emp_choice} • {start_date:%Y-%m-%d} → {end_date:%Y-%m-%d}")

    if data.empty:
        st.info("No attendance records for this interval.")
        st.stop()

    # ── summary metrics ──
    total   = data["hours"].sum()
    expected= len(data) * SHIFT_HOURS
    delta   = total - expected
    col1, col2, col3 = st.columns(3)
    col1.metric("Total hours", f"{total:.2f}")
    col2.metric("Expected", f"{expected:.1f}")
    col3.metric("Δ (overtime)", f"{delta:+.2f}", delta if delta else None)

    # ── build styled table ──
    tbl = data[["punch_date","clock_in","clock_out","net_str","hours"]].rename(
        columns={"punch_date":"Date","clock_in":"IN","clock_out":"OUT","net_str":"NET","hours":"Hours"}
    )
    tbl["Hours"] = tbl["Hours"].round(2)

    def style_row(row):
        style = [""] * len(row)
        # late if after 08:05
        late_threshold = datetime.time(8, 5)
        in_time = datetime.datetime.strptime(row["IN"], "%H:%M").time()
        if in_time > late_threshold:
            style[1] = "background-color:#f8d7da;"      # IN col red
        else:
            style[1] = "background-color:#d1ecf1;"      # IN col blue

        if row["Hours"] < SHIFT_HOURS:
            style[4] = "background-color:#f8d7da;"      # Hours col red
        else:
            style[4] = "background-color:#d4edda;"      # Hours col green
        return style

    styled = tbl.style.apply(style_row, axis=1)

    st.dataframe(styled, use_container_width=True, hide_index=True)
":"NET","hours":"Hours"}
            )
            tbl["Hours"]=tbl["Hours"].map("{:.2f}".format)
            st.dataframe(tbl, use_container_width=True, hide_index=True)
