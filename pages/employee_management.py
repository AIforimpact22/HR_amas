import streamlit as st
import pandas as pd
import psycopg2

# ─────────────── DB Handler Functions ───────────────

def get_connection():
    # You can adjust these to match your Streamlit secrets or config
    conn = psycopg2.connect(
        host=st.secrets["db_host"],
        database=st.secrets["db_name"],
        user=st.secrets["db_user"],
        password=st.secrets["db_password"],
        port=st.secrets.get("db_port", 5432)
    )
    return conn

def get_all_employees():
    conn = get_connection()
    df = pd.read_sql("SELECT * FROM hr_employee ORDER BY employeeid DESC", conn)
    conn.close()
    return df

def add_employee(
    fullname, department, position, phone_no, emergency_phone_no, supervisor_phone_no,
    address, date_of_birth, employment_date, basicsalary, health_condition,
    cv_url, national_id_image_url, national_id_no, email, family_members,
    education_degree, language, ss_registration_date, assurance, assurance_state,
    employee_state, photo_url
):
    conn = get_connection()
    cur = conn.cursor()
    sql = """
        INSERT INTO hr_employee (
            fullname, department, position, phone_no, emergency_phone_no, supervisor_phone_no,
            address, date_of_birth, employment_date, basicsalary, health_condition,
            cv_url, national_id_image_url, national_id_no, email, family_members,
            education_degree, language, ss_registration_date, assurance, assurance_state,
            employee_state, photo_url
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    cur.execute(sql, (
        fullname, department, position, phone_no, emergency_phone_no, supervisor_phone_no,
        address, date_of_birth, employment_date, basicsalary, health_condition,
        cv_url, national_id_image_url, national_id_no, email, family_members,
        education_degree, language, ss_registration_date, assurance, assurance_state,
        employee_state, photo_url
    ))
    conn.commit()
    cur.close()
    conn.close()

def update_employee(
    employeeid, fullname, department, position, phone_no, emergency_phone_no, supervisor_phone_no,
    address, date_of_birth, employment_date, basicsalary, health_condition,
    cv_url, national_id_image_url, national_id_no, email, family_members,
    education_degree, language, ss_registration_date, assurance, assurance_state,
    employee_state, photo_url
):
    conn = get_connection()
    cur = conn.cursor()
    sql = """
        UPDATE hr_employee SET
            fullname=%s, department=%s, position=%s, phone_no=%s, emergency_phone_no=%s, supervisor_phone_no=%s,
            address=%s, date_of_birth=%s, employment_date=%s, basicsalary=%s, health_condition=%s,
            cv_url=%s, national_id_image_url=%s, national_id_no=%s, email=%s, family_members=%s,
            education_degree=%s, language=%s, ss_registration_date=%s, assurance=%s, assurance_state=%s,
            employee_state=%s, photo_url=%s
        WHERE employeeid=%s
    """
    cur.execute(sql, (
        fullname, department, position, phone_no, emergency_phone_no, supervisor_phone_no,
        address, date_of_birth, employment_date, basicsalary, health_condition,
        cv_url, national_id_image_url, national_id_no, email, family_members,
        education_degree, language, ss_registration_date, assurance, assurance_state,
        employee_state, photo_url, employeeid
    ))
    conn.commit()
    cur.close()
    conn.close()

def search_employees(term):
    conn = get_connection()
    sql = """
        SELECT * FROM hr_employee
        WHERE fullname ILIKE %s
           OR email ILIKE %s
           OR department ILIKE %s
           OR phone_no ILIKE %s
           OR supervisor_phone_no ILIKE %s
           OR emergency_phone_no ILIKE %s
        ORDER BY employeeid DESC
    """
    search = f"%{term}%"
    df = pd.read_sql(sql, conn, params=(search, search, search, search, search, search))
    conn.close()
    return df

# ─────────────── Streamlit UI ───────────────

st.set_page_config(page_title="Employee Management", page_icon="👥", layout="wide")
st.title("👥 Employee Management")

tabs = st.tabs(["➕ Add Employee", "📝 Edit Employee", "🔎 Search Employees"])

# ------- Add Employee -------
with tabs[0]:
    st.header("Add New Employee")
    with st.form("add_employee_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            fullname = st.text_input("Full Name", max_chars=100)
            department = st.text_input("Department")
            position = st.text_input("Position")
            phone_no = st.text_input("Phone No.", max_chars=20)
            emergency_phone_no = st.text_input("Emergency Phone No.", max_chars=20)
            supervisor_phone_no = st.text_input("Supervisor Phone No.", max_chars=20)
            address = st.text_area("Address")
            date_of_birth = st.date_input("Date of Birth")
            employment_date = st.date_input("Employment Date")
            basicsalary = st.number_input("Basic Salary", min_value=0.0, step=1000.0)
            health_condition = st.text_input("Health Condition")
            family_members = st.number_input("Family Members", min_value=0)
            education_degree = st.text_input("Education Degree")
            language = st.text_input("Languages (comma separated)")
        with col2:
            cv_file = st.file_uploader("CV (PDF)", type=["pdf"])
            national_id_image = st.file_uploader("National ID (image)", type=["jpg", "jpeg", "png"])
            national_id_no = st.number_input("National ID Number", min_value=0)
            email = st.text_input("Email")
            ss_registration_date = st.date_input("Social Security Registration Date")
            assurance = st.number_input("Assurance", min_value=0.0, step=1000.0)
            assurance_state = st.selectbox("Assurance State", options=["active", "repaid"])
            employee_state = st.selectbox("Employee State", options=["active", "resigned", "terminated"])
            photo = st.file_uploader("Photo", type=["jpg", "jpeg", "png"])
        
        submitted = st.form_submit_button("Add Employee")
        if submitted:
            # Save uploaded files or handle paths here (now just None for demo)
            cv_url = cv_file.name if cv_file else None
            national_id_image_url = national_id_image.name if national_id_image else None
            photo_url = photo.name if photo else None

            add_employee(
                fullname, department, position, phone_no, emergency_phone_no, supervisor_phone_no,
                address, date_of_birth, employment_date, basicsalary, health_condition,
                cv_url, national_id_image_url, national_id_no, email, family_members,
                education_degree, language, ss_registration_date, assurance, assurance_state,
                employee_state, photo_url
            )
            st.success(f"Employee '{fullname}' added successfully!")

# ------- Edit Employee -------
with tabs[1]:
    st.header("Edit Employee")
    all_employees = get_all_employees()
    if not all_employees.empty:
        all_employees["display"] = all_employees["fullname"] + " (" + all_employees["email"] + ")"
        selected_emp = st.selectbox("Select employee to edit", all_employees["display"])
        emp_row = all_employees[all_employees["display"] == selected_emp].iloc[0]
        emp_id = emp_row["employeeid"]
        
        with st.form("edit_employee_form"):
            # Pre-fill form fields with existing values
            fullname = st.text_input("Full Name", value=emp_row["fullname"])
            department = st.text_input("Department", value=emp_row["department"])
            position = st.text_input("Position", value=emp_row["position"])
            phone_no = st.text_input("Phone No.", value=emp_row["phone_no"])
            emergency_phone_no = st.text_input("Emergency Phone No.", value=emp_row["emergency_phone_no"])
            supervisor_phone_no = st.text_input("Supervisor Phone No.", value=emp_row["supervisor_phone_no"])
            address = st.text_area("Address", value=emp_row["address"])
            date_of_birth = st.date_input("Date of Birth", value=pd.to_datetime(emp_row["date_of_birth"]))
            employment_date = st.date_input("Employment Date", value=pd.to_datetime(emp_row["employment_date"]))
            basicsalary = st.number_input("Basic Salary", value=float(emp_row["basicsalary"]), min_value=0.0, step=1000.0)
            health_condition = st.text_input("Health Condition", value=emp_row["health_condition"])
            family_members = st.number_input("Family Members", value=int(emp_row["family_members"]), min_value=0)
            education_degree = st.text_input("Education Degree", value=emp_row["education_degree"])
            language = st.text_input("Languages (comma separated)", value=emp_row["language"])
            national_id_no = st.number_input("National ID Number", value=int(emp_row["national_id_no"]), min_value=0)
            email = st.text_input("Email", value=emp_row["email"])
            ss_registration_date = st.date_input("Social Security Registration Date", value=pd.to_datetime(emp_row["ss_registration_date"]))
            assurance = st.number_input("Assurance", value=float(emp_row["assurance"]), min_value=0.0, step=1000.0)
            assurance_state = st.selectbox("Assurance State", options=["active", "repaid"], index=["active", "repaid"].index(emp_row["assurance_state"]))
            employee_state = st.selectbox("Employee State", options=["active", "resigned", "terminated"], index=["active", "resigned", "terminated"].index(emp_row["employee_state"]))
            submitted = st.form_submit_button("Update Employee")

            if submitted:
                update_employee(
                    emp_id, fullname, department, position, phone_no, emergency_phone_no, supervisor_phone_no,
                    address, date_of_birth, employment_date, basicsalary, health_condition,
                    emp_row["cv_url"], emp_row["national_id_image_url"], national_id_no, email, family_members,
                    education_degree, language, ss_registration_date, assurance, assurance_state,
                    employee_state, emp_row["photo_url"]
                )
                st.success(f"Employee '{fullname}' updated successfully!")
    else:
        st.info("No employees found. Please add employees first.")

# ------- Search Employees -------
with tabs[2]:
    st.header("Search Employees")
    search_term = st.text_input("Enter name, email, department, or phone:")
    if search_term:
        results = search_employees(search_term)
        if results is not None and not results.empty:
            st.dataframe(results)
        else:
            st.warning("No matching employees found.")
    else:
        st.dataframe(get_all_employees())
