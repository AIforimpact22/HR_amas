st.set_page_config(
    page_title="AMAS HR Management",
    page_icon="👥",
    layout="wide",
)

st.title("👥 AMAS HR Management Portal")

st.markdown(
    """
    Welcome to the **AMAS HR Portal**.

    - View and manage employee records
    - Monitor attendance and approve leaves
    - Review payroll, process complaints, and generate reports

    Use the sidebar to navigate through different HR functions.
    """
)
st.info(
    f"💡 Current time: **{datetime.now():%Y-%m-%d %H:%M:%S}**\n\n"
    "Select a page on the left to get started."
)
