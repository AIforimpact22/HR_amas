import streamlit as st
import datetime, math
import pandas as pd
from sqlalchemy import create_engine, text

# ─── DB ENGINE (cached) ──────────────────────────────────────────
if "pg_engine" not in st.session_state:
    st.session_state.pg_engine = create_engine(
        st.secrets["neon"]["dsn"], pool_pre_ping=True, echo=False
    )
engine = st.session_state.pg_engine

# ─── SQL SNIPPETS ────────────────────────────────────────────────
SQL_SHIFT_HRS = """
CASE
  WHEN h.clock_out >= h.clock_in
    THEN (EXTRACT(EPOCH FROM h.clock_out) - EXTRACT(EPOCH FROM h.clock_in)) / 3600
  ELSE (EXTRACT(EPOCH FROM h.clock_out) + 86400 - EXTRACT(EPOCH FROM h.clock_in)) / 3600
END
"""

SQL_DAY = text(f"""
SELECT e.fullname,
       a.clock_in, a.clock_out,
       h.clock_in AS expected_in,
       {SQL_SHIFT_HRS} AS shift_hours,
       EXTRACT(EPOCH FROM (COALESCE(a.clock_out, NOW()) - a.clock_in)) AS secs
FROM   hr_attendance a
JOIN   hr_employee  e USING (employeeid)
LEFT JOIN hr_attendance_history h
       ON h.employeeid = a.employeeid
      AND h.effective_from <= :d
      AND COALESCE(h.effective_to, :d) >= :d
WHERE a.punch_date = :d
ORDER BY e.fullname
""")

SQL_RANGE = text(f"""
SELECT a.punch_date,
       a.clock_in, a.clock_out,
       h.clock_in AS expected_in,
       {SQL_SHIFT_HRS} AS shift_hours,
       EXTRACT(EPOCH FROM (COALESCE(a.clock_out, NOW()) - a.clock_in)) AS secs
FROM   hr_attendance a
LEFT JOIN hr_attendance_history h
       ON h.employeeid = a.employeeid
      AND h.effective_from <= a.punch_date
      AND COALESCE(h.effective_to, a.punch_date) >= a.punch_date
WHERE a.employeeid = :eid
  AND a.punch_date BETWEEN :s AND :e
ORDER BY a.punch_date
""")

# For Tab 3: all employees' schedules
SQL_SCHEDULE_ALL = text("""
SELECT h.att_id,
       e.employeeid,
       e.fullname,
       h.work_days_per_week AS wd_per_wk,
       h.off_day,
       h.clock_in,
       h.clock_out,
       h.effective_from,
       h.effective_to,
       h.reason
FROM   hr_attendance_history h
JOIN   hr_employee           e USING (employeeid)
ORDER  BY e.fullname, h.effective_from
""")

# ─── DB HELPERS ─────────────────────────────────────────────────
def fetch_day(day: datetime.date) -> pd.DataFrame:
    df = pd.read_sql(SQL_DAY, engine, params={"d": day})
    if df.empty:
        return df
    df["clock_in_str"]  = pd.to_datetime(df.clock_in).dt.strftime("%H:%M")
    df["clock_out_str"] = pd.to_datetime(df.clock_out).dt.strftime("%H:%M")
    df["hours"]   = df.secs / 3600
    df["net_str"] = df.secs.apply(lambda s: f"{int(s//3600):02d} h {int((s%3600)//60):02d} m")
    df["late"]    = df.apply(
        lambda r: False if r.expected_in is None else
        r.clock_in.time() >
        (datetime.datetime.combine(datetime.date.today(), r.expected_in)
         + datetime.timedelta(minutes=5)).time(),
        axis=1
    )
    return df

def fetch_range(eid:int, s:datetime.date, e:datetime.date) -> pd.DataFrame:
    df = pd.read_sql(SQL_RANGE, engine, params={"eid":eid,"s":s,"e":e})
    if df.empty:
        return df
    df["clock_in_str"]  = pd.to_datetime(df.clock_in).dt.strftime("%H:%M")
    df["clock_out_str"] = pd.to_datetime(df.clock_out).dt.strftime("%H:%M")
    df["hours"] = df.secs / 3600
    df["late"]  = df.apply(
        lambda r: False if r.expected_in is None else
        pd.to_datetime(r.clock_in).time() >
        (datetime.datetime.combine(datetime.date.today(), r.expected_in)
         + datetime.timedelta(minutes=5)).time(),
        axis=1
    )
    return df

def list_employees() -> pd.DataFrame:
    return pd.read_sql("SELECT employeeid, fullname FROM hr_employee ORDER BY fullname", engine)

def fetch_all_schedules() -> pd.DataFrame:
    df = pd.read_sql(SQL_SCHEDULE_ALL, engine)
    return df

def update_schedule_row(att_id:int, cols:dict):
    sets = ", ".join(f"{k}=:{k}" for k in cols)
    cols["att_id"] = att_id
    sql = text(f"UPDATE hr_attendance_history SET {sets} WHERE att_id=:att_id")
    with engine.begin() as con:
        con.execute(sql, cols)

def close_current_and_add(eid:int, payload:dict):
    close_to = payload["effective_from"] - datetime.timedelta(days=1)
    with engine.begin() as con:
        con.execute(text("""
            UPDATE hr_attendance_history
               SET effective_to = :to
             WHERE employeeid = :eid AND effective_to IS NULL
        """), {"eid":eid,"to":close_to})
        con.execute(text("""
            INSERT INTO hr_attendance_history
                  (employeeid, work_days_per_week, off_day,
                   clock_in, clock_out, effective_from, reason)
            VALUES (:eid,:wd,:off,:cin,:cout,:eff,:rsn)
        """), {
            "eid":eid, "wd":payload["wd"], "off":payload["off"],
            "cin":payload["cin"], "cout":payload["cout"],
            "eff":payload["eff"], "rsn":payload["rsn"]
        })

# ─── UTILITIES ─────────────────────────────────────────────────
def fmt_time(t):
    """Format a time or null as HH:MM or —."""
    if pd.isna(t):
        return "—"
    if isinstance(t, datetime.time):
        return t.strftime("%H:%M")
    return pd.to_datetime(t).strftime("%H:%M")

def fmt_date(d):
    """Format a date/timestamp or null as YYYY‑MM‑DD or —."""
    if pd.isna(d):
        return "—"
    # handle Timestamp, datetime.date, or string
    if hasattr(d, "date"):
        return d.date().isoformat()
    return str(d)

dow = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"]

# ─── UI CONFIG ──────────────────────────────────────────────────
st.set_page_config("Attendance","⏱",layout="wide")
st.title("⏱ Attendance")

tab_grid, tab_log, tab_sched = st.tabs(
    ["🗓 Daily Grid", "📜 Employee Log History", "⚙️ Schedule / Shifts"]
)

# ══════════  TAB 1 — DAILY GRID  ════════════════════════════════
with tab_grid:
    dsel = st.date_input(
        "Select date", datetime.date.today(),
        min_value=datetime.date.today() - datetime.timedelta(days=365),
        max_value=datetime.date.today()
    )
    day_df = fetch_day(dsel)
    if day_df.empty:
        st.info("No punches recorded.")
    else:
        st.markdown("""<style>
.att-card{border:1px solid #DDD;border-radius:8px;padding:14px 16px;height:170px;
display:flex;flex-direction:column;justify-content:space-between;margin-bottom:18px}
.att-card h4{font-size:0.95rem;margin:0 0 6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.small{font-size:0.78rem;margin:1px 0}.in{font-weight:600}.out{color:#e0a800;font-weight:600}
</style>""", unsafe_allow_html=True)

        COLS = 5
        total_rows = math.ceil(len(day_df) / COLS)
        it = iter(day_df.to_dict("records"))

        st.subheader(f"{dsel:%A, %B %d %Y}")
        for _ in range(total_rows):
            cols = st.columns(COLS, gap="small")
            for c in cols:
                try:
                    r = next(it)
                except StopIteration:
                    c.empty()
                    continue
                in_c  = "#dc3545" if r["late"] else "#1f77b4"
                net_c = "#1a873b" if r["hours"] >= r["shift_hours"] else "#c0392b"
                c.markdown(f"""
<div class="att-card">
<h4>{r['fullname']}</h4>
<div class="small">IN  <span class="in" style="color:{in_c};">{r['clock_in_str']}</span></div>
<div class="small">OUT <span class="out">{r['clock_out_str']}</span></div>
<div class="small">NET <span style="color:{net_c};font-weight:600;">{r['net_str']}</span></div>
</div>""", unsafe_allow_html=True)

# ══════════  TAB 2 — LOG HISTORY  ════════════════════════════════
with tab_log:
    emp_df = list_employees()
    emp = st.selectbox("Employee", emp_df.fullname, key="log_emp")
    eid = int(emp_df.loc[emp_df.fullname == emp, "employeeid"].iloc[0])

    today = datetime.date.today()
    start_default = today.replace(day=1)
    s, e = st.date_input("Range", (start_default, today), key="log_range")
    if s > e:
        st.error("Start must be ≤ End")
        st.stop()

    d = fetch_range(eid, s, e)
    st.subheader(f"{emp} • {s} → {e}")
    if d.empty:
        st.info("Nothing.")
        st.stop()

    d["Req IN"]  = d.expected_in.apply(fmt_time)
    d["Req OUT"] = d.apply(
        lambda r: "—" if pd.isna(r.expected_in)
        else (datetime.datetime.combine(r.punch_date, r.expected_in) +
              datetime.timedelta(hours=r.shift_hours)).strftime("%H:%M"),
        axis=1
    )
    d["Δ"] = d.apply(
        lambda r: f"{'+' if (m:=int(round((r.hours-r.shift_hours)*60)))>=0 else '−'}"
                  f"{abs(m)//60:02d}:{abs(m)%60:02d}",
        axis=1
    )

    st.metric("Total",    f"{d.hours.sum():.2f}")
    st.metric("Required", f"{d.shift_hours.sum():.2f}")
    st.metric("Δ",        f"{(d.hours.sum()-d.shift_hours.sum()):+.2f}")

    def sty(row):
        style = [""] * len(row)
        if row["Req IN"] != "—":
            exp = datetime.datetime.strptime(row["Req IN"], "%H:%M").time()
            act = datetime.datetime.strptime(row["IN"], "%H:%M").time()
            cut = (datetime.datetime.combine(today, exp) +
                   datetime.timedelta(minutes=5)).time()
            style[1] = "background-color:#f8d7da;" if act > cut else "background-color:#d1ecf1;"
        style[-1] = "background-color:#d4edda;" if row["Δ"].startswith("+") else "background-color:#f8d7da;"
        return style

    show = d[["punch_date","clock_in_str","clock_out_str","Req IN","Req OUT","Δ"]].rename(
        columns={"punch_date":"Date","clock_in_str":"IN","clock_out_str":"OUT"}
    )
    st.dataframe(show.style.apply(sty,axis=1),use_container_width=True,hide_index=True)

# ══════════  TAB 3 — SCHEDULE / SHIFTS (new design) ═══════════════
with tab_sched:
    sch = fetch_all_schedules()
    if sch.empty:
        st.info("No schedule rows in the system yet.")
        st.stop()

    # build display table
    view = pd.DataFrame({
        "Employee":        sch.fullname,
        "Work days/wk":    sch.wd_per_wk,
        "Off‑day":         sch.off_day.map(lambda i: dow[i] if 0 <= i < 7 else "—"),
        "Clock‑in":        sch.clock_in.apply(fmt_time),
        "Clock‑out":       sch.clock_out.apply(fmt_time),
        "Effective from":  sch.effective_from.apply(fmt_date),
        "Effective to":    sch.effective_to.apply(fmt_date),
        "Reason":          sch.reason.fillna(""),
        "att_id":          sch.att_id
    })

    st.subheader("All employee schedules")
    # header row
    cols = st.columns(len(view.columns) - 1 + 1)  # minus att_id, plus Edit col
    hdrs = ["Employee","Work days/wk","Off‑day","Clock‑in","Clock‑out",
            "Effective from","Effective to","Reason",""]
    for c, h in zip(cols, hdrs):
        c.markdown(f"**{h}**")

    # data rows with Edit button
    for _, row in view.iterrows():
        cols = st.columns(len(view.columns) - 1 + 1)
        for i, field in enumerate(view.columns[:-1]):
            cols[i].markdown(str(row[field]))
        if cols[-1].button("✏️ Edit", key=f"edit_{row.att_id}"):
            st.session_state["edit_row"] = int(row.att_id)

    # modal for editing
    if "edit_row" in st.session_state:
        rid = st.session_state["edit_row"]
        rec = sch.loc[sch.att_id == rid].iloc[0]

        with st.modal(f"Edit schedule • {rec.fullname}"):
            wd   = st.number_input("Work days / week", 1, 7, int(rec.wd_per_wk), key="modal_wd")
            off  = st.selectbox("Off‑day", dow, index=rec.off_day if 0 <= rec.off_day < 7 else 0, key="modal_off")
            cin0 = rec.clock_in if not pd.isna(rec.clock_in) else datetime.time(8,0)
            cout0= rec.clock_out if not pd.isna(rec.clock_out) else datetime.time(17,0)
            cin  = st.time_input("Clock‑in",  cin0,  key="modal_cin")
            cout = st.time_input("Clock‑out", cout0, key="modal_cout")
            efff0= rec.effective_from if not pd.isna(rec.effective_from) else datetime.date.today()
            efff = st.date_input("Effective from", efff0, key="modal_efff")
            efft0= rec.effective_to if not pd.isna(rec.effective_to) else datetime.date(2100,1,1)
            efft = st.date_input("Effective to (blank = open)", efft0, key="modal_efft")
            efft = None if efft == datetime.date(2100,1,1) else efft
            rsn  = st.text_area("Reason", rec.reason or "", key="modal_rsn")

            sv, cc = st.columns(2)
            if sv.button("💾 Save", type="primary"):
                update_schedule_row(rid, {
                    "work_days_per_week": int(wd),
                    "off_day":            dow.index(off),
                    "clock_in":           cin,
                    "clock_out":          cout,
                    "effective_from":     efff,
                    "effective_to":       efft,
                    "reason":             rsn
                })
                st.session_state.pop("edit_row")
                st.experimental_rerun()
            if cc.button("❌ Cancel", type="secondary"):
                st.session_state.pop("edit_row")
                st.experimental_rerun()
