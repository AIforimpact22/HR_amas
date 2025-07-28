import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
import datetime

# ─────────────────────────────────────────────────────────────
# DB engine (cached)
# ─────────────────────────────────────────────────────────────
if "pg_engine" not in st.session_state:
    st.session_state.pg_engine = create_engine(
        st.secrets["neon"]["dsn"], pool_pre_ping=True, echo=False
    )
engine = st.session_state.pg_engine

SHIFT_HOURS = 8.5  # normal hours / shift

# ─────────────────────────────────────────────────────────────
# Data helpers
# ─────────────────────────────────────────────────────────────
def fetch_attendance(start: datetime.date, end: datetime.date) -> pd.DataFrame:
    sql = text("""
        SELECT  a.employeeid,
                e.fullname,
                a.punch_date,
                a.clock_in,
                a.clock_out,
                EXTRACT(EPOCH FROM (COALESCE(a.clock_out, NOW()) - a.clock_in))/3600
                   AS hours_worked
        FROM hr_attendance a
        JOIN hr_employee   e USING (employeeid)
        WHERE a.punch_date BETWEEN :start AND :end
        ORDER BY a.punch_date, a.clock_in
    """)
    return pd.read_sql(sql, engine, params={"start": start, "end": end})

def aggregate(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=[
            "employeeid","fullname","days_present","total_hours",
            "expected_hours","delta_hours"
        ])
    g = df.groupby(["employeeid", "fullname"])
    out = g.agg(
        days_present=("punch_date", "nunique"),
        total_hours=("hours_worked", "sum"),
    ).reset_index()
    out["expected_hours"] = out["days_present"] * SHIFT_HOURS
    out["delta_hours"]    = out["total_hours"] - out["expected_hours"]
    return out.sort_values("fullname")

# ─────────────────────────────────────────────────────────────
# UI ▸ Attendance Dashboard
# ─────────────────────────────────────────────────────────────
st.set_page_config("Attendance","⏱",layout="wide")
st.title("⏱ Employee Attendance")

# ----- Select time window -----
scope = st.radio(
    "Time scope",
    ["Today", "This week", "This month", "This year", "Custom"],
    horizontal=True
)

today = datetime.date.today()
if scope == "Today":
    start = end = today
elif scope == "This week":
    start = today - datetime.timedelta(days=today.weekday())          # Monday
    end   = today
elif scope == "This month":
    start = today.replace(day=1)
    end   = today
elif scope == "This year":
    start = today.replace(month=1, day=1)
    end   = today
else:  # Custom range
    start, end = st.date_input(
        "Select date range (max 365 days)", (today, today)
    )
    if isinstance(start, tuple):  # Streamlit <v1.32 bug‑compat
        start, end = start
    if start > end:
        st.error("Start date must be before end date.")
        st.stop()
    if (end - start).days > 365:
        st.error("Please pick a range ≤ 1 year.")
        st.stop()

# ----- Fetch / Aggregate -----
data = fetch_attendance(start, end)
summary = aggregate(data)

st.subheader(
    f"Summary • {start:%Y‑%m‑%d} → {end:%Y‑%m‑%d} "
    f"  ({(end-start).days+1} day{'s' if start!=end else ''})"
)

st.dataframe(
    summary.style.format({
        "total_hours": "{:.2f}",
        "expected_hours": "{:.1f}",
        "delta_hours": "{:+.2f}"
    }),
    use_container_width=True,
)

# ----- Daily detail if single day -----
if start == end:
    st.subheader("Detail (clock‑in / clock‑out)")
    if data.empty:
        st.info("No punches recorded for this date.")
    else:
        data["clock_in"]  = pd.to_datetime(data["clock_in"]).dt.strftime("%H:%M:%S")
        data["clock_out"] = pd.to_datetime(data["clock_out"]).dt.strftime("%H:%M:%S")
        data = data[["fullname","clock_in","clock_out","hours_worked"]]
        data.rename(columns={"fullname":"Employee","hours_worked":"Hours"}, inplace=True)
        st.dataframe(
            data.style.format({"Hours": "{:.2f}"}),
            use_container_width=True,
            hide_index=True
        )
else:
    st.caption("Choose **Today** scope for punch‑by‑punch detail.")
