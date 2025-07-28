import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
import datetime

# ─────────────── SQLAlchemy Engine (cached) ───────────────
#   st.secrets["neon"]["dsn"]  →  postgresql://user:pwd@host/db?sslmode=...
if "pg_engine" not in st.session_state:
    st.session_state.pg_engine = create_engine(
        st.secrets["neon"]["dsn"], pool_pre_ping=True, echo=False
    )
engine = st.session_state.pg_engine

# ─────────────── CRUD Helper Functions ───────────────
def get_all_employees():
    sql = "SELECT * FROM hr_employee ORDER BY employeeid DESC"
    return pd.read_sql(text(sql), engine)


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


def search_employees(term):
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
    search = f"%{term}%"
    return pd.read_sql(sql, engine, params={"s": search})


# ─────────────── Date helpers (30‑year range) ───────────────
TODAY      = datetime.date.today()
PAST_30_Y  = TODAY - datetime.timedelta(days=365 * 30)
FUTURE_30Y = TODAY + datetime.timedelta(days=365 * 30)


def thirty_year_window(existing: datetime.date | None = None):
    """Ensure picker always includes stored value."""
    if existing:
        return min(PAST_30_Y, existing), max(FUTURE_30Y, existing)
    return PAST_30_Y, FUTURE_30Y


# ─────────────── Streamlit UI ───────────────
st.set_page_config(page_title="Employee Management", page_icon="👥", layout="wide")
st.title("👥 Employee Management")

tabs = st.tabs(["➕ Add Employee", "📝 Edit Employee", "🔎 Search Employees"])

# ------- Add Employee -------
with tabs[0]:
    st.header("Add New Employee")
    with st.form("add_emp", clear_on_submit=True):
        col1, col2 = st.columns(2)

        with col1:
            fullname              = st.text_input("Full Name", max_chars=100)
            department            = st.text_input("Department")
            position              = st.text_input("Position")
            phone_no              = st.text_input("Phone No.", max_chars=20)
            emergency_phone_no    = st.text_input("Emergency Phone No.", max_chars=20)
            supervisor_phone_no   = st.text_input("Supervisor Phone No.", max_chars=20)
            address               = st.text_area("Address")
            date_of_birth         = st.date_input("Date of Birth", min_value=PAST_30_Y, max_value=FUTURE_30Y)
            employment_date       = st.date_input("Employment Date", min_value=PAST_30_Y, max_value=FUTURE_30Y)
            basicsalary           = st.number_input("Basic Salary", min_value=0.0, step=1000.0)
            health_condition      = st.text_input("Health Condition")
            family_members        = st.number_input("Family Members", min_value=0)
            education_degree      = st.text_input("Education Degree")
            language              = st.text_input("Languages (comma separated)")

        with col2:
            cv_file              = st.file_uploader("CV (PDF)", type=["pdf"])
            national_id_image    = st.file_uploader("National ID (image)", type=["jpg", "jpeg", "png"])
            national_id_no       = st.number_input("National ID Number", min_value=0)
            email                = st.text_input("Email")
            ss_registration_date = st.date_input("Social Security Registration Date", min_value=PAST_30_Y, max_value=FUTURE_30Y)
            assurance            = st.number_input("Assurance", min_value=0.0, step=1000.0)
            assurance_state      = st.selectbox("Assurance State", ["active", "repaid"])
            employee_state       = st.selectbox("Employee State", ["active", "resigned", "terminated"])
            photo                = st.file_uploader("Photo", type=["jpg", "jpeg", "png"])

        if st.form_submit_button("Add Employee"):
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

# ------- Edit Employee -------
with tabs[1]:
    st.header("Edit Employee")
    df_all = get_all_employees()

    if df_all.empty:
        st.info("No employees found.")
    else:
        df_all["disp"] = df_all["fullname"] + " (" + df_all["email"] + ")"
        choice = st.selectbox("Select employee", df_all["disp"])
        row    = df_all[df_all["disp"] == choice].iloc[0]
        emp_id = row["employeeid"]

        dob_val = pd.to_datetime(row["date_of_birth"]).date()
        emp_val = pd.to_datetime(row["employment_date"]).date()
        ss_val  = pd.to_datetime(row["ss_registration_date"]).date()

        dob_min, dob_max = thirty_year_window(dob_val)
        emp_min, emp_max = thirty_year_window(emp_val)
        ss_min,  ss_max  = thirty_year_window(ss_val)

        with st.form("edit_emp"):
            fullname            = st.text_input("Full Name", row["fullname"])
            department          = st.text_input("Department", row["department"])
            position            = st.text_input("Position", row["position"])
            phone_no            = st.text_input("Phone No.", row["phone_no"])
            emergency_phone_no  = st.text_input("Emergency Phone No.", row["emergency_phone_no"])
            supervisor_phone_no = st.text_input("Supervisor Phone No.", row["supervisor_phone_no"])
            address             = st.text_area("Address", row["address"])
            date_of_birth       = st.date_input("Date of Birth", dob_val, dob_min, dob_max)
            employment_date     = st.date_input("Employment Date", emp_val, emp_min, emp_max)
            basicsalary         = st.number_input("Basic Salary", float(row["basicsalary"]), min_value=0.0, step=1000.0)
            health_condition    = st.text_input("Health Condition", row["health_condition"])
            family_members      = st.number_input("Family Members", int(row["family_members"]), min_value=0)
            education_degree    = st.text_input("Education Degree", row["education_degree"])
            language            = st.text_input("Languages", row["language"])
            national_id_no      = st.number_input("National ID Number", int(row["national_id_no"]), min_value=0)
            email               = st.text_input("Email", row["email"])
            ss_registration_date = st.date_input("Social Security Registration Date", ss_val, ss_min, ss_max)
            assurance           = st.number_input("Assurance", float(row["assurance"]), min_value=0.0, step=1000.0)
            assurance_state     = st.selectbox("Assurance State", ["active", "repaid"], index=["active", "repaid"].index(row["assurance_state"]))
            employee_state      = st.selectbox("Employee State", ["active", "resigned", "terminated"], index=["active", "resigned", "terminated"].index(row["employee_state"]))

            if st.form_submit_button("Update Employee"):
                update_employee(
                    emp_id, fullname, department, position, phone_no, emergency_phone_no, supervisor_phone_no,
                    address, date_of_birth, employment_date, basicsalary, health_condition,
                    row["cv_url"], row["national_id_image_url"], national_id_no, email, family_members,
                    education_degree, language, ss_registration_date, assurance, assurance_state, employee_state,
                    row["photo_url"]
                )
                st.success(f"Employee **{fullname}** updated!")

# ------- Search Employees -------
with tabs[2]:
    st.header("Search Employees")
    query = st.text_input("Name, email, department, or phone:")
    data  = search_employees(query) if query else get_all_employees()
    st.dataframe(data)
