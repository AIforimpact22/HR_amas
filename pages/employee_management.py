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


# ---------------- TAB 3 · 🔎 Search / Employee Navigator (modal version) -----
with tab_view:
    st.markdown("## 👥 Employee Navigator")

    # ── filter bar ----------------------------------------------------------
    f1, f2, f3 = st.columns([4, 3, 3])
    term = f1.text_input("Search", placeholder="Name / phone / email")

    all_df = get_all_employees()
    dept_opts  = sorted(all_df.department.dropna().unique().tolist())
    state_opts = ["active", "resigned", "terminated"]

    dept_sel  = f2.multiselect("Department", dept_opts)
    state_sel = f3.multiselect("Status", state_opts, default=["active"])

    # ── apply filters ------------------------------------------------------
    df = all_df.copy()
    if term:
        m = (
            df.fullname.str.contains(term, case=False, na=False)
            | df.email.str.contains(term, case=False, na=False)
            | df.phone_no.str.contains(term, case=False, na=False)
        )
        df = df[m]
    if dept_sel:
        df = df[df.department.isin(dept_sel)]
    if state_sel:
        df = df[df.employee_state.isin(state_sel)]

    df = df.sort_values("fullname").reset_index(drop=True)
    if df.empty:
        st.warning("No employees match these filters.")
        st.stop()

    # ── latest salary map (cached) ----------------------------------------
    @st.cache_data(show_spinner=False)
    def _latest_sal():
        return pd.read_sql(
            """SELECT DISTINCT ON (employeeid) employeeid, salary
               FROM hr_salary_history
               ORDER BY employeeid, effective_from DESC""",
            engine,
        ).set_index("employeeid")["salary"].to_dict()

    sal_map = _latest_sal()

    # ── directory as photo-cards grid -------------------------------------
    st.markdown("#### Results")
    cards_per_row = 4
    rows = math.ceil(len(df) / cards_per_row)
    iterator = iter(df.itertuples())

    for _ in range(rows):
        cols = st.columns(cards_per_row, gap="small")
        for col in cols:
            try:
                r = next(iterator)
            except StopIteration:
                col.empty()
                continue

            eid = int(r.employeeid)
            photo = r.photo_url or "https://placehold.co/120x120.png?text=No+Photo"
            col.markdown(
                f"""
                <div style="border:1px solid #ddd;border-radius:8px;padding:10px;text-align:center">
                  <img src="{photo}" style="width:80px;height:80px;border-radius:50%;object-fit:cover">
                  <div style="font-weight:600;margin-top:6px">{r.fullname}</div>
                  <div style="font-size:0.8em;color:#555">{r.position or '-'}<br/>{r.department or '-'}</div>
                  <div style="font-size:0.75em"><code>{r.employee_state}</code></div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if col.button("👁️ Quick View", key=f"view_{eid}", use_container_width=True):
                # ---------- MODAL START -----------------------------------
                with st.modal(f"{r.fullname} — Profile"):
                    # header
                    mdl_l, mdl_r = st.columns([1, 2], gap="large")
                    with mdl_l:
                        st.image(photo, width=200)
                    with mdl_r:
                        st.markdown(f"### {r.fullname}")
                        st.markdown(
                            f"**Dept / Pos:** {r.department or '-'} / {r.position or '-'}"
                        )
                        st.markdown(
                            f"**Phone:** {r.phone_no or '-'} &nbsp;&nbsp; "
                            f"**Email:** {r.email or '-'}"
                        )
                        st.markdown(f"**Status:** `{r.employee_state}`")
                        st.metric(
                            "Current salary",
                            f"Rp {sal_map.get(eid, 0):,.0f}",
                        )

                    # actions
                    act1, act2 = st.columns(2)
                    if act1.button("✏️ Edit", key=f"mdl_edit_{eid}"):
                        st.switch_page("pages/employee_management.py")
                    if act2.button("⬆️ Raise / Cut", key=f"mdl_raise_{eid}"):
                        st.switch_page("pages/employee_salary.py")

                    st.divider()

                    # bio
                    with st.expander("📑 Bio / Employment", expanded=True):
                        bio = {
                            "Date of Birth": r.date_of_birth,
                            "Employment Date": r.employment_date,
                            "Languages": r.language,
                            "Education": r.education_degree,
                            "Health": r.health_condition,
                            "Family Members": r.family_members,
                            "National ID No": r.national_id_no,
                            "SS Registration": r.ss_registration_date,
                            "Assurance": f"Rp {(r.assurance or 0):,.0f} ({r.assurance_state})",
                            "Address": r.address,
                        }
                        for k, v in bio.items():
                            st.markdown(f"**{k}:** {v or '-'}")

                    # salary history
                    with st.expander("💰 Salary history"):
                        hist = pd.read_sql(
                            text(
                                """
                                SELECT salary, effective_from, effective_to
                                  FROM hr_salary_history
                                 WHERE employeeid = :eid
                                 ORDER BY effective_from DESC
                                """
                            ),
                            engine,
                            params={"eid": eid},
                        )
                        if hist.empty:
                            st.info("No records.")
                        else:
                            hist = hist.copy()
                            hist.loc[:, "effective_to"] = (
                                hist["effective_to"]
                                .fillna("Present")
                                .astype(str)
                            )
                            hist.loc[:, "effective_from"] = hist["effective_from"].astype(str)
                            st.dataframe(hist, hide_index=True, use_container_width=True)

                    # files
                    with st.expander("📎 Files"):
                        if r.cv_url:
                            st.link_button("⬇️ CV", r.cv_url)
                        if r.national_id_image_url:
                            st.link_button("⬇️ National ID", r.national_id_image_url)

                # ---------- MODAL END -------------------------------------
