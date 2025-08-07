# employee_management.py  –  Neon + Supabase Storage – downloads keep extension
# Requires: streamlit ≥1.27, supabase-py, sqlalchemy, pandas, requests
# ------------------------------------------------------------------

import streamlit as st, pandas as pd, datetime, mimetypes, uuid, os, urllib.parse, posixpath, requests   # ① added requests
from sqlalchemy import create_engine, text
from supabase import create_client

TODAY, PAST_30 = datetime.date.today(), datetime.date.today() - datetime.timedelta(days=365*30)
FUTURE_30 = TODAY + datetime.timedelta(days=365*30)

# Keep original uploader handle
file_uploader = st.file_uploader

# Supabase client (service key)
sb_cfg = st.secrets["supabase"]
_SB = create_client(sb_cfg["url"], sb_cfg["service"])
BUCKET = sb_cfg["bucket"]

def _upload_to_supabase(file_obj, folder):
    if file_obj is None: return None
    ext = os.path.splitext(file_obj.name)[1] or ""
    key = f"{folder}/{uuid.uuid4().hex}{ext}"
    mime = mimetypes.guess_type(file_obj.name)[0] or "application/octet-stream"
    _SB.storage.from_(BUCKET).upload(key, file_obj.read(), {"content-type": mime})
    return _SB.storage.from_(BUCKET).create_signed_url(key, 60*60*24*7)["signedURL"]

# Postgres
if "pg_engine" not in st.session_state:
    st.session_state.pg_engine = create_engine(st.secrets["neon"]["dsn"], pool_pre_ping=True)
engine = st.session_state.pg_engine

def get_all_employees(): return pd.read_sql("SELECT * FROM hr_employee ORDER BY employeeid DESC", engine)

def add_employee_with_salary(emp, base):
    with engine.begin() as conn:
        eid = conn.execute(text("""INSERT INTO hr_employee (
            fullname, department, position, phone_no, emergency_phone_no, supervisor_phone_no,
            address, date_of_birth, employment_date, health_condition,
            cv_url, national_id_image_url, national_id_no, email, family_members,
            education_degree, language, ss_registration_date, assurance, assurance_state,
            employee_state, photo_url) VALUES (
            :fullname,:department,:position,:phone_no,:emergency_phone_no,:supervisor_phone_no,
            :address,:date_of_birth,:employment_date,:health_condition,
            :cv_url,:national_id_image_url,:national_id_no,:email,:family_members,
            :education_degree,:language,:ss_registration_date,:assurance,:assurance_state,
            :employee_state,:photo_url) RETURNING employeeid"""), emp).scalar()
        conn.execute(text("""INSERT INTO hr_salary_history
                             (employeeid,salary,effective_from,reason)
                             VALUES (:eid,:sal,:eff,'Initial contract rate')"""),
                     {"eid": eid, "sal": base, "eff": emp["employment_date"]})

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

# UI
st.set_page_config("Employee Mgmt", "👥", layout="wide")
tab_add, tab_edit, tab_view = st.tabs(["➕ Add", "📝 Edit", "🔎 Search"])
# ---------------------- ADD TAB (revamped UI) -------------------
with tab_add:
    st.subheader("➕ Add New Employee")

    # ── form with sub-tabs --------------------------------------
    with st.form("add_emp"):
        t_personal, t_employment, t_files = st.tabs(
            ["👤 Personal & Contact", "💼 Employment & Pay", "📎 Attachments"]
        )

        # ---------- TAB 1 : PERSONAL & CONTACT ----------
        with t_personal:
            c1, c2 = st.columns(2)
            with c1:
                fullname = st.text_input("Full Name ＊")
                department = st.text_input("Department")
                position   = st.text_input("Position")
                phone_no   = st.text_input("Phone")
                email      = st.text_input("Email")
                address    = st.text_area("Address")
            with c2:
                emergency_phone_no  = st.text_input("Emergency Phone")
                supervisor_phone_no = st.text_input("Supervisor Phone")
                date_of_birth = st.date_input(
                    "Date of Birth ＊", value=TODAY, min_value=PAST_30, max_value=TODAY
                )
                language  = st.text_input("Languages (comma-sep)")
                health_condition = st.text_input("Health Condition")
                family_members   = st.number_input("Family Members", min_value=0)

        # ---------- TAB 2 : EMPLOYMENT & PAY ----------
        with t_employment:
            c1, c2 = st.columns(2)
            with c1:
                employment_date = st.date_input(
                    "Employment Date ＊",
                    value=TODAY,
                    min_value=PAST_30,
                    max_value=TODAY,
                )
                basicsalary = st.number_input(
                    "Basic Salary ＊",
                    min_value=0.0,
                    step=1000.0,
                    format="%.0f",
                )
                education_degree = st.text_input("Education Degree")
            with c2:
                ss_registration_date = st.date_input(
                    "SS Registration Date",
                    value=TODAY,
                    min_value=PAST_30,
                    max_value=TODAY,
                )
                assurance = st.number_input("Assurance", min_value=0.0, step=1000.0)
                assurance_state = st.radio("Assurance State", ["active", "repaid"], horizontal=True)
                employee_state = st.radio(
                    "Employee State", ["active", "resigned", "terminated"], horizontal=True
                )
                national_id_no = st.text_input("National ID No")

        # ---------- TAB 3 : ATTACHMENTS ----------
        with t_files:
            c1, c2 = st.columns(2)
            with c1:
                cv_up = file_uploader("CV (PDF)", type=["pdf"])
                id_up = file_uploader("National ID (image)", type=["jpg", "jpeg", "png"])
            with c2:
                photo_up = file_uploader("Profile Photo", type=["jpg", "jpeg", "png"])
                # live preview
                if photo_up is not None:
                    st.image(photo_up, width=150, caption="Preview")

        # ---------- SUBMIT ----------
        submit = st.form_submit_button("Add Employee", type="primary")

    # ── validation & insert --------------------------------------
    if submit:
        missing = []
        if not fullname.strip():   missing.append("Full Name")
        if basicsalary <= 0:       missing.append("Basic Salary")
        if date_of_birth > TODAY:  missing.append("Date of Birth")
        if employment_date > TODAY:missing.append("Employment Date")

        if missing:
            st.error("Please complete: " + ", ".join(missing))
            st.stop()

        emp = dict(
            fullname=fullname, department=department, position=position,
            phone_no=phone_no, emergency_phone_no=emergency_phone_no,
            supervisor_phone_no=supervisor_phone_no, address=address,
            date_of_birth=date_of_birth, employment_date=employment_date,
            health_condition=health_condition, cv_url=_upload_to_supabase(cv_up, "cv"),
            national_id_image_url=_upload_to_supabase(id_up, "nid"),
            national_id_no=national_id_no, email=email, family_members=family_members,
            education_degree=education_degree, language=language,
            ss_registration_date=ss_registration_date, assurance=assurance,
            assurance_state=assurance_state, employee_state=employee_state,
            photo_url=_upload_to_supabase(photo_up, "photo"),
        )

        add_employee_with_salary(emp, basicsalary)

        st.success(
            f"Employee **{fullname}** added!  "
            "Files stored securely in Supabase."
        )

# ========== EDIT TAB (revamped UI) ===========================================
with tab_edit:
    df_all = get_all_employees()
    if df_all.empty:
        st.info("No employees in database."); st.stop()

    # — pick employee —
    df_all["label"] = df_all["fullname"] + " (" + df_all["email"].fillna("-") + ")"
    sel_label = st.selectbox("Select employee to edit", df_all.label, index=0)
    row = df_all[df_all.label == sel_label].iloc[0]
    eid = int(row.employeeid)

    # — fetch latest base salary —
    cur_sal = pd.read_sql(
        text("""SELECT salary FROM hr_salary_history
                WHERE employeeid=:eid ORDER BY effective_from DESC LIMIT 1"""),
        engine, params={"eid": eid}
    ).squeeze() if not df_all.empty else 0.0

    # — summary card —
    card_bg = "#1ABC9C20"
    col_card1, col_card2 = st.columns([1,3])
    with col_card1:
        st.image(row.photo_url or f"https://placehold.co/120x120.png?text=No+Photo", width=120)
    with col_card2:
        st.markdown(
            f"""
            <div style="background:{card_bg};padding:10px;border-radius:6px">
            <b>{row.fullname}</b><br>
            Dept/Pos: {row.department or '-'} / {row.position or '-'}<br>
            Salary: <b>Rp {cur_sal:,.0f}</b> &nbsp;|&nbsp;
            Assurance: Rp {(row.assurance or 0):,.0f} ({row.assurance_state})<br>
            Status: <code>{row.employee_state}</code>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("### Edit details")

    # -------------------- FORM --------------------
    with st.form(f"edit_emp_{eid}"):
        t_personal, t_employment, t_files = st.tabs(
            ["👤 Personal & Contact", "💼 Employment & Pay", "📎 Attachments"]
        )

        # ---------- TAB 1 ----------
        with t_personal:
            c1, c2 = st.columns(2)
            with c1:
                fullname   = st.text_input("Full Name ＊", row.fullname)
                department = st.text_input("Department", row.department or "")
                position   = st.text_input("Position", row.position or "")
                phone_no   = st.text_input("Phone", row.phone_no or "")
                email      = st.text_input("Email", row.email or "")
                address    = st.text_area("Address", row.address or "")
            with c2:
                emergency_phone_no  = st.text_input("Emergency Phone", row.emergency_phone_no or "")
                supervisor_phone_no = st.text_input("Supervisor Phone", row.supervisor_phone_no or "")
                date_of_birth = st.date_input(
                    "Date of Birth ＊", value=row.date_of_birth,
                    min_value=PAST_30, max_value=TODAY
                )
                language = st.text_input("Languages", row.language or "")
                health_condition = st.text_input("Health Condition", row.health_condition or "")
                family_members   = st.number_input("Family Members", value=int(row.family_members or 0))

        # ---------- TAB 2 ----------
        with t_employment:
            c1, c2 = st.columns(2)
            with c1:
                employment_date = st.date_input(
                    "Employment Date ＊", value=row.employment_date,
                    min_value=PAST_30, max_value=TODAY
                )
                st.number_input("Basic Salary (read-only)", value=float(cur_sal), disabled=True)
                education_degree = st.text_input("Education Degree", row.education_degree or "")
            with c2:
                ss_registration_date = st.date_input(
                    "SS Registration Date", value=row.ss_registration_date,
                    min_value=PAST_30, max_value=FUTURE_30
                )
                assurance = st.number_input("Assurance", min_value=0.0, step=1000.0,
                                            value=float(row.assurance or 0))
                assurance_state = st.radio(
                    "Assurance State", ["active", "repaid"],
                    index=["active","repaid"].index(row.assurance_state), horizontal=True
                )
                employee_state = st.radio(
                    "Employee State", ["active", "resigned", "terminated"],
                    index=["active","resigned","terminated"].index(row.employee_state), horizontal=True
                )
                national_id_no = st.text_input("National ID No", str(row.national_id_no or ""))

        # ---------- TAB 3 ----------
        with t_files:
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Current Files**")
                if row.cv_url:
                    st.link_button("📄 View CV", row.cv_url)
                if row.national_id_image_url:
                    st.link_button("🪪 View Nat. ID", row.national_id_image_url)
                st.image(row.photo_url or "https://placehold.co/150x150.png?text=No+Photo",
                         width=150, caption="Current Photo")
            with c2:
                st.markdown("**Replace (optional)**")
                cv_up   = st.file_uploader("New CV (PDF)", type=["pdf"])
                id_up   = st.file_uploader("New National ID (image)", type=["jpg","jpeg","png"])
                photo_up= st.file_uploader("New Profile Photo", type=["jpg","jpeg","png"])
                if photo_up: st.image(photo_up, width=150, caption="New Photo Preview")

        # ---------- SUBMIT ----------
        save = st.form_submit_button("Update Employee", type="primary")

    # ----------------- SAVE LOGIC -----------------
    if save:
        required_miss = []
        if not fullname.strip(): required_miss.append("Full Name")
        if date_of_birth > TODAY: required_miss.append("Date of Birth")
        if employment_date > TODAY: required_miss.append("Employment Date")
        if required_miss:
            st.error("Please correct: " + ", ".join(required_miss))
            st.stop()

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
        st.success("Employee updated successfully!  New files (if any) uploaded to Supabase.")


# -------------------- NAV / SEARCH TAB (Dashboard concept) -------------------
with tab_view:
    st.markdown("## 👥 Employee Dashboard")

    # ───────────────────────── LEFT SIDEBAR ────────────────────────────────
    with st.sidebar:
        with st.expander("🔎 Filters", expanded=True):
            term = st.text_input("Name / phone / email")
            all_df = get_all_employees()

            dept_opts  = sorted(all_df.department.dropna().unique().tolist())
            state_opts = ["active", "resigned", "terminated"]

            sel_depts  = st.multiselect("Department", dept_opts)
            sel_states = st.multiselect("Status", state_opts, default=["active"])

        # quick metrics
        st.markdown("### 📊 Org Metrics")
        active_count = len(all_df[all_df.employee_state == "active"])
        resigned_cnt = len(all_df[all_df.employee_state == "resigned"])
        terminated_cnt = len(all_df[all_df.employee_state == "terminated"])
        st.metric("Active employees", active_count)
        st.metric("Resigned", resigned_cnt)
        st.metric("Terminated", terminated_cnt)

        # department bar (simple text bar)
        st.markdown("**Employees by Dept.**")
        dept_counts = (
            all_df.groupby("department")["employeeid"].count().sort_values(ascending=False)
        )
        for d, n in dept_counts.items():
            bar = "█" * int(n / dept_counts.max() * 20)
            st.markdown(f"{d or '-'}: {bar} {n}")

    # ──────────────────────── FILTER + DATA QUERY ──────────────────────────
    df = all_df.copy()
    if term:
        mask = (
            df.fullname.str.contains(term, case=False, na=False)
            | df.email.str.contains(term, case=False, na=False)
            | df.phone_no.str.contains(term, case=False, na=False)
        )
        df = df[mask]

    if sel_depts:
        df = df[df.department.isin(sel_depts)]
    if sel_states:
        df = df[df.employee_state.isin(sel_states)]

    df = df.sort_values("fullname").reset_index(drop=True)
    if df.empty:
        st.warning("No employees match these filters."); st.stop()

    # salary map cached
    @st.cache_data(show_spinner=False)
    def _latest_sal():
        return pd.read_sql(
            """SELECT DISTINCT ON (employeeid) employeeid,salary
                 FROM hr_salary_history
                ORDER BY employeeid,effective_from DESC""",
            engine,
        ).set_index("employeeid")["salary"].to_dict()

    sal_map = _latest_sal()

    # ───────────────────────── CENTER PANE (TABLE) ─────────────────────────
    # build compact dataframe just for display
    disp = df[
        ["employeeid", "fullname", "department", "position", "phone_no", "employee_state"]
    ].copy()
    disp["salary"] = disp.employeeid.map(sal_map).fillna(0).astype(int)

    disp.rename(
        columns={
            "fullname": "Name",
            "department": "Dept",
            "position": "Position",
            "phone_no": "Phone",
            "employee_state": "Status",
            "salary": "Salary",
        },
        inplace=True,
    )

    # clickable buttons per row
    disp["View"] = "👁️"
    disp["Edit"] = "✏️"

    # keep selection in session
    sel_key = "emp_sel_dash"
    st.session_state.setdefault(sel_key, int(disp.iloc[0].employeeid))

    # show table
    sel_row = st.data_editor(
        disp,
        column_config={
            "View": st.column_config.Column(width="small"),
            "Edit": st.column_config.Column(width="small"),
            "Salary": st.column_config.NumberColumn(format="Rp {:,.0f}"),
        },
        use_container_width=True,
        hide_index=True,
        on_click="View",            # any click selects that row
        key="emp_table",
    )

    # determine clicked action
    clicked = st.session_state["emp_table"]["clicked_row"]
    if clicked is not None:
        clicked_id = int(disp.iloc[clicked]["employeeid"])
        st.session_state[sel_key] = clicked_id

    # check for button clicks (View / Edit)
    if "emp_table_button" in st.session_state:
        btn_info = st.session_state.pop("emp_table_button")
        row_idx  = btn_info["row_index"]
        action   = btn_info["column"]
        emp_id   = int(disp.iloc[row_idx]["employeeid"])
        st.session_state[sel_key] = emp_id
        if action == "Edit":
            st.switch_page("pages/employee_management.py")  # jumps to Edit tab
        # action == "View" handled by detail card automatically

    # ──────────────────────── RIGHT PANE (DETAIL CARD) ──────────────────────
    st.markdown("---")
    sel_id = st.session_state[sel_key]
    emp = all_df.set_index("employeeid").loc[sel_id]

    detail_left, detail_right = st.columns([1, 2], gap="large")
    with detail_left:
        st.image(
            emp.photo_url or "https://placehold.co/200x200.png?text=No+Photo",
            width=200,
        )
        st.metric("Current salary", f"Rp {sal_map.get(sel_id,0):,.0f}")
    with detail_right:
        st.markdown(f"### {emp.fullname}")
        st.markdown(f"**Department / Position:** {emp.department or '-'} / {emp.position or '-'}")
        st.markdown(f"**Phone:** {emp.phone_no or '-'} • **Email:** {emp.email or '-'}")
        st.markdown(f"**Status:** `{emp.employee_state}`")
        st.markdown(f"**Assurance:** Rp {(emp.assurance or 0):,.0f} ({emp.assurance_state})")
        bio = {
            "Date of Birth": emp.date_of_birth,
            "Employment Date": emp.employment_date,
            "Languages": emp.language,
            "Education": emp.education_degree,
            "Health": emp.health_condition,
            "Family Members": emp.family_members,
            "National ID No": emp.national_id_no,
            "SS Registration": emp.ss_registration_date,
            "Address": emp.address,
        }
        for k, v in bio.items():
            st.markdown(f"**{k}:** {v or '-'}")

    # salary history inside expander
    with st.expander("💰 Salary history"):
        hist = pd.read_sql(
            text(
                "SELECT salary,effective_from,effective_to "
                "FROM hr_salary_history WHERE employeeid=:eid "
                "ORDER BY effective_from DESC"
            ),
            engine,
            params={"eid": sel_id},
        )
        if hist.empty:
            st.info("No salary history.")
        else:
            hist["effective_to"].fillna("Present", inplace=True)
            st.dataframe(hist, hide_index=True, use_container_width=True)

    # downloads
    st.markdown("### 📎 Files")
    if emp.cv_url:
        st.link_button("⬇️ CV", emp.cv_url)
    if emp.national_id_image_url:
        st.link_button("⬇️ National ID", emp.national_id_image_url)
