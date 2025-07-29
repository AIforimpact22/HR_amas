import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
import datetime, calendar

# ─── DB engine (cached) ─────────────────────────────────────────
if "pg_engine" not in st.session_state:
    st.session_state.pg_engine = create_engine(
        st.secrets["neon"]["dsn"], pool_pre_ping=True, echo=False
    )
engine = st.session_state.pg_engine
SHIFT_HOURS = 8.5

# ─── Helpers ────────────────────────────────────────────────────
def month_range(y, m):
    start = datetime.date(y, m, 1)
    end   = datetime.date(y, m, calendar.monthrange(y, m)[1])
    return start, end

@st.cache_data(show_spinner=False)
def fetch_month(start: datetime.date, end: datetime.date) -> pd.DataFrame:
    sql = text("""
    WITH adj AS (
        SELECT employeeid,
               SUM(CASE WHEN txn_type='bonus' THEN amount END) AS bonus,
               SUM(CASE WHEN txn_type='extra' THEN amount END) AS extra,
               SUM(CASE WHEN txn_type='fine'  THEN amount END) AS fine,
               STRING_AGG(reason, '; ' ORDER BY txn_date)      AS reasons
        FROM hr_salary_log
        WHERE txn_date BETWEEN :s AND :e
        GROUP BY employeeid
    ),
    att AS (
        SELECT employeeid,
               COUNT(*)                       AS days_worked,
               SUM(EXTRACT(EPOCH FROM (COALESCE(clock_out,clock_in) - clock_in)))/3600 AS worked
        FROM hr_attendance
        WHERE punch_date BETWEEN :s AND :e
        GROUP BY employeeid
    )
    SELECT e.employeeid,
           e.fullname,
           e.basicsalary                         AS base,
           COALESCE(a.bonus ,0)                  AS bonus,
           COALESCE(a.extra ,0)                  AS extra,
           COALESCE(a.fine  ,0)                  AS fine,
           COALESCE(att.worked,0)                AS worked,
           COALESCE(att.days_worked,0)*:shift    AS required,
           COALESCE(att.worked,0)-COALESCE(att.days_worked,0)*:shift AS delta,
           COALESCE(a.reasons,'')                AS reasons
    FROM hr_employee e
    LEFT JOIN adj a   USING (employeeid)
    LEFT JOIN att att USING (employeeid)
    ORDER BY e.fullname
    """)
    df = pd.read_sql(sql, engine, params={"s": start, "e": end, "shift": SHIFT_HOURS})
    df["net"] = df["base"] + df["bonus"] + df["extra"] - df["fine"]
    return df

def add_txn(emp_id:int, date_:datetime.date, amt:float, kind:str, reason:str):
    sql=text("INSERT INTO hr_salary_log (employeeid,txn_date,amount,txn_type,reason) "
             "VALUES (:eid,:d,:a,:k,:r)")
    with engine.begin() as con:
        con.execute(sql, {"eid":emp_id,"d":date_,"a":amt,"k":kind,"r":reason})

# ─── Page ───────────────────────────────────────────────────────
st.set_page_config("Employee Salary","💰",layout="wide")
st.title("💰 Employee Salary")

c_year, c_month = st.columns(2)
year  = c_year.number_input("Year", 2020, 2030, datetime.date.today().year, 1)
month = c_month.selectbox("Month", range(1,13),
                          index=datetime.date.today().month-1,
                          format_func=lambda m: calendar.month_name[m])

start_d, end_d = month_range(year, month)
st.caption(f"Period: **{start_d:%Y-%m-%d} → {end_d:%Y-%m-%d}**")

df = fetch_month(start_d, end_d)

# totals
base_tot = df["base"].sum()
adj_tot  = (df["bonus"]+df["extra"]-df["fine"]).sum()
net_tot  = df["net"].sum()
m1,m2,m3 = st.columns(3)
m1.metric("Total base", f"{base_tot:,.0f}")
m2.metric("Total adj.", f"{adj_tot:+,.0f}")
m3.metric("Total net",  f"{net_tot:,.0f}")

st.divider()

# header row
hdr = ["Employee","Base","Bonus","Extra","Fine","Net",
       "Worked","Req.","Δ","Reasons",""]
for w,col in zip([2,1,1,1,1,1,1,1,1.2,2,1], st.columns([2,1,1,1,1,1,1,1,1.2,2,1])):
    col.markdown(f"**{hdr.pop(0)}**")

# data rows
for _, row in df.iterrows():
    cols = st.columns([2,1,1,1,1,1,1,1,1.2,2,1])
    emp_id = int(row["employeeid"])
    cols[0].markdown(row["fullname"])
    cols[1].markdown(f"{row['base']:,.0f}")
    cols[2].markdown(f"{row['bonus']:,.0f}")
    cols[3].markdown(f"{row['extra']:,.0f}")
    cols[4].markdown(f"{row['fine']:,.0f}")
    cols[5].markdown(f"{row['net']:,.0f}")

    ok = row["worked"] >= row["required"]
    bg = "#d4edda" if ok else "#f8d7da"
    cols[6].markdown(f"<div style='background:{bg};padding:2px'>{row['worked']:.1f}</div>",
                     unsafe_allow_html=True)
    cols[7].markdown(f"{row['required']:.1f}")
    cols[8].markdown(f"<div style='background:{bg};padding:2px'>{row['delta']:+.1f}</div>",
                     unsafe_allow_html=True)
    cols[9].markdown(row["reasons"] or "—")

    if cols[-1].button("Edit", key=f"edit_{emp_id}"):
        st.session_state["edit_emp"] = emp_id

    if st.session_state.get("edit_emp") == emp_id:
        with st.form(f"form_{emp_id}"):
            kind   = st.selectbox("Type", ["bonus","extra","fine"], key=f"k{emp_id}")
            amt    = st.number_input("Amount", 0.0, step=1000.0, key=f"a{emp_id}")
            reason = st.text_area("Reason", key=f"r{emp_id}")
            date_  = st.date_input("Date", datetime.date.today(), key=f"d{emp_id}")
            save   = st.form_submit_button("Save")
            cancel = st.form_submit_button("Cancel")
            if save:
                if amt <= 0:
                    st.error("Amount must be > 0")
                else:
                    add_txn(emp_id, date_, amt, kind, reason)
                    st.success("Saved.")
                    st.session_state.pop("edit_emp", None)
                    st.cache_data.clear()
                    st.experimental_rerun()
            elif cancel:
                st.session_state.pop("edit_emp", None)
                st.experimental_rerun()
