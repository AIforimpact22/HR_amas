# employee_management.py  –  Neon + Supabase Storage (private bucket) – stable upload/download
# Requires: streamlit ≥1.27, supabase-py, sqlalchemy, pandas
# ------------------------------------------------------------------

import streamlit as st, pandas as pd, datetime, mimetypes, uuid, os, urllib.parse, posixpath
from sqlalchemy import create_engine, text
from supabase import create_client

# ─── DATE CONSTANTS ──────────────────────────────────────────────
TODAY     = datetime.date.today()
PAST_30   = TODAY - datetime.timedelta(days=365*30)
FUTURE_30 = TODAY + datetime.timedelta(days=365*30)

# ─── KEEP A SAFE HANDLE TO THE ORIGINAL FILE UPLOADER ───────────
file_uploader = st.file_uploader   # ← alias prevents later mutation issues

# ─── SUPABASE (service key) ─────────────────────────────────────
sb_conf  = st.secrets["supabase"]
_SB      = create_client(sb_conf["url"], sb_conf["service"])   # FULL perms
BUCKET   = sb_conf["bucket"]

def _upload_to_supabase(file_obj, subfolder):
    """Upload bytes → 7-day signed URL (private bucket)"""
    if file_obj is None:
        return None
    ext  = os.path.splitext(file_obj.name)[1] or ""
    key  = f"{subfolder}/{uuid.uuid4().hex}{ext}"
    mime = mimetypes.guess_type(file_obj.name)[0] or "application/octet-stream"
    _SB.storage.from_(BUCKET).upload(key, file_obj.read(), {"content-type": mime})
    return _SB.storage.from_(BUCKET).create_signed_url(key, 60*60*24*7)["signedURL"]

# ─── POSTGRES ENGINE ────────────────────────────────────────────
if "pg_engine" not in st.session_state:
    st.session_state.pg_engine = create_engine(st.secrets["neon"]["dsn"], pool_pre_ping=True)
engine = st.session_state.pg_engine

def get_all_employees():
    return pd.read_sql("SELECT * FROM hr_employee ORDER BY employeeid DESC", engine)

def add_employee_with_salary(emp, base):
    with engine.begin() as conn:
        eid = conn.execute(text("""INSERT INTO hr_employee (
            fullname, department, position, phone_no, emergency_phone_no, supervisor_phone_no,
            address, date_of_birth, employment_date, health_condition,
            cv_url, national_id_image_url, national_id_no, email, family_members,
            education_degree, language, ss_registration_date, assurance, assurance_state,
            employee_state, photo_url)
            VALUES (:fullname,:department,:position,:phone_no,:emergency_phone_no,:supervisor_phone_no,
                    :address,:date_of_birth,:employment_date,:health_condition,
                    :cv_url,:national_id_image_url,:national_id_no,:email,:family_members,
                    :education_degree,:language,:ss_registration_date,:assurance,:assurance_state,
                    :employee_state,:photo_url) RETURNING employeeid"""), emp).scalar()
        conn.execute(text("""INSERT INTO hr_salary_history
                             (employeeid,salary,effective_from,reason)
                             VALUES (:eid,:sal,:eff,'Initial contract rate')"""),
                     {"eid": eid, "sal": base, "eff": emp["employment_date"]})
    return eid

def update_employee(eid, **cols):
    with engine.begin() as conn:
        conn.execute(text("UPDATE hr_employee SET " +
                    ", ".join(f"{k}=:{k}" for k in cols) +
                    " WHERE employeeid=:eid"), {**cols, "eid": eid})

def search_employees(term):
    return pd.read_sql(text("""
        SELECT * FROM hr_employee
        WHERE fullname ILIKE :s OR email ILIKE :s OR department ILIKE :s
           OR phone_no ILIKE :s OR supervisor_phone_no ILIKE :s OR emergency_phone_no ILIKE :s
        ORDER BY employeeid DESC"""), engine, params={"s": f"%{term}%"})

# ─── STREAMLIT UI ───────────────────────────────────────────────
st.set_page_config("Employee Mgmt", "👥", layout="wide")
tab_add, tab_edit, tab_view = st.tabs(["➕ Add", "📝 Edit", "🔎 Search"])

# ---------------------- ADD TAB ---------------------------------
with tab_add:
    with st.form("add"):
        c1, c2 = st.columns(2)
        with c1:
            fullname = st.text_input("Full Name *")
            department = st.text_input("Department")
            position = st.text_input("Position")
            phone_no = st.text_input("Phone")
            emergency_phone_no = st.text_input("Emergency Phone")
            supervisor_phone_no = st.text_input("Supervisor Phone")
            address = st.text_area("Address")
            date_of_birth   = st.date_input("Date of Birth *", value=TODAY, min_value=PAST_30, max_value=TODAY)
            employment_date = st.date_input("Employment Date *", value=TODAY, min_value=PAST_30, max_value=TODAY)
            basicsalary = st.number_input("Basic Salary *", min_value=0.0, step=1000.0)
            health_condition = st.text_input("Health Condition")
            family_members = st.number_input("Family Members", min_value=0)
            education_degree = st.text_input("Education Degree")
            language = st.text_input("Languages")
        with c2:
            cv_up  = file_uploader("CV (PDF)", type=["pdf"])
            id_up  = file_uploader("National ID (image)", type=["jpg","jpeg","png"])
            national_id_no = st.number_input("National ID No", min_value=0)
            email = st.text_input("Email")
            ss_registration_date = st.date_input("SS Registration Date", value=TODAY,
                                                 min_value=PAST_30, max_value=TODAY)
            assurance = st.number_input("Assurance", min_value=0.0, step=1000.0)
            assurance_state = st.selectbox("Assurance State", ["active","repaid"])
            employee_state  = st.selectbox("Employee State", ["active","resigned","terminated"])
            photo_up = file_uploader("Profile Photo", type=["jpg","jpeg","png"])

        if st.form_submit_button("Add"):
            if not fullname.strip() or basicsalary <= 0:
                st.error("Name and positive salary required."); st.stop()

            emp = dict(
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
                photo_url=_upload_to_supabase(photo_up, "photo"))
            add_employee_with_salary(emp, basicsalary)
            st.success("Employee added – files stored in Supabase!")

# ---------------------- EDIT TAB (unchanged) --------------------
#  (Keep same as previous script, but replace every st.file_uploader with file_uploader)

# ---------------------- VIEW / SEARCH TAB -----------------------
with tab_view:
    q = st.text_input("🔍  Search employee (name / email / phone)")
    df = search_employees(q) if q else get_all_employees()
    if df.empty:
        st.info("No matches."); st.stop()

    sal_map = pd.read_sql("""SELECT employeeid,salary
                             FROM hr_salary_history WHERE effective_to IS NULL""",
                          engine).set_index("employeeid")["salary"].to_dict()
    st.session_state.setdefault("emp_sel", None)

    def show_img(url, w=90):
        if url and urllib.parse.urlparse(url).scheme in ("http","https"):
            st.image(url, width=w)
        else:
            st.image(f"https://placehold.co/{w}x{w}.png?text=No+Photo", width=w)

    def file_dl(label, url, key):
        if url and urllib.parse.urlparse(url).scheme in ("http","https"):
            fname = posixpath.basename(urllib.parse.urlparse(url).path) or "download"
            st.download_button(label, url, file_name=fname, key=key)

    list_col, detail_col = st.columns([2,3], gap="large")

    with list_col:
        st.markdown("### Results")
        for _, r in df.iterrows():
            eid = int(r.employeeid)
            with st.container(border=True):
                c1, c2 = st.columns([1,3])
                with c1: show_img(r.photo_url, 70)
                with c2: st.markdown(f"**{r.fullname}**\n{r.position or '-'} – {r.department or '-'}\n`{r.employee_state}`")
                if st.button("View", key=f"view_{eid}", use_container_width=True):
                    st.session_state.emp_sel = eid
            st.write("")

    with detail_col:
        sel = st.session_state.emp_sel
        if sel and sel in df.employeeid.values:
            r = df.loc[df.employeeid == sel].iloc[0]
            st.subheader(r.fullname)
            c1, c2 = st.columns([1,2], gap="large")

            with c1:
                show_img(r.photo_url, 180)
                st.metric("Current salary", f"Rp {sal_map.get(sel,0):,.0f}")
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
                    st.markdown(f"**{k}:** {v or '-'}")

            st.markdown("---")
            file_dl("📄 Download CV", r.cv_url, f"cv_{sel}")
            file_dl("🪪 Download National ID", r.national_id_image_url, f"id_{sel}")
        else:
            st.info("Select an employee from the list to view details.")
