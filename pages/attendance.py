import streamlit as st, datetime, math
import pandas as pd
from sqlalchemy import create_engine, text

# ─── DB engine (cached) ──────────────────────────────────────────
if "pg_engine" not in st.session_state:
    st.session_state.pg_engine = create_engine(
        st.secrets["neon"]["dsn"], pool_pre_ping=True, echo=False
    )
engine = st.session_state.pg_engine

# ─── Helper SQL fragments ------------------------------------------------------
SQL_SHIFT_HRS = """
CASE
  WHEN h.clock_out >= h.clock_in
    THEN (EXTRACT(EPOCH FROM h.clock_out) - EXTRACT(EPOCH FROM h.clock_in)) / 3600
  ELSE (EXTRACT(EPOCH FROM h.clock_out) + 86400 - EXTRACT(EPOCH FROM h.clock_in)) / 3600
END
"""

SQL_DAY = text(f"""
SELECT e.fullname, a.clock_in, a.clock_out,
       h.clock_in AS expected_in,
       {SQL_SHIFT_HRS} AS shift_hours,
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

SQL_RANGE = text(f"""
SELECT a.punch_date, a.clock_in, a.clock_out,
       h.clock_in AS expected_in,
       {SQL_SHIFT_HRS} AS shift_hours,
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

SQL_SCHEDULE = """
SELECT att_id, work_days_per_week, off_day,
       clock_in, clock_out,
       effective_from, effective_to, reason
FROM   hr_attendance_history
WHERE  employeeid = :eid
ORDER  BY effective_from
"""

# ─── DB helper wrappers --------------------------------------------------------
def fetch_day(day: datetime.date) -> pd.DataFrame:
    df = pd.read_sql(SQL_DAY, engine, params={"d": day})
    if df.empty:
        return df
    df["clock_in_str"]  = pd.to_datetime(df["clock_in"]).dt.strftime("%H:%M")
    df["clock_out_str"] = pd.to_datetime(df["clock_out"]).dt.strftime("%H:%M")
    df["hours"]         = df["secs"] / 3600.0
    df["net_str"]       = df["secs"].apply(
        lambda s: f"{int(s//3600):02d} h {int((s%3600)//60):02d} m")
    df["late"] = df.apply(
        lambda r: False if r.expected_in is None else
                  r.clock_in.time() >
                  (datetime.datetime.combine(datetime.date.today(), r.expected_in)
                   + datetime.timedelta(minutes=5)).time(),
        axis=1)
    return df

def fetch_range(emp_id:int, s:datetime.date, e:datetime.date)->pd.DataFrame:
    df = pd.read_sql(SQL_RANGE, engine, params={"eid":emp_id,"s":s,"e":e})
    if df.empty: return df
    df["clock_in_str"]  = pd.to_datetime(df["clock_in"]).dt.strftime("%H:%M")
    df["clock_out_str"] = pd.to_datetime(df["clock_out"]).dt.strftime("%H:%M")
    df["hours"]         = df["secs"] / 3600.0
    df["late"] = df.apply(
        lambda r: False if r.expected_in is None else
                  pd.to_datetime(r.clock_in).time() >
                  (datetime.datetime.combine(datetime.date.today(), r.expected_in)
                   + datetime.timedelta(minutes=5)).time(), axis=1)
    return df

def list_employees()->pd.DataFrame:
    return pd.read_sql("SELECT employeeid, fullname FROM hr_employee ORDER BY fullname", engine)

def get_schedule(emp_id:int)->pd.DataFrame:
    return pd.read_sql(SQL_SCHEDULE, engine, params={"eid":emp_id})

def update_schedule_row(att_id:int, cols:dict):
    sets = ", ".join(f"{k}=:{k}" for k in cols)
    cols["att_id"] = att_id
    sql = text(f"UPDATE hr_attendance_history SET {sets} WHERE att_id=:att_id")
    with engine.begin() as con:
        con.execute(sql, cols)

def close_current_and_add(emp_id:int, payload:dict):
    """
    Close the open row, then insert new one (prevent overlaps).
    payload keys: work_days_per_week, off_day, clock_in, clock_out,
                  effective_from, reason
    """
    close_date = payload["effective_from"] - datetime.timedelta(days=1)
    sql_close = text("""
        UPDATE hr_attendance_history
           SET effective_to = :close
         WHERE employeeid = :eid AND effective_to IS NULL
    """)
    sql_new = text("""
        INSERT INTO hr_attendance_history
              (employeeid, work_days_per_week, off_day,
               clock_in, clock_out,
               effective_from, reason)
        VALUES (:eid, :wd, :off, :cin, :cout, :eff, :rsn)
    """)
    with engine.begin() as con:
        con.execute(sql_close, {"close":close_date,"eid":emp_id})
        con.execute(sql_new, {
            "eid": emp_id,
            "wd":  payload["work_days_per_week"],
            "off": payload["off_day"],
            "cin": payload["clock_in"],
            "cout":payload["clock_out"],
            "eff": payload["effective_from"],
            "rsn": payload["reason"]
        })

# ─── UI setup ------------------------------------------------------------------
st.set_page_config("Attendance", "⏱", layout="wide")
st.title("⏱ Attendance")

tab_grid, tab_history, tab_sched = st.tabs(
    ["🗓 Daily Grid", "📜 Employee Log History", "⚙️ Schedule / Shifts"]
)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 • Daily grid  (unchanged)
# ═══════════════════════════════════════════════════════════════════════════════
with tab_grid:
    chosen_date = st.date_input(
        "Select date", datetime.date.today(),
        min_value=datetime.date.today() - datetime.timedelta(days=365),
        max_value=datetime.date.today())
    df = fetch_day(chosen_date)
    if df.empty:
        st.info("No punches recorded for this date.")
    else:
        st.markdown("""<style>
        .att-card{border:1px solid #DDD;border-radius:8px;padding:14px 16px;height:170px;
        display:flex;flex-direction:column;justify-content:space-between;margin-bottom:18px;}
        .att-card h4{font-size:0.95rem;margin:0 0 6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
        .small{font-size:0.78rem;margin:1px 0;} .in{font-weight:600;}
        .out{color:#e0a800;font-weight:600;}
        </style>""", unsafe_allow_html=True)
        COLS, rows = 5, math.ceil(len(df)/5)
        it = iter(df.to_dict("records"))
        st.subheader(f"{chosen_date:%A, %B %d %Y}")
        for _ in range(rows):
            cols = st.columns(COLS, gap="small")
            for col in cols:
                try:r=next(it)
                except StopIteration: col.empty(); continue
                net_c = "#1a873b" if r["hours"]>=r["shift_hours"] else "#c0392b"
                in_c  = "#dc3545" if r["late"] else "#1f77b4"
                col.markdown(f"""
<div class="att-card">
  <h4>{r['fullname']}</h4>
  <div class="small">IN  <span class="in" style="color:{in_c};">{r['clock_in_str']}</span></div>
  <div class="small">OUT <span class="out">{r['clock_out_str']}</span></div>
  <div class="small">NET <span style="color:{net_c};font-weight:600;">{r['net_str']}</span></div>
</div>""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 • Log History  (unchanged from fixed version)
# ═══════════════════════════════════════════════════════════════════════════════
with tab_history:
    emp_df = list_employees()
    emp_choice = st.selectbox("Employee", emp_df["fullname"])
    emp_id = int(emp_df.loc[emp_df.fullname==emp_choice,"employeeid"].iloc[0])
    today = datetime.date.today(); default_start = today.replace(day=1)
    start_date, end_date = st.date_input("Period",(default_start,today))
    if start_date>end_date:st.error("Start must be ≤ End"); st.stop()
    data = fetch_range(emp_id,start_date,end_date)
    st.subheader(f"{emp_choice}  •  {start_date} → {end_date}")
    if data.empty: st.info("No records"); st.stop()

    data["Req IN"]  = data["expected_in"].apply(lambda t:t.strftime("%H:%M") if pd.notna(t) else "—")
    data["Req OUT"] = data.apply(
        lambda r:"—" if pd.isna(r.expected_in) else
        (datetime.datetime.combine(r.punch_date,r.expected_in)+
         datetime.timedelta(hours=r.shift_hours)).strftime("%H:%M"), axis=1)
    data["Δ"] = data.apply(
        lambda r: f"{'+' if (m:=int(round((r.hours-r.shift_hours)*60)))>=0 else '−'}"
                  f"{abs(m)//60:02d}:{abs(m)%60:02d}", axis=1)

    tot, req = data.hours.sum(), data.shift_hours.sum()
    st.metric("Total hrs",f"{tot:.2f}")
    st.metric("Required", f"{req:.2f}")
    st.metric("Δ",f"{tot-req:+.2f}")

    tbl = data[["punch_date","clock_in_str","clock_out_str","Req IN","Req OUT","Δ"]]\
            .rename(columns={"punch_date":"Date","clock_in_str":"IN","clock_out_str":"OUT"})
    def sty(r):
        s=[""]*len(r)
        if r["Req IN"]!="—":
            exp=datetime.datetime.strptime(r["Req IN"],"%H:%M").time()
            act=datetime.datetime.strptime(r["IN"],"%H:%M").time()
            cut=(datetime.datetime.combine(today,exp)+datetime.timedelta(minutes=5)).time()
            s[1]="background-color:#f8d7da;" if act>cut else "background-color:#d1ecf1;"
        s[-1]="background-color:#d4edda;" if r["Δ"].startswith("+") else "background-color:#f8d7da;"
        return s
    st.dataframe(tbl.style.apply(sty,axis=1),use_container_width=True,hide_index=True)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3 • Schedule / Shifts  (NEW)
# ═══════════════════════════════════════════════════════════════════════════════
with tab_sched:
    emp_df = list_employees()
    emp_choice = st.selectbox("Employee ", emp_df["fullname"], key="sched_emp")
    emp_id = int(emp_df.loc[emp_df.fullname==emp_choice,"employeeid"].iloc[0])

    st.subheader(f"Shift history for {emp_choice}")

    sched = get_schedule(emp_id)
    dow = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"]

    # --------- existing rows -------------
    for _, row in sched.iterrows():
        exp = f"{row.effective_from} → {row.effective_to or '…'}"
        with st.expander(f"{exp}  •  {row.clock_in:%H:%M}-{row.clock_out:%H:%M}"):
            if st.button("Edit", key=f"edit_{row.att_id}"):
                st.session_state["edit_att"] = int(row.att_id)
            if st.session_state.get("edit_att") == int(row.att_id):
                with st.form(f"f_{row.att_id}"):
                    wd  = st.number_input("Work days / week",1,7,row.work_days_per_week)
                    off = st.selectbox("Weekly off‑day", dow, index=row.off_day)
                    cin = st.time_input("Clock‑in", row.clock_in)
                    cout= st.time_input("Clock‑out", row.clock_out)
                    eff_from = st.date_input("Effective from", row.effective_from)
                    eff_to   = st.date_input("Effective to (optional)",
                                             row.effective_to or datetime.date(2100,1,1))
                    eff_to   = None if eff_to==datetime.date(2100,1,1) else eff_to
                    rsn = st.text_area("Reason", row.reason or "")
                    sv,cc = st.columns(2)
                    if sv.form_submit_button("Save"):
                        update_schedule_row(row.att_id,{
                            "work_days_per_week": int(wd),
                            "off_day": dow.index(off),
                            "clock_in": cin,
                            "clock_out": cout,
                            "effective_from": eff_from,
                            "effective_to": eff_to,
                            "reason": rsn})
                        st.session_state.pop("edit_att",None); st.rerun()
                    if cc.form_submit_button("Cancel"):
                        st.session_state.pop("edit_att",None); st.rerun()

    st.markdown("---")
    st.subheader("Add new schedule row")
    with st.form("add_sched"):
        wd  = st.number_input("Work days / week",1,7,6)
        off = st.selectbox("Weekly off‑day", dow, index=5)
        cin = st.time_input("Clock‑in", datetime.time(8,0))
        cout= st.time_input("Clock‑out",datetime.time(16,30))
        eff_from = st.date_input("Effective from", datetime.date.today().replace(day=1))
        rsn = st.text_area("Reason")
        if st.form_submit_button("Add"):
            if cin == cout:
                st.error("Clock‑in and out can’t be equal.")
            else:
                payload = dict(work_days_per_week=int(wd),
                               off_day=dow.index(off),
                               clock_in=cin,
                               clock_out=cout,
                               effective_from=eff_from,
                               reason=rsn)
                close_current_and_add(emp_id, payload)
                st.success("New schedule saved."); st.rerun()
