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
    if df.empty: return df
    df["clock_in_str"]  = pd.to_datetime(df.clock_in).dt.strftime("%H:%M")
    df["clock_out_str"] = pd.to_datetime(df.clock_out).dt.strftime("%H:%M")
    df["hours"]   = df.secs / 3600
    df["net_str"] = df.secs.apply(lambda s:f"{int(s//3600):02d} h {int((s%3600)//60):02d} m")
    df["late"]    = df.apply(
        lambda r: False if r.expected_in is None else
        (pd.notna(r.clock_in) and
         r.clock_in.time() >
         (datetime.datetime.combine(datetime.date.today(), r.expected_in) +
          datetime.timedelta(minutes=5)).time()),
        axis=1)
    return df

def fetch_range(eid:int, s:datetime.date, e:datetime.date) -> pd.DataFrame:
    df = pd.read_sql(SQL_RANGE, engine, params={"eid":eid,"s":s,"e":e})
    if df.empty: return df
    df["clock_in_str"]  = pd.to_datetime(df.clock_in).dt.strftime("%H:%M")
    df["clock_out_str"] = pd.to_datetime(df.clock_out).dt.strftime("%H:%M")
    df["hours"] = df.secs / 3600
    df["late"]  = df.apply(
        lambda r: False if r.expected_in is None else
        (pd.notna(r.clock_in) and
         pd.to_datetime(r.clock_in).time() >
         (datetime.datetime.combine(datetime.date.today(), r.expected_in) +
          datetime.timedelta(minutes=5)).time()),
        axis=1)
    return df

def list_employees() -> pd.DataFrame:
    return pd.read_sql(
        "SELECT employeeid, fullname FROM hr_employee ORDER BY fullname", engine)

def fetch_all_schedules() -> pd.DataFrame:
    return pd.read_sql(SQL_SCHEDULE_ALL, engine)

# close current open row & insert new one  -----------------------
def close_current_and_add(eid:int, payload:dict):
    """Close existing open schedule and insert a new row."""
    close_to = payload["eff"] - datetime.timedelta(days=1)
    with engine.begin() as con:
        con.execute(text("""
            UPDATE hr_attendance_history
               SET effective_to = :to
             WHERE employeeid = :eid AND effective_to IS NULL
        """), {"eid": eid, "to": close_to})
        con.execute(text("""
            INSERT INTO hr_attendance_history
                  (employeeid, work_days_per_week, off_day,
                   clock_in, clock_out, effective_from, reason)
            VALUES (:eid, :wd, :off, :cin, :cout, :eff, :rsn)
        """), {
            "eid": eid,
            "wd":  payload["wd"],
            "off": payload["off"],
            "cin": payload["cin"],
            "cout": payload["cout"],
            "eff": payload["eff"],
            "rsn": payload["rsn"]
        })

# ─── UTILITIES ─────────────────────────────────────────────────
dow = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"]

def fmt_time(t):
    if pd.isna(t): return "—"
    if isinstance(t, datetime.time): return t.strftime("%H:%M")
    return pd.to_datetime(t).strftime("%H:%M")

def fmt_date(d):
    if pd.isna(d): return "—"
    return d.date().isoformat() if hasattr(d,"date") else str(d)

def clean_off_index(val):
    if pd.isna(val): return 0
    try:
        i=int(val);  return i if 0<=i<7 else 0
    except Exception: return 0

def safe_int(val, default=0):
    try: return int(val)
    except Exception: return default

# ─── UI CONFIG ──────────────────────────────────────────────────
st.set_page_config("Attendance", "⏱", layout="wide")
st.title("⏱ Attendance")

tab_grid, tab_log, tab_sched = st.tabs(
    ["🗓 Daily Grid", "📜 Employee Log History", "⚙️ Schedule / Shifts"]
)

# ╔═════════ TAB 1 — DAILY GRID ══════════════════════════════════
with tab_grid:
    dsel = st.date_input(
        "Select date",
        datetime.date.today(),
        min_value=datetime.date.today() - datetime.timedelta(days=365),
        max_value=datetime.date.today()
    )
    day_df = fetch_day(dsel)
    if day_df.empty:
        st.info("No punches recorded.")
    else:
        st.markdown("""
<style>
.att-card{border:1px solid #DDD;border-radius:8px;padding:14px 16px;height:170px;
display:flex;flex-direction:column;justify-content:space-between;margin-bottom:18px}
.att-card h4{font-size:0.95rem;margin:0 0 6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.small{font-size:0.78rem;margin:1px 0}.in{font-weight:600}.out{color:#e0a800;font-weight:600}
</style>""", unsafe_allow_html=True)

        COLS, total_rows = 5, math.ceil(len(day_df)/5)
        it = iter(day_df.to_dict("records"))
        st.subheader(f"{dsel:%A, %B %d %Y}")
        for _ in range(total_rows):
            cols = st.columns(COLS, gap="small")
            for c in cols:
                try:
                    r = next(it)
                except StopIteration:
                    c.empty(); continue
                in_c  = "#dc3545" if r["late"] else "#1f77b4"
                net_c = "#1a873b" if r["hours"] >= r["shift_hours"] else "#c0392b"
                c.markdown(f"""
<div class="att-card">
<h4>{r['fullname']}</h4>
<div class="small">IN  <span class="in" style="color:{in_c};">{r['clock_in_str']}</span></div>
<div class="small">OUT <span class="out">{r['clock_out_str']}</span></div>
<div class="small">NET <span style="color:{net_c};font-weight:600;">{r['net_str']}</span></div>
</div>""", unsafe_allow_html=True)

# ╔═════════ TAB 2 — LOG HISTORY ═════════════════════════════════
with tab_log:
    emp_df = list_employees()
    emp = st.selectbox("Employee", emp_df.fullname, key="log_emp")
    eid = int(emp_df.loc[emp_df.fullname == emp, "employeeid"].iloc[0])

    today = datetime.date.today()
    start_default = today.replace(day=1)
    s, e = st.date_input("Range", (start_default, today), key="log_range")
    if s > e:
        st.error("Start must be ≤ End"); st.stop()

    d = fetch_range(eid, s, e)
    st.subheader(f"{emp} • {s} → {e}")
    if d.empty:
        st.info("Nothing."); st.stop()

    d["Req IN"]  = d.expected_in.apply(fmt_time)
    d["Req OUT"] = d.apply(
        lambda r: "—" if pd.isna(r.expected_in)
        else (datetime.datetime.combine(r.punch_date, r.expected_in) +
              datetime.timedelta(hours=r.shift_hours)).strftime("%H:%M"), axis=1)
    d["Δ"] = d.apply(
        lambda r: f"{'+' if (m:=int(round((r.hours-r.shift_hours)*60)))>=0 else '−'}"
                  f"{abs(m)//60:02d}:{abs(m)%60:02d}", axis=1)

    st.metric("Total",    f"{d.hours.sum():.2f}")
    st.metric("Required", f"{d.shift_hours.sum():.2f}")
    st.metric("Δ",        f"{(d.hours.sum()-d.shift_hours.sum()):+.2f}")

    def sty(row):
        style = [""]*len(row)
        if row["Req IN"] != "—":
            exp = datetime.datetime.strptime(row["Req IN"], "%H:%M").time()
            act = datetime.datetime.strptime(row["IN"], "%H:%M").time()
            cut = (datetime.datetime.combine(today, exp) +
                   datetime.timedelta(minutes=5)).time()
            style[1] = "background-color:#f8d7da;" if act > cut else "background-color:#d1ecf1;"
        style[-1] = "background-color:#d4edda;" if row["Δ"].startswith("+") else "background-color:#f8d7da;"
        return style

    show = d[["punch_date","clock_in_str","clock_out_str","Req IN","Req OUT","Δ"]].rename(
        columns={"punch_date":"Date","clock_in_str":"IN","clock_out_str":"OUT"})
    st.dataframe(show.style.apply(sty, axis=1), use_container_width=True, hide_index=True)

# ╔═════════ TAB 3 — SCHEDULE / SHIFTS ═══════════════════════════
with tab_sched:
    sch = fetch_all_schedules()
    if sch.empty:
        st.info("No schedule rows found."); st.stop()

    view = pd.DataFrame({
        "Employee":        sch.fullname,
        "Work days/wk":    sch.wd_per_wk.fillna("—"),
        "Off‑day":         sch.off_day.apply(lambda v: dow[int(v)] if pd.notna(v) and 0<=int(v)<7 else "—"),
        "Clock‑in":        sch.clock_in.apply(fmt_time),
        "Clock‑out":       sch.clock_out.apply(fmt_time),
        "Effective from":  sch.effective_from.apply(fmt_date),
        "Effective to":    sch.effective_to.apply(fmt_date),
        "Reason":          sch.reason.fillna(""),
        "att_id":          sch.att_id
    })

    st.subheader("All employee schedules")
    hdrs = ["Employee","Work days/wk","Off‑day","Clock‑in","Clock‑out",
            "Effective from","Effective to","Reason",""]
    head = st.columns(len(hdrs))
    for c,h in zip(head,hdrs): c.markdown(f"**{h}**")

    for _,row in view.iterrows():
        cols = st.columns(len(hdrs))
        for i, field in enumerate(view.columns[:-1]):
            cols[i].markdown(str(row[field]))
        if cols[-1].button("✏️", key=f"edit_{row.att_id}"):
            st.session_state["edit_row"] = int(row.att_id)

    # ── inline edit form ────────────────────────────────────────
    if "edit_row" in st.session_state and st.session_state["edit_row"] in set(sch.att_id):
        rid = int(st.session_state["edit_row"])
        rec = sch.loc[sch.att_id == rid].iloc[0]

        st.markdown("---")
        st.subheader(f"Edit schedule • {rec.fullname}")
        with st.form(f"form_{rid}"):
            wd = st.number_input(
                "Work days / week", 1, 7,
                safe_int(rec.wd_per_wk, 6), key=f"wd_{rid}")

            off = st.selectbox(
                "Off‑day", dow,
                index=clean_off_index(rec.off_day), key=f"off_{rid}")

            cin_def  = rec.clock_in  if pd.notna(rec.clock_in)  else datetime.time(8,0)
            cout_def = rec.clock_out if pd.notna(rec.clock_out) else datetime.time(17,0)
            cin  = st.time_input("Clock‑in",  cin_def,  key=f"cin_{rid}")
            cout = st.time_input("Clock‑out", cout_def, key=f"cout_{rid}")

            efff_def = rec.effective_from if pd.notna(rec.effective_from) else datetime.date.today()
            efff_def = efff_def.date() if isinstance(efff_def, pd.Timestamp) else efff_def
            efff = st.date_input("Effective from", efff_def, key=f"efff_{rid}")

            rsn = st.text_area("Reason", rec.reason or "", key=f"rsn_{rid}")

            save_btn, cancel_btn = st.columns(2)
            if save_btn.form_submit_button("💾 Save"):
                close_current_and_add(
                    eid=int(rec.employeeid),
                    payload={
                        "wd":  int(wd),
                        "off": dow.index(off),
                        "cin": cin,
                        "cout": cout,
                        "eff": efff,
                        "rsn": rsn
                    }
                )
                st.session_state.pop("edit_row")
                st.rerun()

            if cancel_btn.form_submit_button("❌ Cancel"):
                st.session_state.pop("edit_row")
                st.rerun()
    else:
        st.session_state.pop("edit_row", None)
