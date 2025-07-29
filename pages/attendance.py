import streamlit as st, datetime, math
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

SQL_SCHEDULE_ALL = """
SELECT h.att_id,
       e.employeeid,
       e.fullname,
       h.work_days_per_week     AS wd_per_wk,
       h.off_day,
       h.clock_in,
       h.clock_out,
       h.effective_from,
       h.effective_to,
       h.reason
FROM   hr_attendance_history h
JOIN   hr_employee           e  ON e.employeeid = h.employeeid
ORDER  BY e.fullname, h.effective_from
"""

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
         + datetime.timedelta(minutes=5)).time(), axis=1)
    return df

def fetch_range(eid:int, s:datetime.date, e:datetime.date)->pd.DataFrame:
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
         + datetime.timedelta(minutes=5)).time(), axis=1)
    return df

def list_employees():
    return pd.read_sql("SELECT employeeid, fullname FROM hr_employee ORDER BY fullname", engine)

def fetch_all_schedules() -> pd.DataFrame:
    """Return every schedule row for every employee."""
    return pd.read_sql(SQL_SCHEDULE_ALL, engine)

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

# ─── UTILITIES ──────────────────────────────────────────────────
def fmt_time(t):
    if pd.isna(t):
        return "—"
    if isinstance(t, datetime.time):
        return t.strftime("%H:%M")
    return pd.to_datetime(t).strftime("%H:%M")

dow = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

# ─── UI CONFIG ──────────────────────────────────────────────────
st.set_page_config("Attendance", "⏱", layout="wide")
st.title("⏱ Attendance")

tab_grid, tab_log, tab_sched = st.tabs(
    ["🗓 Daily Grid", "📜 Employee Log History", "⚙️ Schedule / Shifts"]
)

# ══════════  TAB 1 & 2 (unchanged)  ═════════════════════════════
# ... (everything from the previous answer or your working version)

# ══════════  TAB 3 — NEW DESIGN  ════════════════════════════════
with tab_sched:
    sch = fetch_all_schedules()
    if sch.empty:
        st.info("No schedule rows in the system yet.")
        st.stop()

    # build a clean dataframe for display
    view = pd.DataFrame({
        "Employee":      sch.fullname,
        "Work days/wk":  sch.wd_per_wk,
        "Off‑day":       sch.off_day.map(lambda i: dow[i] if 0 <= i < 7 else "—"),
        "Clock‑in":      sch.clock_in.apply(fmt_time),
        "Clock‑out":     sch.clock_out.apply(fmt_time),
        "Effective from":sch.effective_from.dt.date,
        "Effective to":  sch.effective_to.apply(lambda d: "—" if pd.isna(d) else d.date()),
        "Reason":        sch.reason.fillna(""),
    })
    # we keep att_id to know which row to edit later
    view["att_id"] = sch.att_id

    # render table‑like layout with Edit buttons
    st.subheader("All employee schedules")
    header_cols = st.columns(len(view.columns) - 1 + 1)  # +1 for the Edit header
    for i, col_name in enumerate(["Employee", "Work days/wk", "Off‑day",
                                  "Clock‑in", "Clock‑out",
                                  "Effective from", "Effective to", "Reason", ""]):
        header_cols[i].markdown(f"**{col_name}**")

    for idx, row in view.iterrows():
        cols = st.columns(len(view.columns) - 1 + 1)
        for i, field in enumerate(["Employee", "Work days/wk", "Off‑day",
                                   "Clock‑in", "Clock‑out",
                                   "Effective from", "Effective to", "Reason"]):
            cols[i].markdown(str(row[field]))
        # edit button
        if cols[-1].button("✏️ Edit", key=f"edit_{row.att_id}"):
            st.session_state["edit_row"] = int(row.att_id)

    # ─── modal edit form ────────────────────────────────────────
    if "edit_row" in st.session_state:
        rid = st.session_state["edit_row"]
        rec = sch.loc[sch.att_id == rid].iloc[0]

        with st.modal(f"Edit schedule • {rec.fullname}"):
            wd  = st.number_input("Work days / week", 1, 7, int(rec.wd_per_wk), key="modal_wd")
            off = st.selectbox("Off‑day", dow, index=rec.off_day if 0 <= rec.off_day < 7 else 0, key="modal_off")
            cin_default  = rec.clock_in  if pd.notna(rec.clock_in)  else datetime.time(8, 0)
            cout_default = rec.clock_out if pd.notna(rec.clock_out) else datetime.time(17, 0)
            cin  = st.time_input("Clock‑in",  cin_default,  key="modal_cin")
            cout = st.time_input("Clock‑out", cout_default, key="modal_cout")
            efff = st.date_input("Effective from",
                                 rec.effective_from.date(), key="modal_efff")
            efft_def = datetime.date(2100,1,1) if pd.isna(rec.effective_to) else rec.effective_to.date()
            efft = st.date_input("Effective to (blank = open)",
                                 efft_def, key="modal_efft")
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
