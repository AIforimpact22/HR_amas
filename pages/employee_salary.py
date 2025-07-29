import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
import datetime, calendar

# ─── DB engine (cached) ────────────────────────────────────────────
if "pg_engine" not in st.session_state:
    st.session_state.pg_engine = create_engine(
        st.secrets["neon"]["dsn"], pool_pre_ping=True, echo=False
    )
engine = st.session_state.pg_engine

SHIFT_HOURS = 8.5

# ─── Helpers ───────────────────────────────────────────────────────
def month_range(y: int, m: int):
    start = datetime.date(y, m, 1)
    end   = datetime.date(y, m, calendar.monthrange(y, m)[1])
    return start, end

@st.cache_data(show_spinner=False)
def fetch_month(start: datetime.date, end: datetime.date) -> pd.DataFrame:
    sql = text(
    """
    WITH adj AS (
        SELECT employeeid,
               SUM(CASE WHEN txn_type='bonus' THEN amount END)  AS bonus,
               SUM(CASE WHEN txn_type='extra' THEN amount END)  AS extra,
               SUM(CASE WHEN txn_type='fine'  THEN amount END)  AS fine,
               STRING_AGG(reason, '; ' ORDER BY txn_date)       AS reasons
        FROM hr_salary_log
        WHERE txn_date BETWEEN :s AND :e
        GROUP BY employeeid
    ),
    att AS (
        SELECT employeeid,
               COUNT(*)                                               AS days_worked,
               SUM(EXTRACT(EPOCH FROM (COALESCE(clock_out, clock_in) - clock_in)))/3600
                                                                    AS worked
        FROM hr_attendance
        WHERE punch_date BETWEEN :s AND :e
        GROUP BY employeeid
    )
    SELECT e.employeeid,
           e.fullname,
           e.basicsalary                                     AS base,
           COALESCE(a.bonus ,0)                              AS bonus,
           COALESCE(a.extra ,0)                              AS extra,
           COALESCE(a.fine  ,0)                              AS fine,
           COALESCE(att.worked,0)                            AS worked,
           COALESCE(att.days_worked,0)*:shift                AS required,
           COALESCE(att.worked,0) - COALESCE(att.days_worked,0)*:shift AS delta,
           COALESCE(a.reasons,'')                            AS reasons
    FROM hr_employee e
    LEFT JOIN adj  a   USING (employeeid)
    LEFT JOIN att  att USING (employeeid)
    ORDER BY e.fullname
    """)
    df = pd.read_sql(sql, engine, params={"s": start, "e": end, "shift": SHIFT_HOURS})
    df["bonus"].fillna(0, inplace=True)
    df["extra"].fillna(0, inplace=True)
    df["fine"].fillna(0, inplace=True)
    df["net"] = df["base"] + df["bonus"] + df["extra"] - df["fine"]
    return df

def add_txn(emp_id:int, date_:datetime.date, amt:float, kind:str, reason:str):
    sql = text("INSERT INTO hr_salary_log (employeeid, txn_date, amount, txn_type, reason) "
               "VALUES (:eid,:d,:a,:k,:r)")
    with engine.begin() as con:
        con.execute(sql, {"eid":emp_id,"d":date_,"a":amt,"k":kind,"r":reason})

# ─── UI ────────────────────────────────────────────────────────────
st.set_page_config("Employee Salary", "💰", layout="wide")
st.title("💰 Employee Salary")

# Month picker
c_year, c_month = st.columns(2)
year  = c_year.number_input("Year", 2020, 2030, value=datetime.date.today().year, step=1)
month = c_month.selectbox("Month", list(range(1,13)),
                          index=datetime.date.today().month-1,
                          format_func=lambda m: calendar.month_name[m])

start_d, end_d = month_range(year, month)
st.caption(f"Period: **{start_d:%Y‑%m‑%d} → {end_d:%Y‑%m‑%d}**")

df = fetch_month(start_d, end_d)

# Totals
t_base = df["base"].sum()
t_adj  = (df["bonus"]+df["extra"]-df["fine"]).sum()
t_net  = df["net"].sum()
m1,m2,m3 = st.columns(3)
m1.metric("Total base", f"{t_base:,.0f}")
m2.metric("Total adj.", f"{t_adj:+,.0f}")
m3.metric("Total net",  f"{t_net:,.0f}")

st.divider()

# Grid header
header = st.columns([2,1,1,1,1,1,1,1,2,1])
headers = ["Employee","Base","Bonus","Extra","Fine","Net",
           "Worked","Required","Δ Hr","Reasons",""]
for col, h in zip(header, headers): col.markdown(f"**{h}**")

# Per‑row display & editor
for _, r in df.iterrows():
    cols = st.columns([2,1,1,1,1,1,1,1,1.2,2,1])
    cols[0].markdown(r["fullname"])
    cols[1].markdown(f"{r['base']:,.0f}")
    cols[2].markdown(f"{r['bonus']:,.0f}")
    cols[3].markdown(f"{r['extra']:,.0f}")
    cols[4].markdown(f"{r['fine']:,.0f}")
    cols[5].markdown(f"{r['net']:,.0f}")

    # colour for worked / delta
    worked_colour   = "#d4edda" if r["worked"] >= r["required"] else "#f8d7da"
    delta_colour    = worked_colour
    cols[6].markdown(f"<div style='background:{worked_colour};padding:2px'>{r['worked']:.1f}</div>",
                     unsafe_allow_html=True)
    cols[7].markdown(f"{r['required']:.1f}")
    cols[8].markdown(f"<div style='background:{delta_colour};padding:2px'>{r['delta']:+.1f}</div>",
                     unsafe_allow_html=True)
    cols[9].markdown(r["reasons"] if r["reasons"] else "—")

    key_edit = f"edit_{r['employeeid']}"
    if cols[-1].button("Edit", key=key_edit):
        st.session_state["edit_emp"] = r["employeeid"]

    # Inline form
    if st.session_state.get("edit_emp") == r["employeeid"]:
        with st.form(f"form_{r['employeeid']}"):
            kind = st.selectbox("Type", ["bonus","extra","fine"], key=f"k{r['employeeid']}")
            amt  = st.number_input("Amount", min_value=0.0, step=1000.0, key=f"a{r['employeeid']}")
            reason = st.text_area("Reason", key=f"rs{r['employeeid']}")
            date_  = st.date_input("Date", datetime.date.today(), key=f"d{r['employeeid']}")
            if st.form_submit_button("Save"):
                if amt<=0:
                    st.error("Amount must be > 0")
                else:
                    add_txn(int(r["employeeid"]), date_, amt, kind, reason)
                    st.success("Saved.")
                    st.session_state.pop("edit_emp", None)
                    st.cache_data.clear()
                    st.experimental_rerun()
