import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
import datetime
import os

if "pg_engine" not in st.session_state:
    st.session_state.pg_engine = create_engine(
        st.secrets["neon"]["dsn"], pool_pre_ping=True, echo=False
    )
engine = st.session_state.pg_engine

def get_all_employees():
    return pd.read_sql(
        text("SELECT * FROM hr_employee ORDER BY employeeid DESC"), engine
    )

def add_employee(
    fullname, department, position, phone_no, emergency_phone_no, supervisor_phone_no,
    address, date_of_birth, employment_date, basicsalary, health_condition,
    cv_url, national_id_image_url, national_id_no, email, family_members,
    education_degree, language, ss_registration_date, assurance, assurance_state,
    employee_state, photo_url
):
    sql = text(
        """
        INSERT INTO hr_employee (
            fullname, department, position, phone_no, emergency_phone_no, supervisor_phone_no,
            address, date_of_birth, employment_date, basicsalary, health_condition,
            cv_url, national_id_image_url, national_id_no, email, family_members,
            education_degree, language, ss_registration_date, assurance, assurance_state,
            employee_state, photo_url
        ) VALUES (
            :fullname, :department, :position, :phone_no, :emergency_phone_no, :supervisor_phone_no,
            :address, :date_of_birth, :employment_date, :basicsalary, :health_condition,
            :cv_url, :national_id_image_url, :national_id_no, :email, :family_members,
            :education_degree, :language, :ss_registration_date, :assurance, :assurance_state,
            :employee_state, :photo_url
        )
        """
    )
    with engine.begin() as conn:
        conn.execute(
            sql,
            {
                "fullname": fullname,
                "department": department,
                "position": position,
                "phone_no": phone_no,
                "emergency_phone_no": emergency_phone_no,
                "supervisor_phone_no": supervisor_phone_no,
                "address": address,
                "date_of_birth": date_of_birth,
                "employment_date": employment_date,
                "basicsalary": basicsalary,
                "health_condition": health_condition,
                "cv_url": cv_url,
                "national_id_image_url": national_id_image_url,
                "national_id_no": national_id_no,
                "email": email,
                "family_members": family_members,
                "education_degree": education_degree,
                "language": language,
                "ss_registration_date": ss_registration_date,
                "assurance": assurance,
                "assurance_state": assurance_state,
                "employee_state": employee_state,
                "photo_url": photo_url,
            },
        )

def update_employee(
    employeeid, fullname, department, position, phone_no, emergency_phone_no, supervisor_phone_no,
    address, date_of_birth, employment_date, basicsalary, health_condition,
    cv_url, national_id_image_url, national_id_no, email, family_members,
    education_degree, language, ss_registration_date, assurance, assurance_state,
    employee_state, photo_url
):
    sql = text(
        """
        UPDATE hr_employee SET
            fullname=:fullname,
            department=:department,
            position=:position,
            phone_no=:phone_no,
            emergency_phone_no=:emergency_phone_no,
            supervisor_phone_no=:supervisor_phone_no,
            address=:address,
            date_of_birth=:date_of_birth,
            employment_date=:employment_date,
            basicsalary=:basicsalary,
            health_condition=:health_condition,
            cv_url=:cv_url,
            national_id_image_url=:national_id_image_url,
            national_id_no=:national_id_no,
            email=:email,
            family_members=:family_members,
            education_degree=:education_degree,
            language=:language,
            ss_registration_date=:ss_registration_date,
            assurance=:assurance,
            assurance_state=:assurance_state,
            employee_state=:employee_state,
            photo_url=:photo_url
        WHERE employeeid=:employeeid
        """
    )
    with engine.begin() as conn:
        conn.execute(
            sql,
            {
                "employeeid": employeeid,
                "fullname": fullname,
                "department": department,
                "position": position,
                "phone_no": phone_no,
                "emergency_phone_no": emergency_phone_no,
                "supervisor_phone_no": supervisor_phone_no,
                "address": address,
                "date_of_birth": date_of_birth,
                "employment_date": employment_date,
                "basicsalary": basicsalary,
                "health_condition": health_condition,
                "cv_url": cv_url,
                "national_id_image_url": national_id_image_url,
                "national_id_no": national_id_no,
                "email": email,
                "family_members": family_members,
                "education_degree": education_degree,
                "language": language,
                "ss_registration_date": ss_registration_date,
                "assurance": assurance,
                "assurance_state": assurance_state,
                "employee_state": employee_state,
                "photo_url": photo_url,
            },
        )

def search_employees(term: str):
    sql = text(
        """
        SELECT * FROM hr_employee
        WHERE fullname ILIKE :s
           OR email ILIKE :s
           OR department ILIKE :s
           OR phone_no ILIKE :s
           OR supervisor_phone_no ILIKE :s
           OR emergency_phone_no ILIKE :s
        ORDER BY employeeid DESC
        """
    )
    return pd.read_sql(sql, engine, params={"s": f"%{term}%"})

# ─────────────── Date helpers ───────────────
TODAY = datetime.date.today()
PAST_30 = TODAY - datetime.timedelta(days=365 * 30)
FUTURE_30 = TODAY + datetime.timedelta(days=365 * 30)

def _window(existing: datetime.date | None):
    if existing:
        return min(PAST_30, existing), max(FUTURE_30, existing)
    return PAST_30, FUTURE_30

# ─────────────── UI ───────────────
st.set_page_config(page_title="Employee Management", page_icon="👥", layout="wide")
st.title("👥 Employee Management")

tab_add, tab_edit, tab_search = st.tabs(["➕ Add Employee", "📝 Edit Employee", "🔎 Search"])

# ---------- ADD ----------
with tab_add:
    st.header("Add New Employee")
    with st.form("add_emp", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            fullname = st.text_input("Full Name *", max_chars=100)
            department = st.text_input("Department")
            position = st.text_input("Position")
            phone_no = st.text_input("Phone No.", max_chars=20)
            emergency_phone_no = st.text_input("Emergency Phone No.", max_chars=20)
            supervisor_phone_no = st.text_input("Supervisor Phone No.", max_chars=20)
            address = st.text_area("Address")
            date_of_birth = st.date_input("Date of Birth *", min_value=PAST_30, max_value=FUTURE_30)
            employment_date = st.date_input("Employment Date *", min_value=PAST_30, max_value=FUTURE_30)
            basicsalary = st.number_input("Basic Salary *", min_value=0.0, step=1000.0)
            health_condition = st.text_input("Health Condition")
            family_members = st.number_input("Family Members", min_value=0)
            education_degree = st.text_input("Education Degree")
            language = st.text_input("Languages")
        with c2:
            cv_file = st.file_uploader("CV (PDF)", type=["pdf"])
            national_id_image = st.file_uploader("National ID (image)", type=["jpg", "jpeg", "png"])
            national_id_no = st.number_input("National ID Number", min_value=0)
            email = st.text_input("Email")
            ss_registration_date = st.date_input("SS Registration Date", min_value=PAST_30, max_value=FUTURE_30)
            assurance = st.number_input("Assurance", min_value=0.0, step=1000.0)
            assurance_state = st.selectbox("Assurance State", ["active", "repaid"])
            employee_state = st.selectbox("Employee State", ["active", "resigned", "terminated"])
            photo = st.file_uploader("Photo", type=["jpg", "jpeg", "png"])
        submitted = st.form_submit_button("Add Employee")
        if submitted:
            required_errors = []
            if not fullname.strip():
                required_errors.append("Full Name")
            if not date_of_birth:
                required_errors.append("Date of Birth")
            if not employment_date:
                required_errors.append("Employment Date")
            if basicsalary <= 0:
                required_errors.append("Basic Salary (must be greater than 0)")
            if required_errors:
                st.error("Please fill these required fields: " + ", ".join(required_errors))
            else:
                add_employee(
                    fullname, department, position, phone_no, emergency_phone_no, supervisor_phone_no,
                    address, date_of_birth, employment_date, basicsalary, health_condition,
                    cv_file.name if cv_file else None,
                    national_id_image.name if national_id_image else None,
                    national_id_no, email, family_members, education_degree, language,
                    ss_registration_date, assurance, assurance_state, employee_state,
                    photo.name if photo else None,
                )
                st.success(f"Employee **{fullname}** added!")

# ---------- EDIT ----------
with tab_edit:
    st.header("Edit Employee")
    df = get_all_employees()
    if df.empty:
        st.info("No employees yet.")
    else:
        df["disp"] = df["fullname"] + " (" + df["email"] + ")"
        sel = st.selectbox("Choose employee", df["disp"])
        r = df[df["disp"] == sel].iloc[0]
        eid = r["employeeid"]

        dob = pd.to_datetime(r["date_of_birth"]).date()
        empd = pd.to_datetime(r["employment_date"]).date()
        ssd = pd.to_datetime(r["ss_registration_date"]).date()
        dob_min, dob_max = _window(dob)
        emp_min, emp_max = _window(empd)
        ss_min, ss_max = _window(ssd)

        with st.form("edit_emp"):
            fullname = st.text_input("Full Name", r["fullname"])
            department = st.text_input("Department", r["department"])
            position = st.text_input("Position", r["position"])
            phone_no = st.text_input("Phone No.", r["phone_no"])
            emergency_phone_no = st.text_input("Emergency Phone No.", r["emergency_phone_no"])
            supervisor_phone_no = st.text_input("Supervisor Phone No.", r["supervisor_phone_no"])
            address = st.text_area("Address", r["address"])
            date_of_birth = st.date_input("Date of Birth", dob, dob_min, dob_max)
            employment_date = st.date_input("Employment Date", empd, emp_min, emp_max)
            basicsalary = st.number_input(
                "Basic Salary", value=float(r["basicsalary"]), min_value=0.0, step=1000.0
            )
            health_condition = st.text_input("Health Condition", r["health_condition"])
            family_members = st.number_input(
                "Family Members", value=int(r["family_members"]), min_value=0
            )
            education_degree = st.text_input("Education Degree", r["education_degree"])
            language = st.text_input("Languages", r["language"])
            national_id_no = st.number_input(
                "National ID Number", value=int(r["national_id_no"]), min_value=0
            )
            email = st.text_input("Email", r["email"])
            ss_registration_date = st.date_input(
                "SS Registration Date", ssd, ss_min, ss_max
            )
            assurance = st.number_input(
                "Assurance", value=float(r["assurance"]), min_value=0.0, step=1000.0
            )
            assurance_state = st.selectbox(
                "Assurance State",
                ["active", "repaid"],
                index=["active", "repaid"].index(r["assurance_state"]),
            )
            employee_state = st.selectbox(
                "Employee State",
                ["active", "resigned", "terminated"],
                index=["active", "resigned", "terminated"].index(r["employee_state"]),
            )
            st.markdown("**Attachments (leave blank to keep old):**")
            cv_file = st.file_uploader("CV (PDF)", type=["pdf"], key=f"edit_cv_{eid}")
            national_id_image = st.file_uploader("National ID (image)", type=["jpg", "jpeg", "png"], key=f"edit_id_{eid}")
            photo = st.file_uploader("Photo", type=["jpg", "jpeg", "png"], key=f"edit_photo_{eid}")

            cv_url = cv_file.name if cv_file else r["cv_url"]
            national_id_image_url = national_id_image.name if national_id_image else r["national_id_image_url"]
            photo_url = photo.name if photo else r["photo_url"]

            if st.form_submit_button("Update Employee"):
                update_employee(
                    eid, fullname, department, position, phone_no, emergency_phone_no, supervisor_phone_no,
                    address, date_of_birth, employment_date, basicsalary, health_condition,
                    cv_url, national_id_image_url, national_id_no, email, family_members,
                    education_degree, language, ss_registration_date, assurance,
                    assurance_state, employee_state, photo_url
                )
                st.success(f"Employee **{fullname}** updated!")

# ---------- SEARCH ----------
with tab_search:
    st.header("Search Employees")
    q = st.text_input("Search (name, email, dept, phone)")
    data = search_employees(q) if q else get_all_employees()
    if data.empty:
        st.info("No records found.")
    else:
        for idx, row in data.iterrows():
            with st.expander(f"{row['fullname']} — {row['position']}"):
                cols = st.columns([1,2])
                with cols[0]:
                    # Only show photo if it exists and is a URL (not a local filename)
                    if row['photo_url']:
                        # If it's a full URL (starts with http), show; else, just print the name.
                        if str(row['photo_url']).lower().startswith("http"):
                            st.image(row['photo_url'], caption="Photo", width=120)
                        else:
                            st.write(f"Photo filename: {row['photo_url']}")
                    else:
                        st.write("No photo available.")
                with cols[1]:
                    st.write(f"**Department:** {row['department']}  \n**Phone:** {row['phone_no']}  \n**Email:** {row['email']}")
                    st.write(f"**Employment Date:** {row['employment_date']}  \n**Salary:** {row['basicsalary']}")
                    st.write(f"**State:** {row['employee_state']}  \n**Assurance:** {row['assurance']} ({row['assurance_state']})")
                    st.write(f"**Languages:** {row['language']}")
                # CV and National ID download links (only if it's a full URL)
                if row['cv_url']:
                    if str(row['cv_url']).lower().startswith("http"):
                        st.markdown(f"[📄 Download CV]({row['cv_url']})")
                    else:
                        st.write(f"CV filename: {row['cv_url']}")
                if row['national_id_image_url']:
                    if str(row['national_id_image_url']).lower().startswith("http"):
                        st.markdown(f"[🪪 National ID]({row['national_id_image_url']})")
                    else:
                        st.write(f"National ID image: {row['national_id_image_url']}")
