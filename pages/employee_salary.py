import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
import datetime, calendar

# ─────────────────────────────────────────
# DB engine (cached)
# ─────────────────────────────────────────
if "pg_engine" not in st.session_state:
    st.session_state.pg_engine = create_engine(
        st.secrets["neon"]["dsn"], pool_pre_ping=True, echo=False
    )
engine = st.session_state.pg_engine

# ─────────────────────────────────────────
# Helper utilities
# ─────────────────────────────────────────
def month_range(year: int, month: int):
    start = datetime.date(year, month, 1)
    last  = calendar.monthrange(year, month)[1]
    return start, datetime.date(year, month, last)

@st.cache_data(show_spinner=False)
def month_summary(start: datetime.date, end: datetime.date) -> pd.DataFrame:
    sql = text("""
        SELECT e.employeeid,
               e.fullname,
               e.basicsalary                                           AS base,
               COALESCE(SUM(CASE WHEN l.txn_type='bonus' THEN l.amount END),0) AS bonus,
               COALESCE(SUM(CASE WHEN l.txn_type='extra' THEN l.amount END),0) AS extra,
               COALESCE(SUM(CASE WHEN l.txn_type='fine'  THEN l.amount END),0) AS fine
        FROM hr_employee e
        LEFT JOIN hr_salary_log l
               ON l.employeeid = e.employeeid
              AND l.txn_date BETWEEN :s AND :e
        GROUP BY e.employeeid, e.fullname, e.basicsalary
        ORDER BY e.fullname
    """)
    df = pd.read_sql(sql, engine, params={"s": start, "e": end})
    df["net"] = df["base"] + df["bonus"] + df["extra"] - df["fine"]
    return df

def fetch_log(emp_id: int, start: datetime.date, end: datetime.date) -> pd.DataFrame:
    sql = text("""
        SELECT txn_date, txn_type, amount, reason
        FROM hr_salary_log
        WHERE employeeid = :eid AND txn_date BETWEEN :s AND :e
        ORDER BY txn_date
    """)
    return pd.read_sql(sql, engine, params={"eid": emp_id, "s": start, "e": end})

def add_txn(emp_id: int, date_: datetime.date, amt: float, kind: str, reason: str):
    sql = text("""
        INSERT INTO hr_salary_log (employeeid, txn_date, amount, txn_type, reason)
        VALUES (:eid, :d, :a, :k, :r)
    """)
    with engine.begin() as con:
        con.execute(sql, {"eid": emp_id, "d": date_, "a": amt, "k": kind, "r": reason})

# ─────────────────────────────────────────
# Page config
# ─────────────────────────────────────────
st.set_page_config("Employee Salary", "💰", layout="wide")
st.title("💰 Employee Salary")

tab_sum, tab_adj = st.tabs(["📊 Monthly Summary", "➕ Add Adjustment"])

# common month picker state
year_c, month_c = st.columns(2)
year  = year_c.number_input("Year", 2020, 2030, datetime.date.today().year, step=1)
month = month_c.selectbox("Month", list(range(1,13)),
                          index=datetime.date.today().month-1,
                          format_func=lambda m: calendar.month_name[m])

start_m, end_m = month_range(year, month)

# ─────────────────────────────────────────
# TAB 1 – Monthly Summary
# ─────────────────────────────────────────
with tab_sum:
    st.caption(f"Period: **{start_m:%Y‑%m‑%d} → {end_m:%Y‑%m‑%d}**")
    df = month_summary(start_m, end_m)

    # summary metrics
    m1,m2,m3 = st.columns(3)
    m1.metric("Total base", f"{df['base'].sum():,.0f}")
    m2.metric("Total adj.", f"{(df['bonus']+df['extra']-df['fine']).sum():+,.0f}")
    m3.metric("Total net",  f"{df['net'].sum():,.0f}")

    # colour rules
    def row_style(row):
        s = [""]*len(row)
        if row["Bonus"]>0 or row["Extra"]>0:
            if row["Bonus"]>0: s[2] = "background-color:#d4edda;"
            if row["Extra"]>0: s[3] = "background-color:#d4edda;"
        if row["Fine"]>0: s[4] = "background-color:#f8d7da;"
        if row["Net"]<row["Base"]: s[-1]="background-color:#fff3cd;"
        return s

    disp = df.rename(columns={"fullname":"Employee","base":"Base",
                              "bonus":"Bonus","extra":"Extra","fine":"Fine","net":"Net"})
    disp = disp[["Employee","Base","Bonus","Extra","Fine","Net"]]
    styled = disp.style.apply(row_style, axis=1).format("{:,.0f}",
              subset=["Base","Bonus","Extra","Fine","Net"])
    st.dataframe(styled, use_container_width=True, hide_index=True)

    # audit trail expanders
    st.subheader("Audit trail")
    for _, r in df.iterrows():
        with st.expander(f"{r['fullname']}"):
            log = fetch_log(int(r["employeeid"]), start_m, end_m)
            if log.empty:
                st.write("No adjustments.")
            else:
                log_d = log.rename(columns={"txn_date":"Date","txn_type":"Type",
                                            "amount":"Amount","reason":"Reason"})
                log_d["Amount"] = log_d["Amount"].map("{:,.0f}".format)
                st.dataframe(log_d, hide_index=True, use_container_width=True)

# ─────────────────────────────────────────
# TAB 2 – Add Adjustment
# ─────────────────────────────────────────
with tab_adj:
    st.caption("Post a bonus, extra, or fine (amount is always POSITIVE).")
    all_emp = pd.read_sql("SELECT employeeid, fullname FROM hr_employee ORDER BY fullname", engine)
    if all_emp.empty:
        st.error("No employees in database.")
    else:
        with st.form("add_form"):
            emp_name = st.selectbox("Employee", all_emp["fullname"])
            emp_id   = int(all_emp.loc[all_emp["fullname"]==emp_name, "employeeid"].iloc[0])
            kind     = st.selectbox("Type", ["bonus","extra","fine"])
            amount   = st.number_input("Amount", min_value=0.0, step=1000.0)
            reason   = st.text_area("Reason")
            date_    = st.date_input("Date", datetime.date.today())
            submitted = st.form_submit_button("Add")
            if submitted:
                if amount<=0:
                    st.error("Amount must be >0")
                else:
                    add_txn(emp_id, date_, amount, kind, reason)
                    st.success("Adjustment saved!")
                    st.cache_data.clear()

        # recent log
        rec = pd.read_sql(
            text("SELECT txn_date, txn_type, amount, reason, employeeid "
                 "FROM hr_salary_log ORDER BY created_at DESC LIMIT 10"),
            engine
        )
        if not rec.empty:
            rec = rec.merge(all_emp, on="employeeid")
            rec = rec[["txn_date","fullname","txn_type","amount","reason"]].rename(
                columns={"txn_date":"Date","fullname":"Employee",
                         "txn_type":"Type","amount":"Amount","reason":"Reason"})
            rec["Amount"] = rec["Amount"].map("{:,.0f}".format)
            st.subheader("Recent adjustments")
            st.dataframe(rec, hide_index=True, use_container_width=True)
