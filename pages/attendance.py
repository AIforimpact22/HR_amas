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
        lambda r:False if r.expected_in is None else
        pd.notna(r.clock_in) and r.clock_in.time() >
        (datetime.datetime.combine(datetime.date.today(),r.expected_in)+datetime.timedelta(minutes=5)).time(),axis=1)
    return df

def fetch_range(eid:int,s:datetime.date,e:datetime.date)->pd.DataFrame:
    df = pd.read_sql(SQL_RANGE, engine, params={"eid":eid,"s":s,"e":e})
    if df.empty: return df
    df["clock_in_str"]  = pd.to_datetime(df.clock_in).dt.strftime("%H:%M")
    df["clock_out_str"] = pd.to_datetime(df.clock_out).dt.strftime("%H:%M")
    df["hours"] = df.secs / 3600
    df["late"]  = df.apply(
        lambda r:False if r.expected_in is None else
        pd.notna(r.clock_in) and pd.to_datetime(r.clock_in).time() >
        (datetime.datetime.combine(datetime.date.today(),r.expected_in)+datetime.timedelta(minutes=5)).time(),axis=1)
    return df

def list_employees() -> pd.DataFrame:
    return pd.read_sql("SELECT employeeid, fullname FROM hr_employee ORDER BY fullname",engine)

def fetch_all_schedules() -> pd.DataFrame:
    return pd.read_sql(SQL_SCHEDULE_ALL,engine)

def update_schedule_row(att_id:int, cols:dict):
    sets=", ".join(f"{k}=:{k}" for k in cols)
    cols["att_id"]=att_id
    sql=text(f"UPDATE hr_attendance_history SET {sets} WHERE att_id=:att_id")
    with engine.begin() as con:
        con.execute(sql,cols)

# ─── UTILITIES ─────────────────────────────────────────────────
dow = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"]

def fmt_time(t):
    if pd.isna(t): return "—"
    if isinstance(t,datetime.time): return t.strftime("%H:%M")
    return pd.to_datetime(t).strftime("%H:%M")

def fmt_date(d):
    if pd.isna(d): return "—"
    return d.date().isoformat() if hasattr(d,"date") else str(d)

def clean_off_index(val):
    """Return a safe 0‑6 index for selectbox."""
    if pd.isna(val): return 0
    try:
        i=int(val)
        return i if 0<=i<7 else 0
    except Exception:
        return 0

def safe_int(val, default=0):
    try:
        return int(val)
    except Exception:
        return default

# ─── UI CONFIG ──────────────────────────────────────────────────
st.set_page_config("Attendance","⏱",layout="wide")
st.title("⏱ Attendance")

tab_grid, tab_log, tab_sched = st.tabs(
    ["🗓 Daily Grid","📜 Employee Log History","⚙️ Schedule / Shifts"]
)

# ─── TAB 1 & TAB 2 (unchanged) ──────────────────────────────────
#   … keep your working code for Daily Grid and Log History …

# ══════════ TAB 3 — SCHEDULE / SHIFTS ═══════════════════════════
with tab_sched:
    sch = fetch_all_schedules()
    if sch.empty:
        st.info("No schedule rows found.")
        st.stop()

    # build display table
    view = pd.DataFrame({
        "Employee":        sch.fullname,
        "Work days/wk":    sch.wd_per_wk.fillna("—"),
        "Off‑day":         sch.off_day.apply(lambda v:dow[int(v)] if pd.notna(v) and 0<=int(v)<7 else "—"),
        "Clock‑in":        sch.clock_in.apply(fmt_time),
        "Clock‑out":       sch.clock_out.apply(fmt_time),
        "Effective from":  sch.effective_from.apply(fmt_date),
        "Effective to":    sch.effective_to.apply(fmt_date),
        "Reason":          sch.reason.fillna(""),
        "att_id":          sch.att_id
    })

    st.subheader("All employee schedules")
    headers=["Employee","Work days/wk","Off‑day","Clock‑in","Clock‑out",
             "Effective from","Effective to","Reason",""]
    header_cols=st.columns(len(headers))
    for c,h in zip(header_cols,headers):
        c.markdown(f"**{h}**")

    for _,row in view.iterrows():
        cols=st.columns(len(headers))
        for i,field in enumerate(view.columns[:-1]):   # skip att_id
            cols[i].markdown(str(row[field]))
        if cols[-1].button("✏️", key=f"edit_{row.att_id}"):
            st.session_state["edit_row"]=int(row.att_id)

    # ─── inline edit form ──────────────────────────────────────
    if "edit_row" in st.session_state and st.session_state["edit_row"] in set(sch.att_id):
        rid=int(st.session_state["edit_row"])
        rec=sch.loc[sch.att_id==rid].iloc[0]

        st.markdown("---")
        st.subheader(f"Edit schedule • {rec.fullname}")
        with st.form(f"form_{rid}"):
            wd_default = safe_int(rec.wd_per_wk,6)
            wd  = st.number_input("Work days / week",1,7,wd_default,key=f"wd_{rid}")

            off_idx = clean_off_index(rec.off_day)
            off = st.selectbox("Off‑day",dow,index=off_idx,key=f"off_{rid}")

            cin_default  = rec.clock_in if pd.notna(rec.clock_in) else datetime.time(8,0)
            cout_default = rec.clock_out if pd.notna(rec.clock_out) else datetime.time(17,0)
            cin  = st.time_input("Clock‑in", cin_default,  key=f"cin_{rid}")
            cout = st.time_input("Clock‑out",cout_default,key=f"cout_{rid}")

            efff_default = rec.effective_from if pd.notna(rec.effective_from) else datetime.date.today()
            if isinstance(efff_default,pd.Timestamp): efff_default=efff_default.date()
            efff = st.date_input("Effective from",efff_default,key=f"efff_{rid}")

            efft_default = rec.effective_to if pd.notna(rec.effective_to) else datetime.date(2100,1,1)
            if isinstance(efft_default,pd.Timestamp): efft_default=efft_default.date()
            efft = st.date_input("Effective to (blank = open)",efft_default,key=f"efft_{rid}")
            efft = None if efft==datetime.date(2100,1,1) else efft

            rsn = st.text_area("Reason",rec.reason or "",key=f"rsn_{rid}")

            s_col,c_col = st.columns(2)
            if s_col.form_submit_button("💾 Save"):
                close_current_and_add(
                    eid = int(rec.employeeid),
                    payload = {
                    "wd":  int(wd),
                    "off": dow.index(off),
                    "cin": cin,
                    "cout": cout,
                    "eff": efff,       efft,
                    "rsn": rsn            rsn
                }
            )

                st.session_state.pop("edit_row")
                st.rerun()

            if c_col.form_submit_button("❌ Cancel"):
                st.session_state.pop("edit_row")
                st.rerun()
    else:
        st.session_state.pop("edit_row",None)
