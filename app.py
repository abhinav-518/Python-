import re
import sqlite3
from datetime import date
from io import BytesIO
from xml.sax.saxutils import escape

import streamlit as st
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

DB_FILE = "requisitions.db"

APPLICATION_TYPES = [
    "Bonafide", "Student Certificate", "Scholarship", "NOC",
    "Academic Permission", "Examination", "Internship", "Placement",
    "Other Request",
]

# TODO: replace with the exact declaration text printed on the institute's form.
DECLARATION = (
    "I hereby declare that the information furnished above is true and correct "
    "to the best of my knowledge. I understand that any false information may "
    "lead to rejection of my request and disciplinary action."
)

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
MOBILE_RE = re.compile(r"^(\+91[- ]?)?[6-9]\d{9}$")  # Indian 10-digit mobile


# ---------------------------------------------------------------- storage
def init_db():
    with sqlite3.connect(DB_FILE) as con:
        con.execute(
            """CREATE TABLE IF NOT EXISTS requisitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                req_no TEXT, department TEXT, student_name TEXT, roll_no TEXT,
                semester TEXT, division TEXT, contact TEXT, app_type TEXT,
                purpose TEXT, docs_attached TEXT, doc_names TEXT,
                req_date TEXT, status TEXT DEFAULT 'Submitted'
            )"""
        )


def save_record(d):
    with sqlite3.connect(DB_FILE) as con:
        cur = con.execute(
            """INSERT INTO requisitions (department, student_name, roll_no,
               semester, division, contact, app_type, purpose, docs_attached,
               doc_names, req_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (d["department"], d["name"], d["roll"], d["semester"], d["division"],
             d["contact"], d["app_type"], d["purpose"], d["docs_attached"],
             d["doc_names"], d["date"]),
        )
        req_no = f"REQ-{date.today().year}-{cur.lastrowid:04d}"
        con.execute("UPDATE requisitions SET req_no=? WHERE id=?",
                    (req_no, cur.lastrowid))
    return req_no


def fetch_all():
    with sqlite3.connect(DB_FILE) as con:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute(
            "SELECT * FROM requisitions ORDER BY id DESC")]


# ---------------------------------------------------------------- validation
def validate(d, declared):
    errors = []
    required = {
        "department": "Name of Department", "name": "Student Name",
        "roll": "Roll Number", "semester": "Semester", "division": "Division",
        "contact": "Email / Mobile Number", "purpose": "Purpose / Details",
    }
    for key, label in required.items():
        if not d[key].strip():
            errors.append(f"{label} is required.")
    c = d["contact"].strip()
    if c:
        if "@" in c:
            if not EMAIL_RE.match(c):
                errors.append("Email address is not valid.")
        else:
            digits = re.sub(r"[\s-]", "", c)
            if not MOBILE_RE.match(digits):
                errors.append("Mobile number must be a valid 10-digit number.")
    if d["docs_attached"] == "Yes" and not d["doc_names"].strip():
        errors.append("Enter the name(s) of the supporting document(s).")
    if not declared:
        errors.append("You must accept the student declaration.")
    return errors


# ---------------------------------------------------------------- PDF
def build_pdf(d, req_no):
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm,
                            rightMargin=15 * mm, topMargin=10 * mm,
                            bottomMargin=10 * mm)
    ss = getSampleStyleSheet()
    title = ParagraphStyle("t", parent=ss["Title"], fontSize=15, spaceAfter=2)
    sub = ParagraphStyle("s", parent=ss["Normal"], alignment=1, fontSize=10)
    cell = ParagraphStyle("c", parent=ss["Normal"], fontSize=9.5, leading=12)
    bold = ParagraphStyle("b", parent=cell, fontName="Helvetica-Bold")
    head = ParagraphStyle("h", parent=bold, textColor=colors.white)

    P = lambda t, s=cell: Paragraph(escape(str(t)).replace("\n", "<br/>"), s)
    W = A4[0] - 30 * mm
    grid = [("GRID", (0, 0), (-1, -1), 0.7, colors.black),
            ("VALIGN", (0, 0), (-1, -1), "TOP")]

    def section(label):
        t = Table([[P(label, head)]], colWidths=[W])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#333333")),
                               ("GRID", (0, 0), (-1, -1), 0.7, colors.black)]))
        return t

    def kv(rows, widths):
        t = Table(rows, colWidths=widths)
        t.setStyle(TableStyle(grid))
        return t

    el = [P("STUDENT ACADEMIC REQUISITION FORM", title),
          P("Institute Name / Address (as per official form)", sub),
          Spacer(1, 3 * mm)]

    el.append(kv([[P("Requisition No.", bold), P(req_no),
                   P("Date", bold), P(d["date"])]],
                 [35 * mm, W / 2 - 35 * mm, 20 * mm, W / 2 - 20 * mm]))

    # Student details
    el += [section("A. STUDENT DETAILS"),
           kv([[P("Name of Department", bold), P(d["department"])],
               [P("Student Name", bold), P(d["name"])],
               [P("Roll Number", bold), P(d["roll"])],
               [P("Semester / Division", bold), P(f'{d["semester"]} / {d["division"]}')],
               [P("Email / Mobile", bold), P(d["contact"])]],
              [50 * mm, W - 50 * mm])]

    # Application type
    boxes = [("[X] " if t == d["app_type"] else "[   ] ") + t
             for t in APPLICATION_TYPES]
    rows = [[P(b) for b in boxes[i:i + 3]] + [""] * (3 - len(boxes[i:i + 3]))
            for i in range(0, len(boxes), 3)]
    el += [section("B. APPLICATION TYPE"), kv(rows, [W / 3] * 3)]

    # Purpose
    t = Table([[P(d["purpose"])]], colWidths=[W], rowHeights=[None])
    t.setStyle(TableStyle(grid + [("BOTTOMPADDING", (0, 0), (-1, -1), 22)]))
    el += [section("C. PURPOSE / BRIEF DETAILS OF REQUEST"), t]

    # Supporting documents
    yes = d["docs_attached"] == "Yes"
    el += [section("D. SUPPORTING DOCUMENTS"),
           kv([[P("Attached"), P(("[X] Yes   [   ] No") if yes else "[   ] Yes   [X] No")],
               [P("Name of document(s)", bold), P(d["doc_names"] if yes else "—")]],
              [50 * mm, W - 50 * mm])]

    # Declaration
    el += [section("E. STUDENT DECLARATION"),
           kv([[P(DECLARATION)],
               [P(f'[X] Declaration accepted by {d["name"]} on {d["date"]}')]],
              [W]),
           kv([[P("Student Signature", bold), P("")]],
              [50 * mm, W - 50 * mm])]
    el[-1].setStyle(TableStyle(grid + [("BOTTOMPADDING", (0, 0), (-1, -1), 18)]))

    # Official use (left blank)
    blank = lambda label, h=28: (P(label, bold), "")
    hod = Table([[P(*[ "HoD Remarks", bold]), ""], [P("HoD Signature", bold), ""],
                 [P("Forwarded To", bold), ""], [P("Signature / Remarks", bold), ""]],
                colWidths=[50 * mm, W - 50 * mm],
                rowHeights=[18 * mm, 12 * mm, 9 * mm, 12 * mm])
    hod.setStyle(TableStyle(grid))
    pr = Table([[P("Principal Decision", bold), P("[   ] Approved    [   ] Rejected    [   ] Hold")],
                [P("Principal Remarks", bold), ""], [P("Principal Signature", bold), ""]],
               colWidths=[50 * mm, W - 50 * mm],
               rowHeights=[9 * mm, 16 * mm, 12 * mm])
    pr.setStyle(TableStyle(grid))
    el += [section("F. FOR HoD USE"), hod, section("G. FOR PRINCIPAL OFFICE USE"), pr]

    doc.build(el)
    return buf.getvalue()


def safe(s):
    return re.sub(r"[^A-Za-z0-9]+", "_", s.strip()).strip("_")


# ---------------------------------------------------------------- UI
st.set_page_config(page_title="Student Academic Requisition", page_icon="📄")
init_db()
st.title("📄 Student Academic Requisition Form")
tab_form, tab_admin = st.tabs(["Requisition Form", "Admin Dashboard"])

with tab_form:
    with st.form("req_form"):
        department = st.text_input("Name of Department")
        c1, c2 = st.columns(2)
        name = c1.text_input("Student Name")
        roll = c2.text_input("Roll Number")
        c3, c4 = st.columns(2)
        semester = c3.selectbox("Semester", [str(i) for i in range(1, 9)])
        division = c4.text_input("Division")
        contact = st.text_input("Email / Mobile Number")
        app_type = st.radio("Application Type", APPLICATION_TYPES, horizontal=True)
        purpose = st.text_area("Purpose / Brief Details of Request")
        docs_attached = st.radio("Supporting documents attached?", ["No", "Yes"],
                                 horizontal=True)
        doc_names = st.text_input("Name of supporting document(s)")
        req_date = st.date_input("Date", value=date.today())
        st.markdown("**Student Declaration**")
        st.info(DECLARATION)
        declared = st.checkbox("I confirm the above declaration")
        submitted = st.form_submit_button("Generate PDF")

    if submitted:
        data = dict(department=department, name=name, roll=roll,
                    semester=semester, division=division, contact=contact,
                    app_type=app_type, purpose=purpose,
                    docs_attached=docs_attached, doc_names=doc_names,
                    date=req_date.strftime("%d-%m-%Y"))
        errs = validate(data, declared)
        if errs:
            st.session_state.pop("pdf", None)
            for e in errs:
                st.error(e)
        else:
            req_no = save_record(data)
            st.session_state["pdf"] = build_pdf(data, req_no)
            st.session_state["fname"] = f"Requisition_{safe(roll)}_{safe(name)}.pdf"
            st.session_state["req_no"] = req_no

    if "pdf" in st.session_state:
        st.success(f"Requisition {st.session_state['req_no']} saved. PDF is ready.")
        st.download_button("Download PDF", st.session_state["pdf"],
                           file_name=st.session_state["fname"],
                           mime="application/pdf")

with tab_admin:
    rows = fetch_all()
    q = st.text_input("Search (name, roll no, requisition no, type)")
    if q:
        rows = [r for r in rows if q.lower() in " ".join(map(str, r.values())).lower()]
    st.dataframe(rows, use_container_width=True)
