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
        GROUP BY employeeid
    ),
    att AS (
        SELECT employeeid,
               SUM(EXTRACT(EPOCH FROM (COALESCE(clock_out,clock_in)-clock_in)))/3600 AS worked
        FROM hr_attendance
        WHERE punch_date BETWEEN :s AND :e
        GROUP BY employeeid
    ),
    base AS (
        SELECT DISTINCT ON (employeeid)
               employeeid, salary
        FROM   hr_salary_history
        WHERE  effective_from <= :s
          AND  COALESCE(effective_to, DATE '9999-12-31') >= :s
        ORDER  BY employeeid, effective_from DESC
    )
    SELECT  emp.employeeid,
            emp.fullname,
            COALESCE(base.salary, 0)                AS base,
            COALESCE(adj.bonus ,0)                  AS bonus,
            COALESCE(adj.extra ,0)                  AS extra,
            COALESCE(adj.fine  ,0)                  AS fine,
            COALESCE(att.worked,0)                  AS worked,
            :req                                    AS required,
            COALESCE(att.worked,0) - :req           AS delta,
            COALESCE(adj.reasons,'')                AS reasons
    FROM hr_employee emp
    LEFT JOIN base ON base.employeeid = emp.employeeid
    LEFT JOIN adj  ON adj.employeeid  = emp.employeeid
    LEFT JOIN att  ON att.employeeid  = emp.employeeid
    ORDER BY emp.fullname;
    """)
    df = pd.read_sql(sql, engine,
                     params={"s": start_d, "e": end_d, "req": req_h})
    df["net"] = df["base"] + df["bonus"] + df["extra"] - df["fine"]
    return df

def close_current_and_insert_raise(eid:int, new_salary:float,
                                   eff_from:datetime.date, reason:str):
    """Close previous salary row and insert the new one inside a TX."""
    close_date = eff_from - datetime.timedelta(days=1)
    sql_close = text("""
        UPDATE hr_salary_history
           SET effective_to = :close
         WHERE employeeid   = :eid
           AND effective_to IS NULL
    """)
    sql_new  = text("""
        INSERT INTO hr_salary_history
              (employeeid, salary, effective_from, reason)
        VALUES (:eid, :sal, :eff, :rsn)
    """)
    with engine.begin() as con:
        con.execute(sql_close, {"close": close_date, "eid": eid})
        con.execute(sql_new,
                    {"eid": eid, "sal": new_salary, "eff": eff_from, "rsn": reason})

# ────────────────────── UI ───────────────────────────────────────
st.set_page_config(page_title="Employee Salary", page_icon="💰", layout="wide")
tab_sum, tab_raise = st.tabs(["📊 Monthly Summary", "➕ Raise / Cut"])

# keep shared anchor in session_state
if "pay_anchor" not in st.session_state:
    st.session_state.pay_anchor = datetime.date.today().replace(day=1)

# ================================================================
# TAB 1  ▸ Monthly Summary (restored “Edit Adj.” per row)
# ================================================================
with tab_sum:
    anchor = st.date_input("Payroll month", st.session_state.pay_anchor,
                           key="anchor_sum")
    st.session_state.pay_anchor = anchor

    start_d, end_d = month_bounds(anchor)
    days = (end_d - start_d).days + 1
    req_hours = SHIFT_HOURS * (days - 4)

    st.caption(f"Period **{start_d:%Y‑%m‑%d} → {end_d:%Y‑%m‑%d}** • "
               f"Required h/emp = {req_hours:.1f}")

    df = fetch_month(start_d, end_d, req_hours)

    # table header  (note: last column = Edit Adj.)
    widths = [2,1.4,1,1,1,1.4,1,1,1.2,2,1]
    for lbl,col in zip(
        ["Employee","Base","Bonus","Extra","Fine","Net",
         "Worked","Req.","Δ","Reasons",""],
        st.columns(widths)):
        col.markdown(f"**{lbl}**")

    # -------- rows --------
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

        # restored Edit button
        if cols[-1].button("✏️", key=f"edit_adj_{eid}", help="Edit bonus / extra / fine"):
            st.session_state["edit_emp"] = eid

        # inline form for bonus / extra / fine
        if st.session_state.get("edit_emp") == eid:
            with st.form(f"adj_form_{eid}"):
                kind  = st.selectbox("Type", ["bonus","extra","fine"], key=f"k{eid}")
                amt   = st.number_input("Amount", 0.0, step=1000.0, key=f"a{eid}")
                rsn   = st.text_area("Reason", key=f"r{eid}")
                dt    = st.date_input("Date", datetime.date.today(), key=f"d{eid}")
                sv, cc = st.columns(2)
                if sv.form_submit_button("Save") and amt>0:
                    add_txn(eid, dt, amt, kind, rsn)
                    st.session_state.pop("edit_emp", None)
                    st.cache_data.clear(); st.rerun()
                if cc.form_submit_button("Cancel"):
                    st.session_state.pop("edit_emp", None); st.rerun()

    # totals row
    tot = {
        "base": df["base"].sum(), "bonus": df["bonus"].sum(),
        "extra": df["extra"].sum(), "fine": df["fine"].sum(),
        "net": df["net"].sum(), "worked": df["worked"].sum(),
        "required": req_hours * len(df), "delta": df["delta"].sum()
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

# ─── Tab 2 : Raise / Cut ───────────────────────────────────────
with tab_raise:
    st.caption("Create a new base‑salary record.  "
               "The effective date is always set to the **first of the month** you pick.")

    emp_df = pd.read_sql("SELECT employeeid, fullname FROM hr_employee ORDER BY fullname", engine)
    if emp_df.empty:
        st.warning("No employees in database.")
        st.stop()

    with st.form("raise_form"):
        emp_name = st.selectbox("Employee", emp_df["fullname"])
        emp_id   = int(emp_df.loc[emp_df["fullname"]==emp_name, "employeeid"].iloc[0])

        new_sal  = st.number_input("New monthly salary", min_value=0.0, step=100_000.0)
        eff_month = st.date_input("Effective month", anchor, help="Choose any day; will snap to 1st")
        # snap to first‑of‑month
        eff_first = eff_month.replace(day=1)

        reason   = st.text_area("Reason (optional)")

        if st.form_submit_button("Save raise / cut"):
            if new_sal <= 0:
                st.error("Salary must be > 0")
            else:
                close_current_and_insert_raise(emp_id, new_sal, eff_first, reason.strip())
                st.success(f"Saved. New base salary starts {eff_first:%Y‑%m‑%d}")
                st.cache_data.clear(); st.rerun()
