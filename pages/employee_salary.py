import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
import datetime, calendar

# ─────────────  DB engine (cached)  ─────────────
if "pg_engine" not in st.session_state:
    st.session_state.pg_engine = create_engine(
        st.secrets["neon"]["dsn"], pool_pre_ping=True, echo=False
    )
engine = st.session_state.pg_engine

# ─────────────  Helpers  ─────────────
def month_range(y: int, m: int):
    start = datetime.date(y, m, 1)
    end   = datetime.date(y, m, calendar.monthrange(y, m)[1])
    return start, end

def month_summary(start: datetime.date, end: datetime.date) -> pd.DataFrame:
    sql = text("""
        SELECT e.employeeid,
               e.fullname,
               e.basicsalary                                            AS base,
               COALESCE(SUM(CASE WHEN l.txn_type='bonus' THEN l.amount END),0) AS bonus,
               COALESCE(SUM(CASE WHEN l.txn_type='extra' THEN l.amount END),0) AS extra,
               COALESCE(SUM(CASE WHEN l.txn_type='fine'  THEN l.amount END),0) AS fine
        FROM hr_employee e
        LEFT JOIN hr_salary_log l
               ON l.employeeid = e.employeeid
              AND l.txn_date BETWEEN :s AND :e
        GROUP BY e.employeeid, e.fullname, e.basicsalary
        ORDER BY e.fullname;
    """)
    df = pd.read_sql(sql, engine, params={"s": start, "e": end})
    df["net"] = df["base"] + df["bonus"] + df["extra"] - df["fine"]
    return df

def add_txn(emp_id:int, date_:datetime.date, amt:float, kind:str, reason:str):
    sql = text("""INSERT INTO hr_salary_log
                  (employeeid, txn_date, amount, txn_type, reason)
                  VALUES (:eid, :d, :a, :k, :r)""")
    with engine.begin() as con:
        con.execute(sql, {"eid":emp_id,"d":date_,"a":amt,"k":kind,"r":reason})

# ─────────────  Page  ─────────────
st.set_page_config("Employee Salary", "💰", layout="wide")
st.title("💰 Employee Salary")

# Month picker
yr, mo = st.columns(2)
year  = yr.number_input("Year", 2020, 2030, datetime.date.today().year, 1)
month = mo.selectbox("Month", list(range(1,13)),
                     index=datetime.date.today().month-1,
                     format_func=lambda m: calendar.month_name[m])

start_d, end_d = month_range(year, month)
st.caption(f"Period: **{start_d:%Y-%m-%d} → {end_d:%Y-%m-%d}**")

df = month_summary(start_d, end_d)

# Summary metrics
base_tot  = df["base"].sum()
adj_tot   = (df["bonus"]+df["extra"]-df["fine"]).sum()
net_tot   = df["net"].sum()
c1,c2,c3 = st.columns(3)
c1.metric("Total base", f"{base_tot:,.0f}")
c2.metric("Total adj.", f"{adj_tot:+,.0f}")
c3.metric("Total net",  f"{net_tot:,.0f}")

st.divider()

# Row styling helper
def style_row(row):
    s = [""]*6
    if row["Bonus"]>0: s[2]="background-color:#d4edda;"
    if row["Extra"]>0: s[3]="background-color:#d4edda;"
    if row["Fine"]>0:  s[4]="background-color:#f8d7da;"
    if row["Net"]<row["Base"]: s[5]="background-color:#fff3cd;"
    return s

# Container for grid + editors
for idx, r in df.iterrows():
    cols = st.columns([2,1,1,1,1,1,1])
    # display numeric values
    cols[0].markdown(f"**{r['fullname']}**")
    for i, key in enumerate(["base","bonus","extra","fine","net"], start=1):
        cols[i].markdown(f"{r[key]:,.0f}")
    # --- edit button ---
    edit_key = f"edit_{r['employeeid']}"
    if cols[-1].button("Edit", key=edit_key):
        st.session_state["edit_emp"] = r["employeeid"]

    # --- inline editor ---
    if st.session_state.get("edit_emp") == r["employeeid"]:
        with st.form(f"form_{r['employeeid']}"):
            kind   = st.selectbox("Type", ["bonus","extra","fine"], key=f"kind_{r['employeeid']}")
            amt    = st.number_input("Amount (positive)", 0.0, step=1000.0,
                                     key=f"amt_{r['employeeid']}")
            reason = st.text_area("Reason", key=f"rsn_{r['employeeid']}")
            date_  = st.date_input("Date", datetime.date.today(),
                                   key=f"date_{r['employeeid']}")
            sub = st.form_submit_button("Save")
            if sub:
                if amt<=0:
                    st.error("Amount must be > 0")
                else:
                    add_txn(int(r["employeeid"]), date_, amt, kind, reason)
                    st.success("Saved!")
                    st.session_state.pop("edit_emp", None)
                    st.cache_data.clear()
                    st.experimental_rerun()

# Dataframe view (colour coded) below the editable grid
st.subheader("Table view")
disp = df.rename(columns={"fullname":"Employee","base":"Base","bonus":"Bonus",
                          "extra":"Extra","fine":"Fine","net":"Net"})
styled = disp[["Employee","Base","Bonus","Extra","Fine","Net"]].style\
          .apply(style_row, axis=1)\
          .format("{:,.0f}", subset=["Base","Bonus","Extra","Fine","Net"])
st.dataframe(styled, use_container_width=True, hide_index=True)
