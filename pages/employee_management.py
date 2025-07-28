import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
import datetime, os, io

# ─── CONFIG ──────────────────────────────────────────────────────────────
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ─── DB ENGINE ───────────────────────────────────────────────────────────
if "pg_engine" not in st.session_state:
    st.session_state.pg_engine = create_engine(
        st.secrets["neon"]["dsn"], pool_pre_ping=True, echo=False
    )
engine = st.session_state.pg_engine

# ─── HELPERS ─────────────────────────────────────────────────────────────
def save_file(uploaded_file) -> str | None:
    """Save uploader file and return relative path; None if no file."""
    if uploaded_file is None:
        return None
    path = os.path.join(UPLOAD_DIR, uploaded_file.name)
    with open(path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return path

def get_all_employees():
    return pd.read_sql(text("SELECT * FROM hr_employee ORDER BY employeeid DESC"), engine)

def add_employee(*vals):
    sql = text("""
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
    """)
    with engine.begin() as conn:
        conn.execute(sql, dict(zip(sql.columns.keys(), vals)))

def update_employee(employeeid, **cols):
    sets = ", ".join([f"{k}=:{k}" for k in cols.keys()])
    sql = text(f"UPDATE hr_employee SET {sets} WHERE employeeid=:employeeid")
    cols["employeeid"] = employeeid
    with engine.begin() as conn:
        conn.execute(sql, cols)

def search_employees(term: str):
    sql = text("""
        SELECT * FROM hr_employee
        WHERE fullname ILIKE :s OR email ILIKE :s OR department ILIKE :s
           OR phone_no ILIKE :s OR supervisor_phone_no ILIKE :s OR emergency_phone_no ILIKE :s
        ORDER BY employeeid DESC
    """)
    return pd.read_sql(sql, engine, params={"s": f"%{term}%"})

# ─── DATE UTILS ──────────────────────────────────────────────────────────
TODAY = datetime.date.today()
PAST_30 = TODAY - datetime.timedelta(days=365*30)
FUTURE_30 = TODAY + datetime.timedelta(days=365*30)
def win(x): 
    return (min(PAST_30, x), max(FUTURE_30, x)) if x else (PAST_30, FUTURE_30)

# ─── UI ──────────────────────────────────────────────────────────────────
st.set_page_config("Employee Management", "👥", layout="wide")
st.title("👥 Employee Management")

tab_add, tab_edit, tab_view = st.tabs(["➕ Add", "📝 Edit", "🔎 Search"])

# ── ADD ─────────────────────────────────────────────────────
with tab_add:
    with st.form("add"):
        c1, c2 = st.columns(2)
        with c1:
            fullname = st.text_input("Full Name *")
            department = st.text_input("Department")
            position = st.text_input("Position")
            phone_no = st.text_input("Phone No.")
            emergency_phone_no = st.text_input("Emergency Phone No.")
            supervisor_phone_no = st.text_input("Supervisor Phone No.")
            address = st.text_area("Address")
            date_of_birth = st.date_input("Date of Birth *", min_value=PAST_30, max_value=FUTURE_30)
            employment_date = st.date_input("Employment Date *", min_value=PAST_30, max_value=FUTURE_30)
            basicsalary = st.number_input("Basic Salary *", min_value=0.0, step=1000.0)
            health_condition = st.text_input("Health Condition")
            family_members = st.number_input("Family Members", min_value=0)
            education_degree = st.text_input("Education Degree")
            language = st.text_input("Languages")
        with c2:
            cv_up = st.file_uploader("CV (PDF)", type=["pdf"])
            id_up = st.file_uploader("National ID (image)", type=["jpg","jpeg","png"])
            national_id_no = st.number_input("National ID Number", min_value=0)
            email = st.text_input("Email")
            ss_registration_date = st.date_input("SS Registration Date", min_value=PAST_30, max_value=FUTURE_30)
            assurance = st.number_input("Assurance", min_value=0.0, step=1000.0)
            assurance_state = st.selectbox("Assurance State", ["active", "repaid"])
            employee_state = st.selectbox("Employee State", ["active", "resigned", "terminated"])
            photo_up = st.file_uploader("Profile Photo", type=["jpg","jpeg","png"])
        if st.form_submit_button("Add"):
            errors=[]
            if not fullname.strip(): errors.append("Full Name")
            if basicsalary<=0: errors.append("Basic Salary")
            if errors: st.error("Missing: "+", ".join(errors)); st.stop()
            cv_path  = save_file(cv_up)
            id_path  = save_file(id_up)
            pho_path = save_file(photo_up)
            add_employee(
                fullname, department, position, phone_no, emergency_phone_no, supervisor_phone_no,
                address, date_of_birth, employment_date, basicsalary, health_condition,
                cv_path, id_path, national_id_no, email, family_members,
                education_degree, language, ss_registration_date, assurance, assurance_state,
                employee_state, pho_path
            )
            st.success("Employee added.")

# ── EDIT ───────────────────────────────────────────────────
with tab_edit:
    df = get_all_employees()
    if df.empty(): st.info("No employees."); st.stop()
    df["label"] = df["fullname"]+" ("+df["email"].fillna("-")+ ")"
    sel = st.selectbox("Select employee", df["label"])
    row = df[df["label"]==sel].iloc[0]
    with st.form("edit"):
        c1,c2=st.columns(2)
        with c1:
            fullname = st.text_input("Full Name", row.fullname)
            department = st.text_input("Department", row.department or "")
            position = st.text_input("Position", row.position or "")
            phone_no = st.text_input("Phone No.", row.phone_no or "")
            emergency_phone_no = st.text_input("Emergency Phone", row.emergency_phone_no or "")
            supervisor_phone_no = st.text_input("Supervisor Phone", row.supervisor_phone_no or "")
            address = st.text_area("Address", row.address or "")
            date_of_birth = st.date_input("Date of Birth", row.date_of_birth, *win(row.date_of_birth))
            employment_date= st.date_input("Employment Date", row.employment_date, *win(row.employment_date))
            basicsalary=st.number_input("Basic Salary", value=float(row.basicsalary),min_value=0.0,step=1000.0)
            health_condition=st.text_input("Health Condition", row.health_condition or "")
            family_members=st.number_input("Family Members", value=int(row.family_members or 0), min_value=0)
            education_degree=st.text_input("Education Degree", row.education_degree or "")
            language=st.text_input("Languages", row.language or "")
        with c2:
            id_no=st.number_input("National ID No", value=int(row.national_id_no or 0), min_value=0)
            email=st.text_input("Email", row.email or "")
            ss_registration_date=st.date_input("SS Registration Date", row.ss_registration_date, *win(row.ss_registration_date))
            assurance=st.number_input("Assurance", value=float(row.assurance or 0), min_value=0.0, step=1000.0)
            assurance_state=st.selectbox("Assurance State",["active","repaid"],index=["active","repaid"].index(row.assurance_state))
            employee_state=st.selectbox("Employee State",["active","resigned","terminated"], index=["active","resigned","terminated"].index(row.employee_state))
            st.markdown("**Replace attachments (optional):**")
            cv_up=st.file_uploader("New CV", type=["pdf"])
            id_up=st.file_uploader("New National ID", type=["jpg","jpeg","png"])
            photo_up=st.file_uploader("New Photo", type=["jpg","jpeg","png"])
        if st.form_submit_button("Update"):
            upd=dict(
                fullname=fullname,department=department,position=position,phone_no=phone_no,
                emergency_phone_no=emergency_phone_no,supervisor_phone_no=supervisor_phone_no,
                address=address,date_of_birth=date_of_birth,employment_date=employment_date,
                basicsalary=basicsalary,health_condition=health_condition,cv_url=row.cv_url,
                national_id_image_url=row.national_id_image_url,national_id_no=id_no,email=email,
                family_members=family_members,education_degree=education_degree,language=language,
                ss_registration_date=ss_registration_date,assurance=assurance,assurance_state=assurance_state,
                employee_state=employee_state,photo_url=row.photo_url
            )
            if cv_up:  upd["cv_url"]=save_file(cv_up)
            if id_up:  upd["national_id_image_url"]=save_file(id_up)
            if photo_up: upd["photo_url"]=save_file(photo_up)
            update_employee(row.employeeid, **upd)
            st.success("Updated.")

# ── SEARCH / VIEW ──────────────────────────────────────────
with tab_view:
    q=st.text_input("Search employees")
    data=search_employees(q) if q else get_all_employees()
    if data.empty: st.info("No matches."); st.stop()
    for _,r in data.iterrows():
        with st.expander(f"{r.fullname} — {r.position}"):
            c1,c2=st.columns([1,2])
            with c1:
                if r.photo_url and os.path.exists(r.photo_url):
                    st.image(r.photo_url,width=160)
                elif r.photo_url:
                    st.write("Photo:", r.photo_url)
            with c2:
                st.markdown(f"""
**Department:** {r.department or '-'}   **Phone:** {r.phone_no or '-'}   **Email:** {r.email or '-'}  
**DOB:** {r.date_of_birth}   **Employment:** {r.employment_date}  
**Salary:** {r.basicsalary}   **State:** {r.employee_state}  
**Assurance:** {r.assurance} ({r.assurance_state})  
**Languages:** {r.language or '-'}  
""")
            # attachments
            if r.cv_url and os.path.exists(r.cv_url):
                with open(r.cv_url,"rb") as f:
                    st.download_button("📄 Download CV", data=f, file_name=os.path.basename(r.cv_url))
            elif r.cv_url:
                st.write("CV:", r.cv_url)
            if r.national_id_image_url and os.path.exists(r.national_id_image_url):
                with open(r.national_id_image_url,"rb") as f:
                    st.download_button("🪪 Download National ID", data=f, file_name=os.path.basename(r.national_id_image_url))
            elif r.national_id_image_url:
                st.write("National ID image:", r.national_id_image_url)
