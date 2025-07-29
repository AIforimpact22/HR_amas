import streamlit as st, datetime, calendar
import pandas as pd
from sqlalchemy import create_engine, text

# ─── engine (cached) ───────────────────────────────────────────
if "pg_engine" not in st.session_state:
    st.session_state.pg_engine = create_engine(
        st.secrets["neon"]["dsn"], pool_pre_ping=True, echo=False
    )
engine = st.session_state.pg_engine
SHIFT_HOURS = 8.5

# ─── helpers ───────────────────────────────────────────────────
def month_bounds(anchor: datetime.date):
    start = anchor.replace(day=1)
    end   = start.replace(day=calendar.monthrange(start.year, start.month)[1])
    return start, end

@st.cache_data(show_spinner=False)
def fetch_month(start_d, end_d, req_h):
    sql = text("""
    WITH adj AS (
        SELECT employeeid,
               SUM(CASE WHEN txn_type='bonus' THEN amount END) AS bonus,
               SUM(CASE WHEN txn_type='extra' THEN amount END) AS extra,
               SUM(CASE WHEN txn_type='fine'  THEN amount END) AS fine,
               STRING_AGG(reason, '; ' ORDER BY txn_date)      AS reasons
        FROM hr_salary_log
        WHERE txn_date BETWEEN :s AND :e
        GROUP BY employeeid),
    att AS (
        SELECT employeeid,
               SUM(EXTRACT(EPOCH FROM (COALESCE(clock_out,clock_in)-clock_in)))/3600 AS worked
        FROM hr_attendance
        WHERE punch_date BETWEEN :s AND :e
        GROUP BY employeeid)
    SELECT e.employeeid, e.fullname, e.basicsalary AS base,
           COALESCE(a.bonus,0) AS bonus, COALESCE(a.extra,0) AS extra,
           COALESCE(a.fine ,0) AS fine,
           COALESCE(att.worked,0)             AS worked,
           :req                               AS required,
           COALESCE(att.worked,0) - :req      AS delta,
           COALESCE(a.reasons,'')             AS reasons
    FROM hr_employee e
    LEFT JOIN adj a  USING (employeeid)
    LEFT JOIN att    USING (employeeid)
    ORDER BY e.fullname
    """)
    df = pd.read_sql(sql, engine, params={"s": start_d, "e": end_d, "req": req_h})
    df["net"] = df["base"] + df["bonus"] + df["extra"] - df["fine"]
    return df

def add_txn(eid,d,a,k,rsn):
    sql = text("INSERT INTO hr_salary_log (employeeid,txn_date,amount,txn_type,reason) "
               "VALUES (:eid,:d,:a,:k,:r)")
    with engine.begin() as con:
        con.execute(sql, {"eid":eid,"d":d,"a":a,"k":k,"r":rsn})

# ─── UI ────────────────────────────────────────────────────────
st.set_page_config("Employee Salary","💰",layout="wide")
st.title("💰 Employee Salary")

anchor = st.date_input("Payroll month", datetime.date.today().replace(day=1))
start_d, end_d = month_bounds(anchor)
days = (end_d - start_d).days + 1
req_hours = SHIFT_HOURS * (days - 4)   # 4 days off/month

st.caption(f"Period **{start_d:%Y‑%m‑%d} → {end_d:%Y‑%m‑%d}** • "
           f"Required h/emp = {req_hours:.1f}")

df = fetch_month(start_d, end_d, req_hours)

# ─── Table header ─────────────────────────────────────────────
widths = [2,1.4,1,1,1,1.4,1,1,1.2,2,1]   # wider Base & Net columns
for label, col in zip(
    ["Employee","Base","Bonus","Extra","Fine","Net",
     "Worked","Req.","Δ","Reasons",""],
    st.columns(widths)
):
    col.markdown(f"**{label}**")

# ─── Rows with inline editors ─────────────────────────────────
for _, r in df.iterrows():
    cols = st.columns(widths)
    eid = int(r["employeeid"])
    cols[0].markdown(r["fullname"])
    cols[1].markdown(f"{r['base']:,.0f}")
    cols[2].markdown(f"{r['bonus']:,.0f}")
    cols[3].markdown(f"{r['extra']:,.0f}")
    cols[4].markdown(f"{r['fine']:,.0f}")
    cols[5].markdown(f"{r['net']:,.0f}")

    ok = r["worked"] >= r["required"]; bg = "#d4edda" if ok else "#f8d7da"
    cols[6].markdown(f"<div style='background:{bg};padding:2px'>{r['worked']:.1f}</div>", unsafe_allow_html=True)
    cols[7].markdown(f"{r['required']:.1f}")
    cols[8].markdown(f"<div style='background:{bg};padding:2px'>{r['delta']:+.1f}</div>", unsafe_allow_html=True)
    cols[9].markdown(r["reasons"] or "—")

    if cols[-1].button("Edit", key=f"edit_{eid}"):
        st.session_state["edit_emp"] = eid

    if st.session_state.get("edit_emp") == eid:
        with st.form(f"form_{eid}"):
            k   = st.selectbox("Type", ["bonus","extra","fine"], key=f"k{eid}")
            a   = st.number_input("Amount", 0.0, step=1000.0, key=f"a{eid}")
            rsn = st.text_area("Reason", key=f"r{eid}")
            dt  = st.date_input("Date", datetime.date.today(), key=f"d{eid}")
            sv, cc = st.columns(2)
            if sv.form_submit_button("Save") and a>0:
                add_txn(eid, dt, a, k, rsn)
                st.session_state.pop("edit_emp", None); st.cache_data.clear(); st.rerun()
            if cc.form_submit_button("Cancel"):
                st.session_state.pop("edit_emp", None); st.rerun()

# ─── Totals row (bottom only) ─────────────────────────────────
tot = {
    "base":     df["base"].sum(),
    "bonus":    df["bonus"].sum(),
    "extra":    df["extra"].sum(),
    "fine":     df["fine"].sum(),
    "net":      df["net"].sum(),
    "worked":   df["worked"].sum(),
    "required": req_hours * len(df),
    "delta":    df["delta"].sum(),
}
row = st.columns(widths)
row[0].markdown("**Totals**")
row[1].markdown(f"**{tot['base']:,.0f}**")
row[2].markdown(f"**{tot['bonus']:,.0f}**")
row[3].markdown(f"**{tot['extra']:,.0f}**")
row[4].markdown(f"**{tot['fine']:,.0f}**")
row[5].markdown(f"**{tot['net']:,.0f}**")
bg_tot = "#d4edda" if tot["worked"] >= tot["required"] else "#f8d7da"
row[6].markdown(f"<div style='background:{bg_tot};padding:2px'><b>{tot['worked']:.1f}</b></div>", unsafe_allow_html=True)
row[7].markdown(f"**{tot['required']:.1f}**")
row[8].markdown(f"<div style='background:{bg_tot};padding:2px'><b>{tot['delta']:+.1f}</b></div>", unsafe_allow_html=True)
row[9].markdown("—")
