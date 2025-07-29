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
def month_bounds(anchor: datetime.date):
    """Return first and last date of the anchor month."""
    start = anchor.replace(day=1)
    last  = calendar.monthrange(start.year, start.month)[1]
    end   = start.replace(day=last)
    return start, end

@st.cache_data(show_spinner=False)
def fetch_month(start_d: datetime.date, end_d: datetime.date,
                req_hours: float) -> pd.DataFrame:
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
               SUM(EXTRACT(EPOCH FROM (COALESCE(clock_out,clock_in)-clock_in)))/3600 AS worked
        FROM hr_attendance
        WHERE punch_date BETWEEN :s AND :e
        GROUP BY employeeid
    )
    SELECT e.employeeid,
           e.fullname,
           e.basicsalary                      AS base,
           COALESCE(a.bonus ,0)               AS bonus,
           COALESCE(a.extra ,0)               AS extra,
           COALESCE(a.fine  ,0)               AS fine,
           COALESCE(att.worked,0)             AS worked,
           :req                               AS required,
           COALESCE(att.worked,0) - :req      AS delta,
           COALESCE(a.reasons,'')             AS reasons
    FROM hr_employee e
    LEFT JOIN adj a   USING (employeeid)
    LEFT JOIN att att USING (employeeid)
    ORDER BY e.fullname
    """)
    df = pd.read_sql(sql, engine,
                     params={"s": start_d, "e": end_d, "req": req_hours})
    df["net"] = df["base"] + df["bonus"] + df["extra"] - df["fine"]
    return df

def add_txn(eid:int, d:datetime.date, amt:float, kind:str, reason:str):
    sql = text("INSERT INTO hr_salary_log (employeeid,txn_date,amount,txn_type,reason) "
               "VALUES (:eid,:d,:a,:k,:r)")
    with engine.begin() as con:
        con.execute(sql, {"eid":eid,"d":d,"a":amt,"k":kind,"r":reason})

# ─── Page ───────────────────────────────────────────────────────
st.set_page_config(page_title="Employee Salary", page_icon="💰", layout="wide")
st.title("💰 Employee Salary")

# Single month picker (pick any day inside month)
anchor_date = st.date_input("Payroll month", datetime.date.today().replace(day=1))
start_d, end_d = month_bounds(anchor_date)
days_in_month  = (end_d - start_d).days + 1
req_hours_each = SHIFT_HOURS * (days_in_month - 4)   # 4 leave days always

st.caption(f"Period **{start_d:%Y‑%m‑%d} → {end_d:%Y‑%m‑%d}**, "
           f"required hours/employee = {req_hours_each:.1f}")

df = fetch_month(start_d, end_d, req_hours_each)

# summary metrics
tot_base = df["base"].sum()
tot_adj  = (df["bonus"]+df["extra"]-df["fine"]).sum()
tot_net  = df["net"].sum()
mx1,mx2,mx3 = st.columns(3)
mx1.metric("Total base", f"{tot_base:,.0f}")
mx2.metric("Total adj.", f"{tot_adj:+,.0f}")
mx3.metric("Total net",  f"{tot_net:,.0f}")

st.divider()

# header
for lbl,col in zip(
    ["Employee","Base","Bonus","Extra","Fine","Net",
     "Worked","Req.","Δ","Reasons",""],
    st.columns([2,1,1,1,1,1,1,1,1.2,2,1])
):
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

    if st.session_state.get("edit_emp") == eid:
        with st.form(f"form_{eid}"):
            kind   = st.selectbox("Type", ["bonus","extra","fine"], key=f"k{eid}")
            amt    = st.number_input("Amount", 0.0, step=1000.0, key=f"a{eid}")
            reason = st.text_area("Reason", key=f"r{eid}")
            date_  = st.date_input("Date", datetime.date.today(), key=f"d{eid}")
            btn_s, btn_c = st.columns(2)
            save   = btn_s.form_submit_button("Save")
            cancel = btn_c.form_submit_button("Cancel")
            if save and amt>0:
                add_txn(eid, date_, amt, kind, reason)
                st.success("Saved.")
                st.session_state.pop("edit_emp", None)
                st.cache_data.clear(); st.rerun()
            elif cancel:
                st.session_state.pop("edit_emp", None)
                st.rerun()

# totals row
totals = {
    "bonus": df["bonus"].sum(),
    "extra": df["extra"].sum(),
    "fine":  df["fine"].sum(),
    "worked": df["worked"].sum(),
    "required": req_hours_each * len(df),
    "delta": df["delta"].sum(),
    "net": tot_net
}
row = st.columns([2,1,1,1,1,1,1,1,1.2,2,1])
row[0].markdown("**Totals**")
row[1].markdown(f"**{tot_base:,.0f}**")
row[2].markdown(f"**{totals['bonus']:,.0f}**")
row[3].markdown(f"**{totals['extra']:,.0f}**")
row[4].markdown(f"**{totals['fine']:,.0f}**")
row[5].markdown(f"**{totals['net']:,.0f}**")

bg_tot = "#d4edda" if totals["worked"] >= totals["required"] else "#f8d7da"
row[6].markdown(f"<div style='background:{bg_tot};padding:2px'><b>{totals['worked']:.1f}</b></div>", unsafe_allow_html=True)
row[7].markdown(f"**{totals['required']:.1f}**")
row[8].markdown(f"<div style='background:{bg_tot};padding:2px'><b>{totals['delta']:+.1f}</b></div>", unsafe_allow_html=True)
row[9].markdown("—")
