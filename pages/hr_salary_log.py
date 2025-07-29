import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
import datetime
import calendar

# ───────────────────────────────────────────────
# Database engine (cached)
# ───────────────────────────────────────────────
if "pg_engine" not in st.session_state:
    st.session_state.pg_engine = create_engine(
        st.secrets["neon"]["dsn"], pool_pre_ping=True, echo=False
    )
engine = st.session_state.pg_engine

# ───────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────
def month_range(year: int, month: int):
    start = datetime.date(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    end = datetime.date(year, month, last_day)
    return start, end

@st.cache_data(show_spinner=False)
def fetch_month_summary(start: datetime.date, end: datetime.date) -> pd.DataFrame:
    sql = text(
        """
        SELECT e.employeeid,
               e.fullname,
               e.basicsalary                                                 AS base,
               COALESCE(SUM(CASE WHEN l.txn_type = 'bonus' THEN l.amount END),0) AS bonus,
               COALESCE(SUM(CASE WHEN l.txn_type = 'extra' THEN l.amount END),0) AS extra,
               COALESCE(SUM(CASE WHEN l.txn_type = 'fine'  THEN l.amount END),0) AS fine
        FROM hr_employee e
        LEFT JOIN hr_salary_log l
               ON l.employeeid = e.employeeid
              AND l.txn_date BETWEEN :s AND :e
        GROUP BY e.employeeid, e.fullname, e.basicsalary
        ORDER BY e.fullname
        """
    )
    df = pd.read_sql(sql, engine, params={"s": start, "e": end})
    df["net"] = df["base"] + df["bonus"] + df["extra"] - df["fine"]
    return df

def fetch_log(emp_id: int, start: datetime.date, end: datetime.date) -> pd.DataFrame:
    sql = text(
        """
        SELECT log_id,
               txn_date,
               txn_type,
               amount,
               reason,
               created_at
        FROM hr_salary_log
        WHERE employeeid = :eid
          AND txn_date BETWEEN :s AND :e
        ORDER BY txn_date
        """
    )
    return pd.read_sql(sql, engine, params={"eid": emp_id, "s": start, "e": end})

def add_adjustment(emp_id: int, date_: datetime.date, amount: float, txn_type: str, reason: str):
    sql = text(
        """
        INSERT INTO hr_salary_log
              (employeeid, txn_date, amount, txn_type, reason)
        VALUES (:eid, :d, :amt, :typ, :rsn)
        """
    )
    with engine.begin() as conn:
        conn.execute(sql, {"eid": emp_id, "d": date_, "amt": amount, "typ": txn_type, "rsn": reason})

# ───────────────────────────────────────────────
# UI
# ───────────────────────────────────────────────
st.set_page_config("Monthly Payroll", "💰", layout="wide")
st.title("💰 Monthly Payroll Review")

# Month picker
yy, mm = st.columns(2)
year  = yy.number_input("Year", min_value=2020, max_value=2030, value=datetime.date.today().year, step=1)
month = mm.selectbox("Month", list(range(1,13)), index=datetime.date.today().month-1, format_func=lambda m: calendar.month_name[m])

start_d, end_d = month_range(year, month)
st.caption(f"Period: **{start_d:%Y‑%m‑%d} → {end_d:%Y‑%m‑%d}**")

# Fetch data
df = fetch_month_summary(start_d, end_d)

# Top metrics
tot_base   = df["base"].sum()
tot_adj    = (df["bonus"] + df["extra"] - df["fine"]).sum()
tot_net    = df["net"].sum()

m1, m2, m3 = st.columns(3)
m1.metric("Total base", f"{tot_base:,.0f}")
m2.metric("Total adj. (bonus+extra‑fine)", f"{tot_adj:+,.0f}")
m3.metric("Total net", f"{tot_net:,.0f}")

# Adjustment form
with st.expander("➕ Add adjustment"):
    with st.form("add_adj"):
        emp_name = st.selectbox("Employee", df["fullname"])
        emp_id   = int(df[df["fullname"] == emp_name]["employeeid"].iloc[0])
        txn_type = st.selectbox("Type", ["bonus", "extra", "fine"])
        amount   = st.number_input("Amount", min_value=0.0, step=1000.0)
        reason   = st.text_area("Reason")
        date_    = st.date_input("Date", datetime.date.today())
        if st.form_submit_button("Submit"):
            if amount <= 0:
                st.error("Amount must be positive.")
            else:
                add_adjustment(emp_id, date_, amount, txn_type, reason)
                st.success("Adjustment added. Refreshing data…")
                st.cache_data.clear()  # invalidate month cache
                st.experimental_rerun()

# Colour rules for table
def style_tbl(tbl):
    def _row(r):
        style = [""]*len(r)
        if r["bonus"] > 0: style[3] = "background-color:#d4edda;"  # green
        if r["extra"] > 0: style[4] = "background-color:#d4edda;"
        if r["fine"]  > 0: style[5] = "background-color:#f8d7da;"  # red
        if r["net"] < r["base"]:
            style[-1] = "background-color:#fff3cd;"                # yellow
        return style
    return tbl.apply(_row, axis=1)

tbl_show = df[["fullname","base","bonus","extra","fine","net"]].rename(
    columns={"fullname":"Employee","base":"Base","bonus":"Bonus","extra":"Extra","fine":"Fine","net":"Net"}
)
styled = tbl_show.style.apply(style_tbl, axis=1).format("{:,.0f}", subset=["Base","Bonus","Extra","Fine","Net"])
st.dataframe(styled, use_container_width=True, hide_index=True)

# Per‑employee logs with expanders
st.subheader("Audit trail")
for _, r in df.iterrows():
    with st.expander(f"{r['fullname']} – details"):
        log = fetch_log(int(r["employeeid"]), start_d, end_d)
        if log.empty:
            st.write("No adjustments.")
        else:
            log_show = log[["txn_date","txn_type","amount","reason"]].rename(
                columns={"txn_date":"Date","txn_type":"Type","amount":"Amount","reason":"Reason"}
            )
            log_show["Amount"] = log_show["Amount"].map("{:,.0f}".format)
            log_show = log_show.sort_values("Date")
            st.dataframe(log_show, hide_index=True, use_container_width=True)
