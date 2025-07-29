import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
import datetime, calendar

# ───────────────────────────────────────────────
# DB engine (cached)
# ───────────────────────────────────────────────
if "pg_engine" not in st.session_state:
    st.session_state.pg_engine = create_engine(
        st.secrets["neon"]["dsn"], pool_pre_ping=True, echo=False
    )
engine = st.session_state.pg_engine

SHIFT_HOURS = 8.5  # not used here, kept for future logic

# ───────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────
def month_range(year: int, month: int):
    start = datetime.date(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    end = datetime.date(year, month, last_day)
    return start, end

@st.cache_data(show_spinner=False)
def get_month_summary(start: datetime.date, end: datetime.date) -> pd.DataFrame:
    sql = text(
        """
        SELECT e.employeeid,
               e.fullname,
               e.basicsalary                                AS base,
               COALESCE(SUM(CASE WHEN l.txn_type='bonus' THEN l.amount END),0) AS bonus,
               COALESCE(SUM(CASE WHEN l.txn_type='extra' THEN l.amount END),0) AS extra,
               COALESCE(SUM(CASE WHEN l.txn_type='fine'  THEN l.amount END),0) AS fine
        FROM hr_employee e
        LEFT JOIN hr_salary_log l
               ON l.employeeid = e.employeeid
              AND l.txn_date BETWEEN :s AND :e
        GROUP BY e.employeeid, e.fullname, e.basicsalary
        ORDER BY e.fullname;
        """
    )
    df = pd.read_sql(sql, engine, params={"s": start, "e": end})
    df["net"] = df["base"] + df["bonus"] + df["extra"] - df["fine"]
    return df

def get_log(emp_id: int, start: datetime.date, end: datetime.date) -> pd.DataFrame:
    sql = text(
        """
        SELECT txn_date, txn_type, amount, reason
        FROM hr_salary_log
        WHERE employeeid = :eid
          AND txn_date BETWEEN :s AND :e
        ORDER BY txn_date;
        """
    )
    return pd.read_sql(sql, engine, params={"eid": emp_id, "s": start, "e": end})

def post_adjustment(emp_id: int, date_: datetime.date, amount: float, kind: str, reason: str):
    sql = text(
        """
        INSERT INTO hr_salary_log (employeeid, txn_date, amount, txn_type, reason)
        VALUES (:eid, :d, :amt, :k, :rsn);
        """
    )
    with engine.begin() as conn:
        conn.execute(sql, {"eid": emp_id, "d": date_, "amt": amount, "k": kind, "rsn": reason})

# ───────────────────────────────────────────────
# UI
# ───────────────────────────────────────────────
st.set_page_config(page_title="Employee Salary", page_icon="💰", layout="wide")
st.title("💰 Monthly Payroll Review")

# ── Month picker
col_year, col_month = st.columns(2)
year  = col_year.number_input("Year", 2020, 2030, datetime.date.today().year, 1)
month = col_month.selectbox("Month", list(range(1,13)),
                            index=datetime.date.today().month-1,
                            format_func=lambda m: calendar.month_name[m])

start_d, end_d = month_range(year, month)
st.caption(f"Period: **{start_d:%Y‑%m‑%d} → {end_d:%Y‑%m‑%d}**")

# ── Fetch summary
df = get_month_summary(start_d, end_d)

# ── Metrics
tot_base = df["base"].sum()
tot_adj  = (df["bonus"] + df["extra"] - df["fine"]).sum()
tot_net  = df["net"].sum()

m1, m2, m3 = st.columns(3)
m1.metric("Total base", f"{tot_base:,.0f}")
m2.metric("Total adj.", f"{tot_adj:+,.0f}")
m3.metric("Total net", f"{tot_net:,.0f}")

# ── Add adjustment form
with st.expander("➕ Add adjustment"):
    with st.form("adj_form"):
        emp_name = st.selectbox("Employee", df["fullname"])
        emp_id   = int(df.loc[df["fullname"] == emp_name, "employeeid"].iloc[0])
        kind     = st.selectbox("Type", ["bonus", "extra", "fine"])
        amount   = st.number_input("Amount (positive)", 0.0, step=1000.0)
        reason   = st.text_area("Reason")
        date_    = st.date_input("Date", datetime.date.today())
        if st.form_submit_button("Submit"):
            if amount <= 0:
                st.error("Amount must be > 0")
            else:
                post_adjustment(emp_id, date_, amount, kind, reason)
                st.success("Adjustment added!")
                st.cache_data.clear()   # refresh
                st.experimental_rerun()

# ── Styling helper for table
def row_style(row):
    s = [""] * len(row)
    if row["Bonus"] > 0 or row["Extra"] > 0:
        for idx in [2,3]:  # Bonus/Extra cols
            if row.iloc[idx] > 0:
                s[idx] = "background-color:#d4edda;"  # green
    if row["Fine"] > 0:
        s[4] = "background-color:#f8d7da;"            # red
    if row["Net"] < row["Base"]:
        s[-1] = "background-color:#fff3cd;"           # yellow
    return s

display_df = df.rename(columns={
    "fullname":"Employee","base":"Base","bonus":"Bonus",
    "extra":"Extra","fine":"Fine","net":"Net"
})[["Employee","Base","Bonus","Extra","Fine","Net"]]

styled = (display_df.style
          .apply(row_style, axis=1)
          .format("{:,.0f}", subset=["Base","Bonus","Extra","Fine","Net"]))

st.dataframe(styled, use_container_width=True, hide_index=True)

# ── Audit trail per employee
st.subheader("Audit trail")
for _, r in df.iterrows():
    with st.expander(f"{r['fullname']} – details"):
        log = get_log(int(r["employeeid"]), start_d, end_d)
        if log.empty:
            st.write("No adjustments.")
        else:
            log_disp = log.rename(columns={
                "txn_date":"Date","txn_type":"Type","amount":"Amount","reason":"Reason"
            })
            log_disp["Amount"] = log_disp["Amount"].map("{:,.0f}".format)
            st.dataframe(log_disp, hide_index=True, use_container_width=True)
