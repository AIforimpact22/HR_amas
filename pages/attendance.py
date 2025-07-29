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

# Tab‑3 query: every employee’s schedules
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
    return pd.read_sql(SQL_SCHEDULE_ALL, engine)

def update_schedule_row(att_id:int, cols:dict):
    sets = ", ".join(f"{k}=:{k}" for k in cols)
    cols["att_id"] = att_id
    sql = text(f"UPDATE hr_attendance_history SET {sets} WHERE att_id=:att_id")
    with engine.begin() as con:
        con.execute(sql, cols)

# ─── UTILITIES ─────────────────────────────────────────────────
def fmt_time(t):
    if pd.isna(t):
        return "—"
    if isinstance(t, datetime.time):
        return t.strftime("%H:%M")
    return pd.to_datetime(t).strftime("%H:%M")

def fmt_date(d):
    if pd.isna(d):
        return "—"
    return d.date().isoformat() if hasattr(d, "date") else str(d)

dow = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"]

# ─── UI CONFIG ──────────────────────────────────────────────────
st.set_page_config("Attendance", "⏱", layout="wide")
st.title("⏱ Attendance")

tab_grid, tab_log, tab_sched = st.tabs(
    ["🗓 Daily Grid", "📜 Employee Log History", "⚙️ Schedule / Shifts"]
)
