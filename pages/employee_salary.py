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
st.set_page_config(page_title="Employee Salary", page_icon="💰", layout="wide")
st.title("💰 Employee Salary")

col_y, col_m = st.columns(2)
year  = col_y.number_input("Year", 2020, 2030, datetime.date.today().year, 1)
month = col_m.selectbox("Month", range(1,13),
                        index=datetime.date.today().month-1,
                        format_func=lambda m: calendar.month_name[m])

start_d, end_d = month_range(year, month)
st.caption(f"Period: **{start_d:%Y-%m-%d} → {end_d:%Y-%m-%d}**")

df = fetch_month(start_d, end_d)

# totals
tot_base = df["base"].sum()
tot_adj  = (df["bonus"]+df["extra"]-df["fine"]).sum()
tot_net  = df["net"].sum()
m1,m2,m3 = st.columns(3)
m1.metric("Total base", f"{tot_base:,.0f}")
m2.metric("Total adj.", f"{tot_adj:+,.0f}")
m3.metric("Total net",  f"{tot_net:,.0f}")

st.divider()

# header
hdr = ["Employee","Base","Bonus","Extra","Fine","Net",
       "Worked","Req.","Δ","Reasons",""]
for lbl, col in zip(hdr, st.columns([2,1,1,1,1,1,1,1,1.2,2,1])):
    col.markdown(f"**{lbl}**")

# rows
for _, r in df.iterrows():
    cols = st.columns([2,1,1,1,1,1,1,1,1.2,2,1])
    eid = int(r["employeeid"])
    cols[0].markdown(r["fullname"])
    cols[1].markdown(f"{r['base']:,.0f}")
    cols[2].markdown(f"{r['bonus']:,.0f}")
    cols[3].markdown(f"{r['extra']:,.0f}")
    cols[4].markdown(f"{r['fine']:,.0f}")
    cols[5].markdown(f"{r['net']:,.0f}")

    ok = r["worked"] >= r["required"]
    bg = "#d4edda" if ok else "#f8d7da"
    cols[6].markdown(f"<div style='background:{bg};padding:2px'>{r['worked']:.1f}</div>",
                     unsafe_allow_html=True)
    cols[7].markdown(f"{r['required']:.1f}")
    cols[8].markdown(f"<div style='background:{bg};padding:2px'>{r['delta']:+.1f}</div>",
                     unsafe_allow_html=True)
    cols[9].markdown(r["reasons"] or "—")

    if cols[-1].button("Edit", key=f"edit_{eid}"):
        st.session_state["edit_emp"] = eid

    # inline editor
    if st.session_state.get("edit_emp") == eid:
        with st.form(f"form_{eid}"):
            kind   = st.selectbox("Type", ["bonus","extra","fine"], key=f"k{eid}")
            amt    = st.number_input("Amount", 0.0, step=1000.0, key=f"a{eid}")
            reason = st.text_area("Reason", key=f"r{eid}")
            date_  = st.date_input("Date", datetime.date.today(), key=f"d{eid}")
            col_s, col_c = st.columns(2)
            save   = col_s.form_submit_button("Save")
            cancel = col_c.form_submit_button("Cancel")
            if save:
                if amt <= 0:
                    st.error("Amount must be > 0")
                else:
                    add_txn(eid, date_, amt, kind, reason)
                    st.success("Saved.")
                    st.session_state.pop("edit_emp", None)
                    st.cache_data.clear()
                    st.rerun()            # ← updated
            elif cancel:
                st.session_state.pop("edit_emp", None)
                st.rerun()                # ← updated
