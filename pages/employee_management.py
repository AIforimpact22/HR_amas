import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
import datetime, os

# ─── STATIC CONFIG ────────────────────────────────────────────────
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ─── DB ENGINE (cached) ───────────────────────────────────────────
if "pg_engine" not in st.session_state:
    st.session_state.pg_engine = create_engine(
        st.secrets["neon"]["dsn"], pool_pre_ping=True, echo=False
    )
engine = st.session_state.pg_engine

# ─── HELPERS ──────────────────────────────────────────────────────
def save_file(up_file):
    if up_file is None:
        return None
    path = os.path.join(UPLOAD_DIR, up_file.name)
    with open(path, "wb") as f:
        f.write(up_file.getbuffer())
    return path

def get_all_employees():
    return pd.read_sql("SELECT * FROM hr_employee ORDER BY employeeid DESC", engine)

# ➊ ADD employee + salary‑history in one transaction
def add_employee_with_salary(emp_payload: dict, base_salary: float):
    """
    1. insert into hr_employee … RETURNING employeeid
    2. insert into hr_salary_history (employeeid, salary, effective_from)
       effective_from = employment_date
    """
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
    sql_sal = text("""
        INSERT INTO hr_salary_history
              (employeeid, salary, effective_from, reason)
        VALUES (:eid, :sal, :eff_from, 'Initial contract rate')
    """)
    with engine.begin() as conn:
        eid = conn.execute(sql_emp, emp_payload).scalar()         # 1️⃣
        conn.execute(sql_sal,                                    # 2️⃣
                     {"eid": eid,
                      "sal": base_salary,
                      "eff_from": emp_payload["employment_date"]})

def update_employee(eid, **cols):
    sets = ", ".join([f"{k}=:{k}" for k in cols])
    sql = text(f"UPDATE hr_employee SET {sets} WHERE employeeid=:eid")
    cols["eid"] = eid
    with engine.begin() as conn:
        conn.execute(sql, cols)

def search_employees(term):
    sql = text("""
       SELECT * FROM hr_employee
       WHERE fullname ILIKE :s OR email ILIKE :s OR department ILIKE :s
          OR phone_no ILIKE :s OR supervisor_phone_no ILIKE :s OR emergency_phone_no ILIKE :s
       ORDER BY employeeid DESC
    """)
    return pd.read_sql(sql, engine, params={"s": f"%{term}%"})

# ─── DATE UTIL ────────────────────────────────────────────────────
TODAY=datetime.date.today(); PAST_30=TODAY-datetime.timedelta(days=365*30); FUTURE_30=TODAY+datetime.timedelta(days=365*30)
def win(d): return (min(PAST_30,d),max(FUTURE_30,d)) if d else (PAST_30,FUTURE_30)

# ─── UI ───────────────────────────────────────────────────────────
st.set_page_config("Employee Mgmt","👥",layout="wide")
st.title("👥 Employee Management")

tab_add, tab_edit, tab_view = st.tabs(["➕ Add","📝 Edit","🔎 Search"])

# ---------- ADD ----------
with tab_add:
    with st.form("add"):
        c1,c2 = st.columns(2)
        with c1:
            fullname=st.text_input("Full Name *")
            department=st.text_input("Department")
            position=st.text_input("Position")
            phone_no=st.text_input("Phone")
            emergency_phone_no=st.text_input("Emergency Phone")
            supervisor_phone_no=st.text_input("Supervisor Phone")
            address=st.text_area("Address")
            date_of_birth=st.date_input("Date of Birth *",min_value=PAST_30,max_value=FUTURE_30)
            employment_date=st.date_input("Employment Date *",min_value=PAST_30,max_value=FUTURE_30)
            basicsalary=st.number_input("Basic Salary *",min_value=0.0,step=1000.0)
            health_condition=st.text_input("Health Condition")
            family_members=st.number_input("Family Members",min_value=0)
            education_degree=st.text_input("Education Degree")
            language=st.text_input("Languages")
        with c2:
            cv_up=st.file_uploader("CV (PDF)",type=["pdf"])
            id_up=st.file_uploader("National ID (image)",type=["jpg","jpeg","png"])
            national_id_no=st.number_input("National ID No",min_value=0)
            email=st.text_input("Email")
            ss_registration_date=st.date_input("SS Registration Date",min_value=PAST_30,max_value=FUTURE_30)
            assurance=st.number_input("Assurance",min_value=0.0,step=1000.0)
            assurance_state=st.selectbox("Assurance State",["active","repaid"])
            employee_state=st.selectbox("Employee State",["active","resigned","terminated"])
            photo_up=st.file_uploader("Profile Photo",type=["jpg","jpeg","png"])
        if st.form_submit_button("Add"):
            errs=[]
            if not fullname.strip(): errs.append("Full Name")
            if basicsalary<=0: errs.append("Basic Salary")
            if errs: st.error("Missing: "+", ".join(errs)); st.stop()

            emp_payload = dict(
                fullname=fullname,department=department,position=position,phone_no=phone_no,
                emergency_phone_no=emergency_phone_no,supervisor_phone_no=supervisor_phone_no,
                address=address,date_of_birth=date_of_birth,employment_date=employment_date,
                health_condition=health_condition,
                cv_url=save_file(cv_up),national_id_image_url=save_file(id_up),
                national_id_no=national_id_no,email=email,family_members=family_members,
                education_degree=education_degree,language=language,
                ss_registration_date=ss_registration_date,assurance=assurance,assurance_state=assurance_state,
                employee_state=employee_state,photo_url=save_file(photo_up)
            )
            add_employee_with_salary(emp_payload, basicsalary)
            st.success("Employee added with initial salary record!")

# ---------- EDIT ----------
with tab_edit:
    df = get_all_employees()
    if df.empty:
        st.info("No employees")
        st.stop()

    df["label"] = df["fullname"] + " (" + df["email"].fillna("-") + ")"
    row = df[df.label == st.selectbox("Select employee", df.label)].iloc[0]
    eid = int(row.employeeid)          # ← cast fixes numpy.int64 error

    with st.form("edit"):
        c1, c2 = st.columns(2)
        with c1:
            fullname = st.text_input("Full Name", row.fullname)
            department = st.text_input("Department", row.department or "")
            position = st.text_input("Position", row.position or "")
            phone_no = st.text_input("Phone", row.phone_no or "")
            emergency_phone_no = st.text_input("Emergency Phone", row.emergency_phone_no or "")
            supervisor_phone_no = st.text_input("Supervisor Phone", row.supervisor_phone_no or "")
            address = st.text_area("Address", row.address or "")
            date_of_birth = st.date_input("DOB", row.date_of_birth, *win(row.date_of_birth))
            employment_date = st.date_input("Employment Date", row.employment_date, *win(row.employment_date))

            st.number_input(
                "Salary (read‑only – use Raise/Cut page)",
                value=float(row.basicsalary),
                disabled=True,
            )

            health_condition = st.text_input("Health Condition", row.health_condition or "")
            family_members = st.number_input(
                "Family Members", value=int(row.family_members or 0), min_value=0
            )
            education_degree = st.text_input("Education Degree", row.education_degree or "")
            language = st.text_input("Languages", row.language or "")
        with c2:
            national_id_no = st.number_input(
                "National ID No", value=int(row.national_id_no or 0), min_value=0
            )
            email = st.text_input("Email", row.email or "")
            ss_registration_date = st.date_input(
                "SS Registration", row.ss_registration_date, *win(row.ss_registration_date)
            )
            assurance = st.number_input(
                "Assurance", value=float(row.assurance or 0), min_value=0.0, step=1000.0
            )
            assurance_state = st.selectbox(
                "Assurance State",
                ["active", "repaid"],
                index=["active", "repaid"].index(row.assurance_state),
            )
            employee_state = st.selectbox(
                "Employee State",
                ["active", "resigned", "terminated"],
                index=["active", "resigned", "terminated"].index(row.employee_state),
            )
            st.markdown("*Replace attachments (optional)*")
            cv_up = st.file_uploader("New CV", type=["pdf"])
            id_up = st.file_uploader("New ID image", type=["jpg", "jpeg", "png"])
            photo_up = st.file_uploader("New Photo", type=["jpg", "jpeg", "png"])

        if st.form_submit_button("Update"):
            update_employee(
                eid,
                fullname=fullname,
                department=department,
                position=position,
                phone_no=phone_no,
                emergency_phone_no=emergency_phone_no,
                supervisor_phone_no=supervisor_phone_no,
                address=address,
                date_of_birth=date_of_birth,
                employment_date=employment_date,
                health_condition=health_condition,
                cv_url=save_file(cv_up) or row.cv_url,
                national_id_image_url=save_file(id_up) or row.national_id_image_url,
                national_id_no=national_id_no,
                email=email,
                family_members=family_members,
                education_degree=education_degree,
                language=language,
                ss_registration_date=ss_registration_date,
                assurance=assurance,
                assurance_state=assurance_state,
                employee_state=employee_state,
                photo_url=save_file(photo_up) or row.photo_url,
            )
            st.success("Employee data updated (salary unchanged).")


# ---------- VIEW / SEARCH  (FIXED) ----------
def _show_employee_details(row: pd.Series, salary_map: dict):
    st.markdown("---")
    st.subheader(row.fullname)

    c1, c2 = st.columns([1, 2], gap="large")
    with c1:
        img_path = (
            row.photo_url
            if row.photo_url and os.path.exists(row.photo_url)
            else "static/no_avatar.png"
        )
        st.image(img_path, width=180)
        st.metric("Current salary",
                  f"Rp {salary_map.get(int(row.employeeid), 0):,.0f}")
        st.metric("Assurance",
                  f"Rp {(row.assurance or 0):,.0f} ({row.assurance_state})")
        st.markdown(f"**Status:** `{row.employee_state}`")

    with c2:
        info = {
            "Department": row.department,
            "Position": row.position,
            "Phone": row.phone_no,
            "Email": row.email,
            "Supervisor": row.supervisor_phone_no,
            "Emergency": row.emergency_phone_no,
            "DOB": row.date_of_birth,
            "Employment": row.employment_date,
            "Languages": row.language,
            "Education": row.education_degree,
            "Health": row.health_condition,
            "Family members": row.family_members,
        }
        for k, v in info.items():
            st.markdown(f"**{k}:**  {v or '-'}")

        for label, path in (
            ("📄 CV", row.cv_url),
            ("🪪 National ID", row.national_id_image_url),
        ):
            if path and os.path.exists(path):
                with open(path, "rb") as f:
                    st.download_button(label, f,
                        file_name=os.path.basename(path),
                        key=f"dl_{label}_{row.employeeid}"
                    )

with tab_view:
    df_all = get_all_employees()
    if df_all.empty:
        st.info("No employees.")
        st.stop()

    with st.sidebar:
        q = st.text_input("🔍 Search (name / email / phone)")
        sel_dept = st.multiselect("Department",
                                  sorted(df_all.department.dropna().unique()))
        sel_state = st.multiselect("Status",
                                   ["active", "resigned", "terminated"])

    df = df_all.copy()
    if q:
        ql = q.lower()
        df = df[
            df.fullname.str.lower().str.contains(ql)
            | df.email.fillna("").str.lower().str.contains(ql)
            | df.phone_no.fillna("").str.contains(ql)
        ]
    if sel_dept:
        df = df[df.department.isin(sel_dept)]
    if sel_state:
        df = df[df.employee_state.isin(sel_state)]

    if df.empty:
        st.info("No matches.")
        st.stop()

    sal_map = pd.read_sql(
        "SELECT employeeid, salary FROM hr_salary_history "
        "WHERE effective_to IS NULL", engine
    ).set_index("employeeid")["salary"].to_dict()

    df["salary"] = df.employeeid.map(lambda x: sal_map.get(int(x), 0))
    df["photo"] = df.photo_url

    grid = st.data_editor(
        df[["photo", "fullname", "position",
            "department", "salary", "employee_state"]],
        key="emp_grid",
        hide_index=True,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "photo": st.column_config.ImageColumn(   # ⬅ removed css_style
                "Photo", width="60px"                # ⬅ keep width only
            ),
            "salary": st.column_config.NumberColumn(
                "Salary", format="Rp {:,.0f}"
            ),
            "employee_state": st.column_config.SelectboxColumn(
                "Status", options=["active", "resigned", "terminated"]
            ),
        },
    )

    sel_rows = grid.get("selected_row_indices", [])
    if sel_rows:
        _show_employee_details(df.iloc[sel_rows[0]], sal_map)
