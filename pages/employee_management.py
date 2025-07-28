import streamlit as st
import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor

# Database connection (adjust for your env)
@st.cache_resource
def get_connection():
    return psycopg2.connect(
        host=st.secrets["DB_HOST"],
        dbname=st.secrets["DB_NAME"],
        user=st.secrets["DB_USER"],
        password=st.secrets["DB_PASSWORD"],
        port=st.secrets["DB_PORT"],
        cursor_factory=RealDictCursor
    )

conn = get_connection()

st.title("👥 Employee Management")

tab1, tab2, tab3 = st.tabs(["➕ Add", "✏️ Edit", "🔍 Search"])

# ---- Tab 1: Add Employee ----
with tab1:
    st.subheader("Add New Employee")
    with st.form("add_employee"):
        fullname = st.text_input("Full Name")
        department = st.text_input("Department")
        position = st.text_input("Position")
        phone_no = st.text_input("Phone Number")
        emergency_phone_no = st.text_input("Emergency Phone Number")
        supervisor_phone_no = st.text_input("Supervisor Phone Number")
        address = st.text_area("Address")
        date_of_birth = st.date_input("Date of Birth")
        employment_date = st.date_input("Employment Date")
        basicsalary = st.number_input("Basic Salary", min_value=0)
        health_condition = st.text_input("Health Condition")
        cv = st.file_uploader("CV (PDF)", type=["pdf"])
        national_id_no = st.text_input("National ID No")
        national_id_image = st.file_uploader("National ID (image)", type=["jpg", "jpeg", "png"])
        email = st.text_input("Email")
        family_members = st.number_input("Family Members", min_value=0, step=1)
        education_degree = st.text_input("Education Degree")
        language = st.text_input("Languages (comma separated)")
        ss_registration_date = st.date_input("SS Registration Date")
        assurance = st.number_input("Assurance", min_value=0)
        assurance_state = st.selectbox("Assurance State", ["active", "repaid"])
        employee_state = st.selectbox("Employee State", ["active", "resigned", "terminated"])
        photo = st.file_uploader("Photo", type=["jpg", "jpeg", "png"])

        submit = st.form_submit_button("Add Employee")

        if submit:
            # [TODO: handle file uploads and store URLs]
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO hr_employee 
                (fullname, department, position, phone_no, emergency_phone_no, supervisor_phone_no, address, date_of_birth, employment_date, basicsalary, health_condition, national_id_no, email, family_members, education_degree, language, ss_registration_date, assurance, assurance_state, employee_state)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                fullname, department, position, phone_no, emergency_phone_no, supervisor_phone_no, address, date_of_birth, employment_date, basicsalary, health_condition, national_id_no, email, family_members, education_degree, language, ss_registration_date, assurance, assurance_state, employee_state
            ))
            conn.commit()
            st.success("Employee added!")

# ---- Tab 2: Edit Employee ----
with tab2:
    st.subheader("Edit Employee")
    # Search for employee by name or email
    search_term = st.text_input("Search Employee (by name or email)")
    if search_term:
        df = pd.read_sql(f"SELECT * FROM hr_employee WHERE fullname ILIKE %s OR email ILIKE %s", conn, params=(f"%{search_term}%", f"%{search_term}%"))
        if not df.empty:
            selected_emp = st.selectbox("Select Employee to Edit", df["fullname"] + " (" + df["email"] + ")", index=0)
            emp_row = df[df["fullname"] + " (" + df["email"] + ")" == selected_emp].iloc[0]
            # Show edit form (same fields as add), prefill values
            # [Repeat Add Employee fields, prefilled with emp_row[]]
            # [Update logic goes here...]
        else:
            st.warning("No employee found.")

# ---- Tab 3: Search / Directory ----
with tab3:
    st.subheader("Employee Directory")
    df = pd.read_sql("SELECT employeeid, fullname, department, position, phone_no, email, employee_state FROM hr_employee ORDER BY fullname", conn)
    st.dataframe(df, use_container_width=True)
    # Optionally: Add more filters, export to CSV, etc.

