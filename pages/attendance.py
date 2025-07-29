import streamlit as st, datetime, math
import pandas as pd
from sqlalchemy import create_engine, text

# ─── DB engine (cached) ──────────────────────────────────────────
if "pg_engine" not in st.session_state:
    st.session_state.pg_engine = create_engine(
        st.secrets["neon"]["dsn"], pool_pre_ping=True, echo=False
    )
engine = st.session_state.pg_engine

# ─── Helper SQL snippets -------------------------------------------------------
SQL_DAY = text("""
SELECT e.fullname,
       a.clock_in,
       a.clock_out,
       h.clock_in           AS expected_in,
       CASE WHEN h.clock_out < h.clock_in
            THEN EXTRACT(EPOCH FROM (h.clock_out + INTERVAL '1 day' - h.clock_in))
            ELSE EXTRACT(EPOCH FROM (h.clock_out - h.clock_in))
       END / 3600           AS shift_hours,
       EXTRACT(EPOCH FROM (COALESCE(a.clock_out, NOW()) - a.clock_in)) AS secs
FROM   hr_attendance a
JOIN   hr_employee  e USING (employeeid)
LEFT JOIN hr_attendance_history h
       ON h.employeeid = a.employeeid
      AND h.effective_from <= :d
      AND COALESCE(h.effective_to, :d) >= :d
WHERE  a.punch_date = :d
ORDER  BY e.fullname
""")

SQL_RANGE = text("""
SELECT a.punch_date,
       a.clock_in,
       a.clock_out,
       h.clock_in AS expected_in,
       CASE WHEN h.clock_out < h.clock_in
            THEN EXTRACT(EPOCH FROM (h.clock_out + INTERVAL '1 day' - h.clock_in))
            ELSE EXTRACT(EPOCH FROM (h.clock_out - h.clock_in))
       END / 3600           AS shift_hours,
       EXTRACT(EPOCH FROM (COALESCE(a.clock_out, NOW()) - a.clock_in)) AS secs
FROM   hr_attendance a
LEFT JOIN hr_attendance_history h
       ON h.employeeid = a.employeeid
      AND h.effective_from <= a.punch_date
      AND COALESCE(h.effective_to, a.punch_date) >= a.punch_date
WHERE  a.employeeid = :eid
  AND  a.punch_date BETWEEN :s AND :e
ORDER  BY a.punch_date
""")

# ─── Fetch helpers -------------------------------------------------------------
def fetch_day(day: datetime.date) -> pd.DataFrame:
    df = pd.read_sql(SQL_DAY, engine, params={"d": day})
    if df.empty:
        return df
    df["clock_in_str"]  = pd.to_datetime(df["clock_in"]).dt.strftime("%H:%M")
    df["clock_out_str"] = pd.to_datetime(df["clock_out"]).dt.strftime("%H:%M")
    df["hours"]         = df["secs"] / 3600.0
    df["net_str"]       = df["secs"].apply(
        lambda s: f"{int(s//3600):02d} h {int((s%3600)//60):02d} m"
    )
    # late flag: IN > expected_in + 5 min
    def _late(row):
        if row.expected_in is None:
            return False
        act = row.clock_in.time()
        exp = row.expected_in
        return act > (datetime.datetime.combine(datetime.date.today(), exp) +
                      datetime.timedelta(minutes=5)).time()
    df["late"] = df.apply(_late, axis=1)
    return df

def fetch_range(emp_id: int, start: datetime.date, end: datetime.date) -> pd.DataFrame:
    df = pd.read_sql(SQL_RANGE, engine, params={"eid": emp_id, "s": start, "e": end})
    if df.empty:
        return df
    df["clock_in_str"]  = pd.to_datetime(df["clock_in"]).dt.strftime("%H:%M")
    df["clock_out_str"] = pd.to_datetime(df["clock_out"]).dt.strftime("%H:%M")
    df["hours"]         = df["secs"] / 3600.0
    df["net_str"]       = df["secs"].apply(
        lambda s: f"{int(s//3600):02d}:{int((s%3600)//60):02d}"
    )
    df["late"] = df.apply(
        lambda r: (pd.to_datetime(r["clock_in"]).time() >
                   (datetime.datetime.combine(datetime.date.today(), r["expected_in"])
                    + datetime.timedelta(minutes=5)).time()) if r["expected_in"] else False,
        axis=1,
    )
    return df

def list_employees():
    return pd.read_sql(
        text("SELECT employeeid, fullname FROM hr_employee ORDER BY fullname"), engine
    )

# ─── UI setup ------------------------------------------------------------------
st.set_page_config("Attendance", "⏱", layout="wide")
st.title("⏱ Attendance")

tab_grid, tab_history = st.tabs(["🗓 Daily Grid", "📜 Employee Log History"])

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 • Daily grid
# ═══════════════════════════════════════════════════════════════════════════════
with tab_grid:
    chosen_date = st.date_input(
        "Select date",
        datetime.date.today(),
        min_value=datetime.date.today() - datetime.timedelta(days=365),
        max_value=datetime.date.today(),
        key="grid_date",
    )
    df = fetch_day(chosen_date)
    if df.empty:
        st.info("No punches recorded for this date.")
    else:
        st.markdown(
            """
<style>
.att-card{border:1px solid #DDD;border-radius:8px;padding:14px 16px;height:170px;
          display:flex;flex-direction:column;justify-content:space-between;margin-bottom:18px;}
.att-card h4{font-size:0.95rem;margin:0 0 6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.small{font-size:0.78rem;margin:1px 0;}
.in{font-weight:600;}
.out{color:#e0a800;font-weight:600;}
</style>
""",
            unsafe_allow_html=True,
        )
        COLS = 5
        rows = math.ceil(len(df) / COLS)
        recs = df.to_dict("records")
        it = iter(recs)
        st.subheader(f"{chosen_date:%A, %B %d %Y}")

        for _ in range(rows):
            cols = st.columns(COLS, gap="small")
            for col in cols:
                try:
                    r = next(it)
                except StopIteration:
                    col.empty()
                    continue

                # colour logic
                net_color = "#1a873b" if r["hours"] >= r["shift_hours"] else "#c0392b"
                in_col = "#dc3545" if r["late"] else "#1f77b4"

                col.markdown(
                    f"""
<div class="att-card">
  <h4>{r['fullname']}</h4>
  <div class="small">IN  <span class="in" style="color:{in_col};">{r['clock_in_str']}</span></div>
  <div class="small">OUT <span class="out">{r['clock_out_str']}</span></div>
  <div class="small">NET <span style="color:{net_color};font-weight:600;">{r['net_str']}</span></div>
</div>
""",
                    unsafe_allow_html=True,
                )

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 • Log History
# ═══════════════════════════════════════════════════════════════════════════════
with tab_history:
    emp_df = list_employees()
    if emp_df.empty:
        st.warning("No employees found.")
        st.stop()

    emp_choice = st.selectbox("Select employee", emp_df["fullname"], key="hist_emp")
    emp_row = emp_df[emp_df["fullname"] == emp_choice].iloc[0]
    emp_id   = int(emp_row["employeeid"])  # cast fixes numpy.int64

    today = datetime.date.today()
    default_start = today.replace(day=1)
    date_range = st.date_input("Date range", (default_start, today), key="hist_rng")
    start_date, end_date = (
        date_range if isinstance(date_range, tuple) else (date_range[0], date_range[1])
    )

    if start_date > end_date:
        st.error("Start date must be before end date.")
        st.stop()

    data = fetch_range(emp_id, start_date, end_date)
    st.subheader(f"{emp_choice} • {start_date:%Y-%m-%d} → {end_date:%Y-%m-%d}")

    if data.empty:
        st.info("No attendance records for this interval.")
        st.stop()

    # ─── Summary metrics ─────────────────────────────────────────────
    total_hours    = data["hours"].sum()
    expected_hours = data["shift_hours"].sum()
    delta_hours    = total_hours - expected_hours

    m1, m2, m3 = st.columns(3)
    m1.metric("Total hours",   f"{total_hours:.2f}")
    m2.metric("Expected",      f"{expected_hours:.2f}")
    m3.metric("Δ",             f"{delta_hours:+.2f}", delta_hours if delta_hours else None)

    # ─── Build daily table ───────────────────────────────────────────
    # required IN / OUT strings
    data["Req IN"] = data["expected_in"].apply(
        lambda t: t.strftime("%H:%M") if pd.notna(t) else "—"
    )

    def _req_out(row):
        if pd.isna(row.expected_in):
            return "—"
        # build a dt on punch_date then add shift_hours
        base_dt = datetime.datetime.combine(row.punch_date, row.expected_in)
        out_dt  = base_dt + datetime.timedelta(hours=row.shift_hours)
        return out_dt.strftime("%H:%M")

    data["Req OUT"] = data.apply(_req_out, axis=1)

    # Δ as ±HH:MM
    def _delta_str(row):
        delta = int((row.hours - row.shift_hours) * 60)  # minutes
        sign  = "+" if delta >= 0 else "−"
        delta = abs(delta)
        hh, mm = divmod(delta, 60)
        return f"{sign}{hh:02d}:{mm:02d}"

    data["Δ"] = data.apply(_delta_str, axis=1)

    tbl = data[
        ["punch_date", "clock_in_str", "clock_out_str", "Req IN", "Req OUT", "Δ"]
    ].rename(
        columns={
            "punch_date": "Date",
            "clock_in_str": "IN",
            "clock_out_str": "OUT",
        }
    )

    # ─── Styling ────────────────────────────────────────────────────
    def colour_row(row):
        style = [""] * len(row)

        # late highlight on IN ( > Req IN + 5 min)
        if row["Req IN"] != "—":
            exp_in = datetime.datetime.strptime(row["Req IN"], "%H:%M").time()
            act_in = datetime.datetime.strptime(row["IN"], "%H:%M").time()
            late_cut = (datetime.datetime.combine(datetime.date.today(), exp_in)
                        + datetime.timedelta(minutes=5)).time()
            style[1] = "background-color:#f8d7da;" if act_in > late_cut \
                       else "background-color:#d1ecf1;"

        # Δ colouring
        style[-1] = "background-color:#d4edda;" if row["Δ"].startswith("+") \
                    else "background-color:#f8d7da;"
        return style

    st.dataframe(
        tbl.style.apply(colour_row, axis=1),
        use_container_width=True,
        hide_index=True,
    )
