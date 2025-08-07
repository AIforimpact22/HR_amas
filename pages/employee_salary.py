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

def add_txn(eid: int, dt: datetime.date, amt: float, kind: str, rsn: str):
    sql = text("""
        INSERT INTO hr_salary_log (employeeid, txn_date, amount, txn_type, reason)
        VALUES (:eid, :dt, :amt, :kind, :rsn)
    """)
    with engine.begin() as con:
        con.execute(sql, {"eid": eid, "dt": dt, "amt": amt, "kind": kind, "rsn": rsn})

# ────────────────────── UI ───────────────────────────────────────
st.set_page_config(page_title="Employee Salary", page_icon="💰", layout="wide")
tab_sum, tab_raise, tab_push = st.tabs(["📊 Monthly Summary", "➕ Raise / Cut", "📤 Push to Finance"])

# keep shared anchor in session_state
if "pay_anchor" not in st.session_state:
    st.session_state.pay_anchor = datetime.date.today().replace(day=1)

# ================================================================
# TAB 1  ▸ Monthly Summary  (salary-only, nicer UI)
# ================================================================
with tab_sum:
    # ── choose month (no day component) ──────────────────────────
    # build a list of "first-of-month" dates, newest first
    months = pd.date_range(
        end=datetime.date.today().replace(day=1),
        periods=24,           # 2 years back; tweak as you like
        freq="MS"
    ).to_pydatetime()[::-1]   # newest → oldest

    anchor = st.selectbox(
        "Payroll month",
        months,
        format_func=lambda d: d.strftime("%B %Y")   # e.g. "August 2025"
    )
    st.session_state.pay_anchor = anchor            # keep in session

    # ── period info & data fetch ────────────────────────────────
    start_d, end_d = month_bounds(anchor)
    days      = (end_d - start_d).days + 1
    req_hours = SHIFT_HOURS * (days - 4)            # still needed elsewhere
    st.caption(f"Period **{start_d:%Y-%m-%d} → {end_d:%Y-%m-%d}**")

    df = fetch_month(start_d, end_d, req_hours)

    # ── tiny formatting helpers ─────────────────────────────────
    fmt  = lambda n: f"{n:,.0f}"         # thousands‐sep int
    cell = lambda v, bg="#ffffff": (     # wrap any value in a styled <div>
        f"<div style='background:{bg};padding:4px'>{v}</div>"
    )

    # ── table header (attendance cols removed) ──────────────────
    widths = [2, 1.4, 1, 1, 1, 1.4, 2, 1]           # 8 cols
    for lbl, col in zip(
        ["Employee", "Base", "Bonus", "Extra", "Fine", "Net", "Reasons", ""],
        st.columns(widths)
    ):
        col.markdown(f"**{lbl}**")

    # ── data rows with zebra striping ───────────────────────────
    even_bg = "#f7f9fc"     # light gray-blue
    odd_bg  = "#ffffff"

    for i, r in df.iterrows():
        row_bg = even_bg if i % 2 == 0 else odd_bg
        cols   = st.columns(widths)
        eid    = int(r["employeeid"])

        cols[0].markdown(cell(r["fullname"], row_bg), unsafe_allow_html=True)
        cols[1].markdown(cell(fmt(r["base" ]), row_bg), unsafe_allow_html=True)
        cols[2].markdown(cell(fmt(r["bonus"]), row_bg), unsafe_allow_html=True)
        cols[3].markdown(cell(fmt(r["extra"]), row_bg), unsafe_allow_html=True)
        cols[4].markdown(cell(fmt(r["fine" ]), row_bg), unsafe_allow_html=True)
        cols[5].markdown(cell(fmt(r["net"  ]), row_bg), unsafe_allow_html=True)
        cols[6].markdown(cell(r["reasons"] or "—", row_bg), unsafe_allow_html=True)

        # edit-adjustment button (unchanged)
        if cols[-1].button("✏️", key=f"edit_adj_{eid}", help="Edit bonus / extra / fine"):
            st.session_state["edit_emp"] = eid

        # inline adjustment form (unchanged)
        if st.session_state.get("edit_emp") == eid:
            with st.form(f"adj_form_{eid}"):
                kind = st.selectbox("Type", ["bonus", "extra", "fine"], key=f"k{eid}")
                amt  = st.number_input("Amount", 0.0, step=1000.0, key=f"a{eid}")
                rsn  = st.text_area("Reason", key=f"r{eid}")
                dt   = st.date_input("Date", datetime.date.today(), key=f"d{eid}")
                sv, cc = st.columns(2)
                if sv.form_submit_button("Save") and amt > 0:
                    add_txn(eid, dt, amt, kind, rsn)
                    st.session_state.pop("edit_emp", None)
                    st.cache_data.clear(); st.rerun()
                if cc.form_submit_button("Cancel"):
                    st.session_state.pop("edit_emp", None); st.rerun()

    # ── totals row (highlighted) ────────────────────────────────
    tot_bg = "#e6f4f1"   # soft teal (matches your accent #1ABC9C)
    tot = {
        "base":  df["base"].sum(),
        "bonus": df["bonus"].sum(),
        "extra": df["extra"].sum(),
        "fine":  df["fine"].sum(),
        "net":   df["net"].sum(),
    }
    row = st.columns(widths)
    row[0].markdown(cell("<b>Totals</b>", tot_bg), unsafe_allow_html=True)
    row[1].markdown(cell(f"<b>{fmt(tot['base'])}</b>",  tot_bg), unsafe_allow_html=True)
    row[2].markdown(cell(f"<b>{fmt(tot['bonus'])}</b>", tot_bg), unsafe_allow_html=True)
    row[3].markdown(cell(f"<b>{fmt(tot['extra'])}</b>", tot_bg), unsafe_allow_html=True)
    row[4].markdown(cell(f"<b>{fmt(tot['fine'])}</b>",  tot_bg), unsafe_allow_html=True)
    row[5].markdown(cell(f"<b>{fmt(tot['net'])}</b>",   tot_bg), unsafe_allow_html=True)
    row[6].markdown(cell("—", tot_bg), unsafe_allow_html=True)


# ================================================================
# TAB 2  ▸ Raise / Cut  (streamlined UI, bug-fixed)
# ================================================================
with tab_raise:
    st.caption(
        "Create a new base-salary record.  "
        "The effective date is always set to the **first of the month** you pick."
    )

    # ── fetch employee list ──────────────────────────────────────
    emp_df = pd.read_sql(
        "SELECT employeeid, fullname FROM hr_employee ORDER BY fullname", engine
    )
    if emp_df.empty:
        st.warning("No employees in database.")
        st.stop()

    with st.form("raise_form", clear_on_submit=False):
        # ── choose employee ──────────────────────────────────────
        emp_name = st.selectbox("Employee", emp_df["fullname"])
        emp_id   = int(emp_df.loc[emp_df["fullname"] == emp_name, "employeeid"].iloc[0])

        # ── look up current salary ───────────────────────────────
        cur_sql = text("""
            SELECT salary, effective_from
              FROM hr_salary_history
             WHERE employeeid = :eid
               AND effective_from <= CURRENT_DATE
               AND (effective_to IS NULL OR effective_to >= CURRENT_DATE)
             ORDER BY effective_from DESC
             LIMIT 1
        """)
        with engine.connect() as con:
            cur_row = con.execute(cur_sql, {"eid": emp_id}).fetchone()

        cur_sal  = float(cur_row.salary) if cur_row else 0.0
        cur_from = cur_row.effective_from if cur_row else None

        # ── info card with current salary ────────────────────────
        card_bg = "#1ABC9C20"   # teal @20 % opacity
        cur_since = f"(since {cur_from:%Y-%m-%d})" if cur_from else ""
        st.markdown(
            f"""
            <div style="background:{card_bg};padding:10px;border-radius:6px;margin-bottom:8px">
                <b>Current salary:</b> {cur_sal:,.0f} &nbsp;&nbsp;
                <span style="font-size:0.9em">{cur_since}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # ── side-by-side inputs ─────────────────────────────────
        c1, c2 = st.columns(2)
        with c1:
            new_sal = st.number_input(
                "New monthly salary",
                min_value=0.0,
                step=50_000.0,
                value=cur_sal,
            )
        with c2:
            # month select (24 months back, newest first)
            months = pd.date_range(
                end=datetime.date.today().replace(day=1),
                periods=24,
                freq="MS",
            ).to_pydatetime()[::-1]
            eff_month = st.selectbox(
                "Effective month",
                months,
                format_func=lambda d: d.strftime("%B %Y"),
            )
            eff_first = eff_month.replace(day=1)   # snap to first-of-month

        reason = st.text_area("Reason (optional)", placeholder="Promotion, adjustment…")

        # ── live delta badge ─────────────────────────────────────
        delta = new_sal - cur_sal
        if delta != 0:
            arrow = "▲" if delta > 0 else "▼"
            color = "#28a745" if delta > 0 else "#dc3545"   # green / red
            st.markdown(
                f"<span style='background:{color};color:#fff;padding:4px 8px;border-radius:4px'>"
                f"{arrow} {abs(delta):,.0f}</span>",
                unsafe_allow_html=True,
            )

        # ── save button ─────────────────────────────────────────
        if st.form_submit_button("Save raise / cut", type="primary"):
            if new_sal <= 0:
                st.error("Salary must be > 0")
            elif new_sal == cur_sal:
                st.warning("New salary is identical to current salary — nothing saved.")
            else:
                close_current_and_insert_raise(
                    emp_id, new_sal, eff_first, reason.strip()
                )
                st.success(f"Saved! New base salary starts {eff_first:%Y-%m-%d}")
                st.cache_data.clear()
                st.rerun()

# ─── Tab 3: Push to Finance ────────────────────────────────────
with tab_push:
    st.header("📤 Push Monthly Salaries to Finance")
    # Select month to finalize
    sel_month = st.date_input(
        "Select month to finalize",
        st.session_state.pay_anchor,
        key="push_month"
    )
    month_first = sel_month.replace(day=1)
    start_d, end_d = month_bounds(month_first)
    days = (end_d - start_d).days + 1
    req_hours = SHIFT_HOURS * (days - 4)

    # Check if already pushed for this month
    check_sql = text("""
        SELECT COUNT(*) FROM hr_salary_pushed WHERE month = :m
    """)
    with engine.connect() as con:
        already_pushed = con.execute(check_sql, {"m": month_first}).scalar() > 0

    st.caption(f"Period **{start_d:%Y‑%m‑%d} → {end_d:%Y‑%m‑%d}** • "
               f"Required h/emp = {req_hours:.1f} • "
               f"Month status: {'✅ Already pushed' if already_pushed else '🟡 Not yet pushed'}")

    # Fetch calculated salaries for this month
    df = fetch_month(start_d, end_d, req_hours)

    # Get base salary reason (raise/cut note) for each employee as of the first day of month
    base_reasons = {}
    base_sql = text("""
        SELECT employeeid, reason
        FROM hr_salary_history
        WHERE effective_from <= :month
          AND (effective_to IS NULL OR effective_to >= :month)
    """)
    with engine.connect() as con:
        for row in con.execute(base_sql, {"month": month_first}):
            base_reasons[row.employeeid] = row.reason

    # Prepare notes column: combine raise/cut reason and salary adj. reasons
    notes = []
    for _, row in df.iterrows():
        eid = int(row["employeeid"])
        note_parts = []
        raise_note = base_reasons.get(eid, "")
        if raise_note:
            note_parts.append(f"Raise/Cut: {raise_note}")
        if row["reasons"]:
            note_parts.append(f"Adj.: {row['reasons']}")
        notes.append(" | ".join(note_parts) if note_parts else "")

    # Prepare preview table with totals
    df_preview = df[["fullname", "base", "bonus", "extra", "fine", "net"]].copy()
    df_preview["note"] = notes

    # Add totals row (numeric)
    totals_row = {
        "fullname": "Totals",
        "base": df_preview["base"].sum(),
        "bonus": df_preview["bonus"].sum(),
        "extra": df_preview["extra"].sum(),
        "fine": df_preview["fine"].sum(),
        "net": df_preview["net"].sum(),
        "note": ""
    }
    df_totals = pd.DataFrame([totals_row])
    # Concatenate for display
    df_show = pd.concat([df_preview, df_totals], ignore_index=True)

    if already_pushed:
        st.info("Salaries for this month have already been pushed to finance. Viewing mode only.")
        pushed = pd.read_sql(
            text("""
                SELECT p.*, e.fullname FROM hr_salary_pushed p
                JOIN hr_employee e ON e.employeeid = p.employeeid
                WHERE month = :m
                ORDER BY e.fullname
            """), engine, params={"m": month_first}
        )
        pushed_preview = pushed[["fullname", "base", "bonus", "extra", "fine", "net", "note"]].copy()
        pushed_totals_row = {
            "fullname": "Totals",
            "base": pushed_preview["base"].sum(),
            "bonus": pushed_preview["bonus"].sum(),
            "extra": pushed_preview["extra"].sum(),
            "fine": pushed_preview["fine"].sum(),
            "net": pushed_preview["net"].sum(),
            "note": ""
        }
        pushed_show = pd.concat([pushed_preview, pd.DataFrame([pushed_totals_row])], ignore_index=True)
        st.dataframe(pushed_show, hide_index=True)
        st.caption(
            f"**Totals:** Base: {pushed_totals_row['base']:,.0f} | "
            f"Bonus: {pushed_totals_row['bonus']:,.0f} | "
            f"Extra: {pushed_totals_row['extra']:,.0f} | "
            f"Fine: {pushed_totals_row['fine']:,.0f} | "
            f"Net: {pushed_totals_row['net']:,.0f}"
        )
    else:
        st.warning("This will finalize all employee salaries for the selected month. You cannot edit or re-push after this.")
        st.dataframe(df_show, hide_index=True)
        st.caption(
            f"**Totals:** Base: {totals_row['base']:,.0f} | "
            f"Bonus: {totals_row['bonus']:,.0f} | "
            f"Extra: {totals_row['extra']:,.0f} | "
            f"Fine: {totals_row['fine']:,.0f} | "
            f"Net: {totals_row['net']:,.0f}"
        )

        if st.button("Push all to Finance (Finalize)", type="primary"):
            with engine.begin() as con:
                for idx, row in df.iterrows():
                    eid = int(row["employeeid"])
                    base = float(row["base"])
                    bonus = float(row["bonus"])
                    extra = float(row["extra"])
                    fine = float(row["fine"])
                    net = float(row["net"])
                    note = notes[idx]
                    created_by = st.session_state.get("user", "hr")
                    con.execute(
                        text("""
                            INSERT INTO hr_salary_pushed
                              (employeeid, month, base, bonus, extra, fine, net, note, created_by)
                            VALUES
                              (:eid, :month, :base, :bonus, :extra, :fine, :net, :note, :created_by)
                        """),
                        {
                            "eid": eid,
                            "month": month_first,
                            "base": base,
                            "bonus": bonus,
                            "extra": extra,
                            "fine": fine,
                            "net": net,
                            "note": note,
                            "created_by": created_by,
                        }
                    )
            st.success("Salaries finalized and pushed to finance. This month is now locked.")
            st.cache_data.clear(); st.rerun()
