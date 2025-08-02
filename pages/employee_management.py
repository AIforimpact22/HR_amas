# employee_management.py  –  Neon + Supabase Storage (private bucket) + bug-free dates
# Requires: streamlit ≥1.27, supabase, sqlalchemy, pandas
# --------------------------------------------------------------------

import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
from supabase import create_client
import datetime, mimetypes, uuid, os, urllib.parse

# ─────────────── GLOBAL CONFIG ────────────────────────────────────
st.set_page_config("Employee Mgmt", "👥", layout="wide")

TODAY      = datetime.date.today()
PAST_30    = TODAY - datetime.timedelta(days=365 * 30)
FUTURE_30  = TODAY + datetime.timedelta(days=365 * 30)
def win(d):                         # helper for edit pages
    return (min(PAST_30, d), max(FUTURE_30, d)) if d else (PAST_30, FUTURE_30)

# ---------- Supabase (private bucket) ----------
_SB      = create_client(st.secrets["supabase"]["url"],
                         st.secrets["supabase"]["anon"])
_BUCKET  = st.secrets["supabase"]["bucket"]

def _upload_to_supabase(file_obj, subfolder: str) -> str | None:
    """Upload file → return 7-day signed URL (or None)."""
    if file_obj is None:
        return None
    ext  = os.path.splitext(file_obj.name)[1] or ""
    key  = f"{subfolder}/{uuid.uuid4().hex}{ext}"
    mime = mimetypes.guess_type(file_obj.name)[0] or "application/octet-stream"
    _SB.storage.from_(_BUCKET).upload(key, file_obj, {"content-type": mime})
    signed = _SB.storage.from_(_BUCKET).create_signed_url(key, 60 * 60 * 24 * 7)
    return signed["signedURL"]

# ---------- PostgreSQL ----------
if "pg_engine" not in st.session_state:
    st.session_state.pg_engine = create_engine(
        st.secrets["neon"]["dsn"], pool_pre_ping=True, echo=False)
engine = st.session_state.pg_engine

# ---------- DB helpers ----------
def get_all_employees():
    return pd.read_sql("SELECT * FROM hr_employee ORDER BY employeeid DESC", engine)

def add_employee_with_salary(emp: dict, base: float):
    sql_emp = text("""
        INSERT INTO hr_employee (
            fullname, department, position, phone_no, emergency_phone_no, supervisor_phone_no,
            address, date_of_birth, employment_date, health_condition,
            cv_url, national_id_image_url, national_id_no, email, family_members,
            education_degree, language, ss_registration_date, assurance, assurance_state,
            employee_state, photo_url
        ) VALUES (
            :fullname, :department, :position, :phone_no, :emergency_phone_no, :supervisor_phone_no,
            :address, :date_of_birth, :employment_date, :health_condition,
            :cv_url, :national_id_image_url, :national_id_no, :email, :family_members,
            :education_degree, :language, :ss_registration_date, :assurance, :assurance_state,
            :employee_state, :photo_url
        )
        RETURNING employeeid
    """)
    sql_sal = text("""INSERT INTO hr_salary_history
                      (employeeid, salary, effective_from, reason)
                      VALUES (:eid, :sal, :eff, 'Initial contract rate')""")
    with engine.begin() as conn:
        eid = conn.execute(sql_emp, emp).scalar()
        conn.execute(sql_sal, {"eid": eid, "sal": base, "eff": emp["employment_date"]})

def update_employee(eid, **cols):
    sets = ", ".join([f"{k}=:{k}" for k in cols])
    cols["eid"] = eid
    with engine.begin() as conn:
        conn.execute(text(f"UPDATE hr_employee SET {sets} WHERE employeeid=:eid"), cols)

def search_employees(term: str):
    sql = text("""
       SELECT * FROM hr_employee
       WHERE fullname ILIKE :s OR email ILIKE :s OR department ILIKE :s
          OR phone_no ILIKE :s OR supervisor_phone_no ILIKE :s OR emergency_phone_no ILIKE :s
       ORDER BY employeeid DESC
    """)
    return pd.read_sql(sql, engine, params={"s": f"%{term}%"})

# ───────────── UI TABS ───────────────────────────────────────────
tab_add, tab_edit, tab_view = st.tabs(["➕ Add", "📝 Edit", "🔎 Search"])

# =================================================================
# ➕ ADD
# =================================================================
with tab_add:
    with st.form("add"):
        c1, c2 = st.columns(2)

        # left
        with c1:
            fullname         = st.text_input("Full Name *")
            department       = st.text_input("Department")
            position         = st.text_input("Position")
            phone_no         = st.text_input("Phone")
            emergency_phone_no  = st.text_input("Emergency Phone")
            supervisor_phone_no = st.text_input("Supervisor Phone")
            address          = st.text_area("Address")
            date_of_birth    = st.date_input("Date of Birth *",
                                             value=TODAY,
                                             min_value=PAST_30,
                                             max_value=TODAY)
            employment_date  = st.date_input("Employment Date *",
                                             value=TODAY,
                                             min_value=PAST_30,
                                             max_value=TODAY)
            basicsalary      = st.number_input("Basic Salary *", min_value=0.0, step=1000.0)
            health_condition = st.text_input("Health Condition")
            family_members   = st.number_input("Family Members", min_value=0)
            education_degree = st.text_input("Education Degree")
            language         = st.text_input("Languages")

        # right
        with c2:
            cv_up  = st.file_uploader("CV (PDF)", type=["pdf"])
            id_up  = st.file_uploader("National ID (image)", type=["jpg","jpeg","png"])
            national_id_no = st.number_input("National ID No", min_value=0)
            email  = st.text_input("Email")
            ss_registration_date = st.date_input("SS Registration Date",
                                                 value=TODAY,
                                                 min_value=PAST_30,
                                                 max_value=TODAY)
            assurance       = st.number_input("Assurance", min_value=0.0, step=1000.0)
            assurance_state = st.selectbox("Assurance State", ["active","repaid"])
            employee_state  = st.selectbox("Employee State", ["active","resigned","terminated"])
            photo_up        = st.file_uploader("Profile Photo", type=["jpg","jpeg","png"])

        if st.form_submit_button("Add"):
            missing = []
            if not fullname.strip(): missing.append("Full Name")
            if basicsalary <= 0:     missing.append("Basic Salary")
            if missing:
                st.error("Missing: " + ", ".join(missing)); st.stop()

            emp_payload = dict(
                fullname=fullname, department=department, position=position,
                phone_no=phone_no, emergency_phone_no=emergency_phone_no,
                supervisor_phone_no=supervisor_phone_no, address=address,
                date_of_birth=date_of_birth, employment_date=employment_date,
                health_condition=health_condition,
                cv_url=_upload_to_supabase(cv_up, "cv"),
                national_id_image_url=_upload_to_supabase(id_up, "nid"),
                national_id_no=national_id_no, email=email, family_members=family_members,
                education_degree=education_degree, language=language,
                ss_registration_date=ss_registration_date, assurance=assurance,
                assurance_state=assurance_state, employee_state=employee_state,
                photo_url=_upload_to_supabase(photo_up, "photo"),
            )
            add_employee_with_salary(emp_payload, basicsalary)
            st.success("Employee added! (Supabase URLs valid 7 days.)")

# =================================================================
# 📝 EDIT
# =================================================================
with tab_edit:
    df = get_all_employees()
    if df.empty:
        st.info("No employees."); st.stop()

    df["label"] = df["fullname"] + " (" + df["email"].fillna("-") + ")"
    row = df[df.label == st.selectbox("Select employee", df.label)].iloc[0]
    eid = int(row.employeeid)

    with st.form("edit"):
        c1, c2 = st.columns(2)

        # left
        with c1:
            fullname         = st.text_input("Full Name", row.fullname)
            department       = st.text_input("Department", row.department or "")
            position         = st.text_input("Position", row.position or "")
            phone_no         = st.text_input("Phone", row.phone_no or "")
            emergency_phone_no  = st.text_input("Emergency Phone", row.emergency_phone_no or "")
            supervisor_phone_no = st.text_input("Supervisor Phone", row.supervisor_phone_no or "")
            address          = st.text_area("Address", row.address or "")
            date_of_birth    = st.date_input("DOB",
                                             value=row.date_of_birth,
                                             min_value=PAST_30,
                                             max_value=FUTURE_30)
            employment_date  = st.date_input("Employment Date",
                                             value=row.employment_date,
                                             min_value=PAST_30,
                                             max_value=FUTURE_30)
            st.number_input("Salary (read-only – use Raise/Cut page)",
                            value=float(row.basicsalary), disabled=True)
            health_condition = st.text_input("Health Condition", row.health_condition or "")
            family_members   = st.number_input("Family Members", value=int(row.family_members or 0))
            education_degree = st.text_input("Education Degree", row.education_degree or "")
            language         = st.text_input("Languages", row.language or "")

        # right
        with c2:
            national_id_no = st.number_input("National ID No", value=int(row.national_id_no or 0))
            email  = st.text_input("Email", row.email or "")
            ss_registration_date = st.date_input("SS Registration",
                                                 value=row.ss_registration_date,
                                                 min_value=PAST_30,
                                                 max_value=FUTURE_30)
            assurance = st.number_input("Assurance", value=float(row.assurance or 0), step=1000.0)
            assurance_state = st.selectbox("Assurance State", ["active","repaid"],
                                           index=["active","repaid"].index(row.assurance_state))
            employee_state  = st.selectbox("Employee State", ["active","resigned","terminated"],
                                           index=["active","resigned","terminated"].index(row.employee_state))
            st.markdown("*Replace attachments (optional)*")
            cv_up    = st.file_uploader("New CV",   type=["pdf"])
            id_up    = st.file_uploader("New ID image", type=["jpg","jpeg","png"])
            photo_up = st.file_uploader("New Photo", type=["jpg","jpeg","png"])

        if st.form_submit_button("Update"):
            update_employee(
                eid,
                fullname=fullname, department=department, position=position,
                phone_no=phone_no, emergency_phone_no=emergency_phone_no,
                supervisor_phone_no=supervisor_phone_no, address=address,
                date_of_birth=date_of_birth, employment_date=employment_date,
                health_condition=health_condition,
                cv_url=_upload_to_supabase(cv_up, "cv") or row.cv_url,
                national_id_image_url=_upload_to_supabase(id_up, "nid") or row.national_id_image_url,
                national_id_no=national_id_no, email=email, family_members=family_members,
                education_degree=education_degree, language=language,
                ss_registration_date=ss_registration_date, assurance=assurance,
                assurance_state=assurance_state, employee_state=employee_state,
                photo_url=_upload_to_supabase(photo_up, "photo") or row.photo_url,
            )
            st.success("Employee updated! New uploads saved to Supabase.")

# =================================================================
# 🔎 VIEW / SEARCH
# =================================================================
with tab_view:
    q  = st.text_input("🔍  Search employee (name, email, phone)")
    df = search_employees(q) if q else get_all_employees()
    if df.empty:
        st.info("No matches."); st.stop()

    sal_map = pd.read_sql(
        "SELECT employeeid, salary FROM hr_salary_history WHERE effective_to IS NULL",
        engine).set_index("employeeid")["salary"].to_dict()

    st.session_state.setdefault("emp_sel", None)

    def show_img(url: str | None, width: int = 90):
        if url and urllib.parse.urlparse(url).scheme in ("http", "https"):
            st.image(url, width=width)
        else:
            st.image(f"https://placehold.co/{width}x{width}.png?text=No+Photo", width=width)

    def file_dl(label: str, url: str | None, key: str):
        if url and urllib.parse.urlparse(url).scheme in ("http", "https"):
            st.download_button(label, url, key=key)

    list_col, detail_col = st.columns([2, 3], gap="large")

    with list_col:
        st.markdown("### Results")
        for _, r in df.iterrows():
            eid = int(r.employeeid)
            with st.container(border=True):
                c1, c2 = st.columns([1, 3], gap="small")
                with c1: show_img(r.photo_url, 70)
                with c2:
                    st.markdown(f"**{r.fullname}**  \n{r.position or '-'} – {r.department or '-'}  \n`{r.employee_state}`")
                if st.button("View", key=f"btn_{eid}", use_container_width=True):
                    st.session_state.emp_sel = eid
            st.write("")

    with detail_col:
        sel_id = st.session_state.emp_sel
        if sel_id is None:
            st.info("Click **View** to see the full profile.")
        elif sel_id not in df.employeeid.values:
            st.warning("Selected employee not in current result set.")
        else:
            r = df.loc[df.employeeid == sel_id].iloc[0]
            st.subheader(r.fullname)
            c1, c2 = st.columns([1, 2], gap="large")

            with c1:
                show_img(r.photo_url, 180)
                st.metric("Current salary", f"Rp {sal_map.get(sel_id, 0):,.0f}")
                st.metric("Assurance", f"Rp {(r.assurance or 0):,.0f} ({r.assurance_state})")
                st.markdown(f"**Status:** `{r.employee_state}`")

            with c2:
                info = {
                    "Department": r.department, "Position": r.position, "Phone": r.phone_no,
                    "Email": r.email, "Supervisor phone": r.supervisor_phone_no,
                    "Emergency phone": r.emergency_phone_no, "Date of Birth": r.date_of_birth,
                    "Employment date": r.employment_date, "Languages": r.language,
                    "Education": r.education_degree, "Health condition": r.health_condition,
                    "Family members": r.family_members, "National ID No": r.national_id_no,
                    "SS registration": r.ss_registration_date,
                }
                st.markdown("### Profile")
                for k, v in info.items():
                    st.markdown(f"**{k}:**  {v or '-'}")

            st.markdown("---")
            file_dl("📄 Download CV", r.cv_url, f"cv_{sel_id}")
            file_dl("🪪 Download National ID", r.national_id_image_url, f"id_{sel_id}")
