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
               COUNT(*) AS days_worked,
               SUM(EXTRACT(EPOCH FROM (COALESCE(clock_out,clock_in)-clock_in)))/3600 AS worked
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

def add_txn(eid:int, d:datetime.date, a:float, kind:str, reason:str):
    sql = text("INSERT INTO hr_salary_log (employeeid,txn_date,amount,txn_type,reason) "
               "VALUES (:eid,:d,:a,:k,:r)")
    with engine.begin() as con:
        con.execute(sql, {"eid":eid,"d":d,"a":a,"k":kind,"r":reason})

# ─── Page ───────────────────────────────────────────────────────
st.set_page_config(page_title="Employee Salary", page_icon="💰", layout="wide")
st.title("💰 Employee Salary")

# month picker
y_col, m_col = st.columns(2)
year  = y_col.number_input("Year", 2020, 2030, datetime.date.today().year, 1)
month = m_col.selectbox("Month", range(1,13),
                        index=datetime.date.today().month-1,
                        format_func=lambda m: calendar.month_name[m])

start_d, end_d = month_range(year, month)
st.caption(f"Period: **{start_d:%Y-%m-%d} → {end_d:%Y-%m-%d}**")

df = fetch_month(start_d, end_d)

# summary metrics
tot_base = df["base"].sum()
tot_adj  = (df["bonus"]+df["extra"]-df["fine"]).sum()
tot_net  = df["net"].sum()
top1, top2, top3 = st.columns(3)
top1.metric("Total base", f"{tot_base:,.0f}")
top2.metric("Total adj.", f"{tot_adj:+,.0f}")
top3.metric("Total net",  f"{tot_net:,.0f}")

st.divider()

# header
header_cols = st.columns([2,1,1,1,1,1,1,1,1.2,2,1])
for h, c in zip(
    ["Employee","Base","Bonus","Extra","Fine","Net",
     "Worked","Req.","Δ","Reasons",""], header_cols
):
    c.markdown(f"**{h}**")

# data rows
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
    cols[6].markdown(f"<div style='background:{bg};padding:2px'>{r['worked']:.1f}</div>", unsafe_allow_html=True)
    cols[7].markdown(f"{r['required']:.1f}")
    cols[8].markdown(f"<div style='background:{bg};padding:2px'>{r['delta']:+.1f}</div>", unsafe_allow_html=True)
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
            col_sv, col_cn = st.columns(2)
            save   = col_sv.form_submit_button("Save")
            cancel = col_cn.form_submit_button("Cancel")
            if save and amt>0:
                add_txn(eid, date_, amt, kind, reason)
                st.success("Saved.")
                st.session_state.pop("edit_emp", None)
                st.cache_data.clear(); st.rerun()
            elif cancel:
                st.session_state.pop("edit_emp", None)
                st.rerun()

# ─── totals row ────────────────────────────────────────────────
tot_worked   = df["worked"].sum()
tot_required = df["required"].sum()
tot_delta    = df["delta"].sum()

tot_row = st.columns([2,1,1,1,1,1,1,1,1.2,2,1])
tot_row[0].markdown("**Totals**")
tot_row[1].markdown(f"**{tot_base:,.0f}**")
tot_row[2].markdown(f"**{df['bonus'].sum():,.0f}**")
tot_row[3].markdown(f"**{df['extra'].sum():,.0f}**")
tot_row[4].markdown(f"**{df['fine'].sum():,.0f}**")
tot_row[5].markdown(f"**{tot_net:,.0f}**")

bg_tot = "#d4edda" if tot_worked >= tot_required else "#f8d7da"
tot_row[6].markdown(f"<div style='background:{bg_tot};padding:2px'><b>{tot_worked:.1f}</b></div>", unsafe_allow_html=True)
tot_row[7].markdown(f"**{tot_required:.1f}**")
tot_row[8].markdown(f"<div style='background:{bg_tot};padding:2px'><b>{tot_delta:+.1f}</b></div>", unsafe_allow_html=True)
tot_row[9].markdown("—")
