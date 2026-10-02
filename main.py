from __future__ import annotations

import json
import html
import re
import sqlite3
import os
from contextlib import contextmanager
from datetime import date, datetime, time
from pathlib import Path
from typing import Iterator

import streamlit as st

# =====================================================================
# 1. CONFIGURAÇÕES E DIRETÓRIOS GLOBAIS
# =====================================================================
APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "gestao_escolar_v2.db"
APP_TITLE = "🏫 Portal Digital - CI Prefeito Ary Levy Pereira"
UPLOAD_DIR = APP_DIR / "documentos_pdf"

if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

MATRICULAS_PERMITIDAS: dict[str, dict[str, str]] = {
    "adm123": {"role": "Administrador", "name": "Administrador", "email": "direcao@escola.com", "teacher_type": "Regular"},
    "12345": {"role": "Professor", "name": "Regina Mello", "email": "regina@escola.com", "teacher_type": "Regular"},
    "45678": {"role": "Professor", "name": "Paula Souza (AEE)", "email": "paula.aee@escola.com", "teacher_type": "AEE"},
    "00000": {"role": "Monitor", "name": "Inspeção de Pátio", "email": "", "teacher_type": "Regular"},
}

SALAS_CADASTRADAS = (
    "Berçário I",
    "Berçário II",
    "Maternal I",
    "Maternal II - Turma 1",
    "Maternal II - Turma 2",
    "Primeira Etapa - Turma 1",
    "Primeira Etapa - Turma 2",
    "Segunda Etapa - Turma 1",
    "Segunda Etapa - Turma 2",
)

ESPACOS = ("Quadra", "Informática", "Leitura")
STATUS_CHAMADA = ("Presente", "Falta", "Falta justificada")
ADMIN_PAGE = "⚙️ Painel de Controle (Adm)"
PEDAGOGICAL_PAGES = [
    "📢 Quadro de Avisos",
    "📋 Chamada Diária",
    "🧒 Carômetro e Histórico de Alunos",
    "📝 Planejamentos & Atas de Conselho",
    "📅 Calendário de Avaliações",
    "🏢 Agendamento de Espaços",
    "🚨 Ocorrências da Rotina",
]
MONITOR_PAGE = "🔎 Carômetro de Segurança"

BNCC_EXPERIENCES = (
    "O eu, o outro e o nós",
    "Corpo, gestos e movimentos",
    "Traços, sons, cores e formas",
    "Escuta, fala, pensamento e imaginação",
    "Espaços, tempos, quantidades, relações e transformações",
)

OCCURRENCE_TYPES = (
    "Mordida/Arranhão",
    "Queda/Escoriação",
    "Febre/Sintomas de Saúde",
    "Indisposição Alimentar",
    "Outros",
)
OCCURRENCE_SEVERITIES = ("Leve", "Média", "Alta")

AREAS_PEDAGOGICAS = (
    "Linguagem verbal",
    "Linguagem matemática",
    "Indivíduo e sociedade",
    "Linguagens e tecnologias",
    "Artes",
    "Cultura, corpo e movimento",
)

MESES_DO_ANO = (
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"
)

QUINZENAS = ("1ª Quinzena", "2ª Quinzena")
TRIMESTRES = ("1º Trimestre", "2º Trimestre", "3º Trimestre")

# =====================================================================
# 2. CONEXÃO E GERENCIAMENTO DO BANCO DE DADOS (SQLITE3)
# =====================================================================
@contextmanager
def connection_scope() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

def initialize_database() -> None:
    with connection_scope() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS announcements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                audience TEXT NOT NULL,
                body TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reservations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                space TEXT NOT NULL,
                responsible TEXT NOT NULL,
                teacher_name TEXT NOT NULL DEFAULT '',
                teacher_registry TEXT NOT NULL DEFAULT '',
                teacher_email TEXT NOT NULL DEFAULT '',
                group_name TEXT NOT NULL,
                reservation_date TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                purpose TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS aee_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_ref TEXT NOT NULL,
                grade TEXT NOT NULL,
                period TEXT NOT NULL,
                goals TEXT NOT NULL,
                supports TEXT NOT NULL,
                progress TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                teacher_name TEXT NOT NULL DEFAULT '',
                teacher_registry TEXT NOT NULL DEFAULT '',
                teacher_email TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS classrooms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                classroom_id INTEGER NOT NULL REFERENCES classrooms(id),
                allergies TEXT NOT NULL DEFAULT '',
                food_restrictions TEXT NOT NULL DEFAULT '',
                authorized_pickup TEXT NOT NULL DEFAULT '',
                emergency_contact TEXT NOT NULL DEFAULT '',
                avatar TEXT NOT NULL DEFAULT '👶',
                active INTEGER NOT NULL DEFAULT 1,
                faltas_consecutivas INTEGER NOT NULL DEFAULT 0,
                arquivos_pdf TEXT NOT NULL DEFAULT '[]'
            );
            CREATE TABLE IF NOT EXISTS authorized_users (
                registry TEXT PRIMARY KEY,
                role TEXT NOT NULL CHECK(role IN ('Administrador', 'Professor', 'Monitor')),
                full_name TEXT NOT NULL DEFAULT '',
                email TEXT NOT NULL DEFAULT '',
                teacher_type TEXT NOT NULL DEFAULT 'Regular',
                classroom_id INTEGER REFERENCES classrooms(id),
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL REFERENCES students(id),
                attendance_date TEXT NOT NULL,
                status TEXT NOT NULL,
                teacher_name TEXT NOT NULL,
                teacher_registry TEXT NOT NULL,
                teacher_email TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(student_id, attendance_date)
            );
            CREATE TABLE IF NOT EXISTS assessments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                classroom_id INTEGER NOT NULL REFERENCES classrooms(id),
                subject TEXT NOT NULL,
                assessment_type TEXT NOT NULL,
                assessment_date TEXT NOT NULL,
                notes TEXT NOT NULL,
                teacher_name TEXT NOT NULL,
                teacher_registry TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS plans_minutes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_type TEXT NOT NULL,
                record_date TEXT NOT NULL,
                classroom_id INTEGER REFERENCES classrooms(id),
                student_id INTEGER REFERENCES students(id),
                month_name TEXT NOT NULL DEFAULT '',
                quinzena TEXT NOT NULL DEFAULT '',
                trimester TEXT NOT NULL DEFAULT '',
                subject TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                teacher_name TEXT NOT NULL,
                teacher_registry TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS occurrences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL REFERENCES students(id),
                occurrence_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                details TEXT NOT NULL,
                occurrence_date TEXT NOT NULL,
                teacher_name TEXT NOT NULL,
                teacher_registry TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        for room in SALAS_CADASTRADAS:
            connection.execute("INSERT OR IGNORE INTO classrooms (name) VALUES (?)", (room,))
            
        now = datetime.now().isoformat(timespec="minutes")
        for registry, user in MATRICULAS_PERMITIDAS.items():
            connection.execute(
                """
                INSERT OR IGNORE INTO authorized_users
                    (registry, role, full_name, email, teacher_type, active, created_at)
                VALUES (?, ?, ?, ?, ?, 1, ?)
                """,
                (registry, user["role"], user["name"], user["email"], user["teacher_type"], now)
            )

initialize_database()

# =====================================================================
# 3. FUNÇÕES AUXILIARES DE SUPORTE
# =====================================================================
def fetch_all(query: str, parameters: tuple = ()) -> list[sqlite3.Row]:
    with connection_scope() as connection:
        return connection.execute(query, parameters).fetchall()

def fetch_one(query: str, parameters: tuple = ()) -> sqlite3.Row | None:
    with connection_scope() as connection:
        return connection.execute(query, parameters).fetchone()

def format_date(value: str) -> str:
    try:
        return date.fromisoformat(value).strftime("%d/%m/%Y")
    except Exception:
        return value

def delete_record(table_name: str, record_id: int) -> None:
    with connection_scope() as connection:
        connection.execute(f"DELETE FROM {table_name} WHERE id = ?", (record_id,))

def classroom_rows() -> list[sqlite3.Row]:
    rooms = fetch_all("SELECT id, name FROM classrooms")
    return rooms

def classrooms_for_teacher(teacher: dict[str, str | int | None]) -> list[sqlite3.Row]:
    rooms = classroom_rows()
    assigned_classroom = teacher.get("classroom_id")
    if teacher.get("role") == "Professor" and teacher.get("teacher_type") == "Regular" and assigned_classroom is not None:
        return [row for row in rooms if row["id"] == int(assigned_classroom)]
    return rooms

def get_authorized_user(registry: str) -> sqlite3.Row | None:
    return fetch_one(
        "SELECT registry, role, full_name, email, teacher_type, classroom_id, active FROM authorized_users WHERE registry = ?",
        (registry.strip().lower(),)
    )

def decode_plan_content(content: str) -> dict:
    try:
        decoded = json.loads(content)
    except (TypeError, json.JSONDecodeError):
        return {"legacy_text": content}
    return decoded if isinstance(decoded, dict) else {"legacy_text": content}

def registered_teacher_rows() -> list[sqlite3.Row]:
    return fetch_all("SELECT registry, full_name, role FROM authorized_users WHERE active = 1 ORDER BY full_name COLLATE NOCASE")

# =====================================================================
# 4. SISTEMA DE ESCRITA E GRAVAÇÃO DE DADOS (ALUNOS / ATAS / CHAMADA)
# =====================================================================
def add_student(name: str, classroom_id: int, code: str = "", *, allergies: str = "", food_restrictions: str = "", authorized_pickup: str = "", emergency_contact: str = "", avatar: str = "👶") -> str:
    with connection_scope() as connection:
        if not code.strip():
            next_id = connection.execute("SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM students").fetchone()["next_id"]
            code = f"ALU-{next_id:03d}"
        connection.execute(
            """
            INSERT INTO students (code, name, classroom_id, allergies, food_restrictions, authorized_pickup, emergency_contact, avatar)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (code.strip().upper(), name.strip(), classroom_id, allergies.strip(), food_restrictions.strip(), authorized_pickup.strip(), emergency_contact.strip(), avatar.strip() or "👶")
        )
    return code.strip().upper()

def update_student(student_id: int, name: str, classroom_id: int, allergies: str, food_restrictions: str, authorized_pickup: str, emergency_contact: str, avatar: str, active: bool) -> None:
    with connection_scope() as connection:
        connection.execute(
            """
            UPDATE students SET name = ?, classroom_id = ?, allergies = ?, food_restrictions = ?, authorized_pickup = ?, emergency_contact = ?, avatar = ?, active = ?
            WHERE id = ?
            """,
            (name.strip(), classroom_id, allergies.strip(), food_restrictions.strip(), authorized_pickup.strip(), emergency_contact.strip(), avatar.strip() or "👶", int(active), student_id)
        )

def save_attendance(student_statuses: dict[int, str], attendance_date: date, teacher: dict[str, str]) -> None:
    now = datetime.now().isoformat(timespec="minutes")
    with connection_scope() as connection:
        for student_id, status in student_statuses.items():
            connection.execute(
                """
                INSERT INTO attendance (student_id, attendance_date, status, teacher_name, teacher_registry, teacher_email, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(student_id, attendance_date) DO UPDATE SET
                    status = excluded.status, teacher_name = excluded.teacher_name, teacher_registry = excluded.teacher_registry, created_at = excluded.created_at
                """,
                (student_id, attendance_date.isoformat(), status, teacher["name"], teacher["registry"], teacher.get("email", ""), now)
            )
            if status == "Presente":
                connection.execute("UPDATE students SET faltas_consecutivas = 0 WHERE id = ?", (student_id,))
            else:
                connection.execute("UPDATE students SET faltas_consecutivas = faltas_consecutivas + 1 WHERE id = ?", (student_id,))

def save_assessment(title: str, classroom_id: int, subject: str, assessment_type: str, assessment_date: date, notes: str, teacher: dict[str, str]) -> None:
    with connection_scope() as connection:
        connection.execute(
            """
            INSERT INTO assessments (title, classroom_id, subject, assessment_type, assessment_date, notes, teacher_name, teacher_registry, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (title.strip(), classroom_id, subject.strip(), assessment_type, assessment_date.isoformat(), notes.strip(), teacher["name"], teacher["registry"], datetime.now().isoformat(timespec="minutes"))
        )

def save_plan_or_minutes(record_type: str, record_date: date, classroom_id: int | None, subject: str, title: str, content: str, teacher: dict[str, str], month_name: str = "", quinzena: str = "", trimester: str = "", student_id: int | None = None) -> int:
    with connection_scope() as connection:
        cursor = connection.execute(
            """
            INSERT INTO plans_minutes (record_type, record_date, classroom_id, student_id, month_name, quinzena, trimester, subject, title, content, teacher_name, teacher_registry, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (record_type, record_date.isoformat(), classroom_id, student_id, month_name, quinzena, trimester, subject.strip(), title.strip(), content.strip(), teacher["name"], teacher["registry"], datetime.now().isoformat(timespec="minutes"))
        )
        return int(cursor.lastrowid)

def save_occurrence(student_id: int, occurrence_type: str, severity: str, details: str, occurrence_date: date, teacher: dict[str, str]) -> None:
    with connection_scope() as connection:
        connection.execute(
            """
            INSERT INTO occurrences (student_id, occurrence_type, severity, details, occurrence_date, teacher_name, teacher_registry, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (student_id, occurrence_type, severity, details.strip(), occurrence_date.isoformat(), teacher["name"], teacher["registry"], datetime.now().isoformat(timespec="minutes"))
        )

def complete_teacher_profile(registry: str, name: str, email: str) -> None:
    with connection_scope() as connection:
        connection.execute(
            "UPDATE authorized_users SET full_name = ?, email = ? WHERE registry = ?",
            (name.strip(), email.strip().lower(), registry.strip().lower())
        )

def students_in_classroom(classroom_id: int) -> list[sqlite3.Row]:
    return fetch_all(
        """
        SELECT students.id, students.code, students.name, students.classroom_id, students.allergies, students.food_restrictions, students.authorized_pickup, students.emergency_contact, students.avatar, students.active, classrooms.name AS classroom
        FROM students JOIN classrooms ON classrooms.id = students.classroom_id
        WHERE classrooms.id = ? AND students.active = 1 ORDER BY students.name
        """,
        (classroom_id,)
    )

def save_announcement(title: str, category: str, audience: str, body: str) -> None:
    with connection_scope() as connection:
        connection.execute(
            "INSERT INTO announcements (title, category, audience, body, created_at) VALUES (?, ?, ?, ?, ?)",
            (title.strip(), category, audience, body.strip(), datetime.now().isoformat(timespec="minutes"))
        )

# =====================================================================
# 5. GERADORES DE TEMPLATES VISUAIS EM HTML (IMPRESSÃO DA ATA)
# =====================================================================
def build_minutes_print_html(row: sqlite3.Row, teachers: list[sqlite3.Row]) -> str:
    payload = decode_plan_content(row["content"])
    subject_reports = payload.get("subject_reports", {})
    if not isinstance(subject_reports, dict):
        subject_reports = {}
        
    subject_sections = "".join(
        f"<div style='margin-bottom: 15px;'><b>📌 Componente: {html.escape(area)}</b>"
        f"<p style='margin: 5px 0 15px 0; text-align: justify;'>{html.escape(str(subject_reports.get(area, 'Sem apontamentos.'))).replace(chr(10), '<br>')}</p></div>"
        for area in AREAS_PEDAGOGICAS
    )
    
    signatures = []
    for row_teacher in teachers:
        if row_teacher["role"] in ["Professor", "Administrador"]:
            signatures.append(f"<p style='margin-bottom: 25px;'>✍️ <b>{html.escape(row_teacher['full_name'].upper())}</b> ____________________________________</p>")
    signatures_html = "".join(signatures)
    
    trimester = row["trimester"] or payload.get("trimestre", "")
    html_content = f"""
    <div id="documento-ata-{row['id']}" style="border: 2px solid #333; padding: 30px; background-color: #fff; color: #111; font-family: 'Courier New', monospace; max-width: 800px; margin: auto;">
        <h2 style="text-align: center; margin-bottom: 5px;">ATA DE CONSELHO DE CLASSE CONSOLIDADA</h2>
        <p style="text-align: center; font-size: 14px; margin-top: 0;"><b>{html.escape(trimester.upper())}</b> | TURMA: {html.escape(row['classroom'] if row['classroom'] else 'Geral').upper()}</p>
        <p style="font-size: 13px;"><b>Coordenador Responsável:</b> {html.escape(row['teacher_name'])}</p>
        <hr style="border-top: 1px solid #333; margin-bottom: 20px;">
        {subject_sections}
        <br><hr style="border-top: 1px solid #333;"><h4>✍️ ASSINATURAS DOS PROFESSORES INTEGRADOS:</h4><br>
        {signatures_html}
    </div>
    """
    return html_content
def render_login() -> None:
    st.title(APP_TITLE)
    st.subheader("Acesso ao sistema")
    st.caption("Informe sua matrícula e os dados solicitados para entrar.")
    with st.form("teacher_login_form"):
        teacher_name = st.text_input("Nome completo")
        teacher_registry = st.text_input("Matrícula da Prefeitura", type="password")
        teacher_email = st.text_input("E-mail corporativo")
        login_submitted = st.form_submit_button("Acessar", type="primary")

    if login_submitted:
        normalized_registry = teacher_registry.strip().lower()
        account = get_authorized_user(normalized_registry)
        if not normalized_registry or account is None or not account["active"]:
            st.error("Matrícula não cadastrada ou inativa. Solicite suporte à direção.")
        else:
            resolved_name = account["full_name"] or teacher_name.strip()
            resolved_email = account["email"] or teacher_email.strip()
            complete_teacher_profile(normalized_registry, resolved_name, resolved_email)
            st.session_state["teacher_profile"] = {
                "name": resolved_name,
                "registry": account["registry"],
                "email": resolved_email,
                "role": account["role"],
                "teacher_type": account["teacher_type"],
                "classroom_id": account["classroom_id"]
            }
            st.success("Conectado com sucesso!")
            st.rerun()

def render_announcements() -> None:
    st.subheader("Quadro de Avisos")
    with st.form("announcement_form", clear_on_submit=True):
        title = st.text_input("Título", max_chars=120)
        col1, col2 = st.columns(2)
        category = col1.selectbox("Categoria", ["Comunicado", "Evento", "Reunião", "Prazo", "Outro"])
        audience = col2.selectbox("Público", ["Toda a comunidade", "Estudantes", "Famílias", "Equipe escolar"])
        body = st.text_area("Mensagem", height=120)
        submitted = st.form_submit_button("Publicar aviso", type="primary")
        
    if submitted:
        if not title.strip() or not body.strip():
            st.error("Informe o título e a mensagem do aviso.")
        else:
            save_announcement(title, category, audience, body)
            st.success("Aviso publicado.")

    st.divider()
    announcements = fetch_all("SELECT * FROM announcements ORDER BY created_at DESC, id DESC")
    for row in announcements:
        with st.container(border=True):
            st.markdown(f"### {row['title']}")
            st.caption(f"{row['category']} · {row['audience']} · {row['created_at']}")
            st.write(row["body"])
            if st.button("Excluir aviso", key=f"del_ann_{row['id']}"):
                delete_record("announcements", row["id"])
                st.rerun()

def render_daily_attendance(teacher: dict[str, str]) -> None:
    st.subheader("📋 Chamada Diária e Controle de Evasão")
    rooms = classrooms_for_teacher(teacher)
    room_names = [row["name"] for row in rooms]
    selected_room = st.selectbox("Selecione a Sala de Aula:", room_names)
    classroom_id = next(row["id"] for row in rooms if row["name"] == selected_room)
    attendance_date = st.date_input("Data da chamada", value=date.today())
    students = students_in_classroom(classroom_id)
    
    with st.form("daily_attendance_form"):
        statuses: dict[int, str] = {}
        for student in students:
            statuses[student["id"]] = st.selectbox(f"👤 {student['name']} (Código: {student['code']})", STATUS_CHAMADA)
        submitted = st.form_submit_button("💾 Gravar Frequência da Sala", type="primary")
        
    if submitted:
        save_attendance(statuses, attendance_date, teacher)
        st.success("Frequência enviada e consolidada no histórico escolar!")
        st.rerun()

def render_minutes_and_plans(teacher: dict[str, str]) -> None:
    st.subheader("📝 Gestão de Atas por Matéria e Planejamentos")
    rooms = classrooms_for_teacher(teacher)
    room_names = [row["name"] for row in rooms]
    selected_room = st.selectbox("Selecione a Sala:", room_names, key="plan_room")
    classroom_id = next(row["id"] for row in rooms if row["name"] == selected_room)
    
    with st.form("form_ata_materias", clear_on_submit=True):
        trimestre = st.selectbox("Trimestre Letivo:", TRIMESTRES)
        st.write("### Deliberações Separadas por Matéria:")
        reports = {}
        for area in AREAS_PEDAGOGICAS:
            reports[area] = st.text_area(f"📌 Parecer Coletivo: {area}")
            
        if st.form_submit_button("📝 Protocolar e Consolidar Ata"):
            content_json = json.dumps({"subject_reports": reports})
            save_plan_or_minutes("Ata", date.today(), classroom_id, "Geral", f"Conselho de Classe {trimestre}", content_json, teacher, trimester=trimestre)
            st.success("Ata protocolada!")
            st.rerun()
            
    st.divider()
    st.subheader("🖨️ Histórico de Atas Prontas para Impressão")
    atas = fetch_all(
        """
        SELECT plans_minutes.*, classrooms.name AS classroom 
        FROM plans_minutes 
        LEFT JOIN classrooms ON classrooms.id = plans_minutes.classroom_id 
        WHERE record_type = 'Ata' AND classroom_id = ? 
        ORDER BY id DESC
        """, 
        (classroom_id,)
    )
    teachers = registered_teacher_rows()
    
    for row in atas:
        with st.container(border=True):
            html_content = build_minutes_print_html(row, teachers)
            st.html(html_content)
            st.button(
                "🖨️ Abrir Janela de Impressão (Salvar como PDF)", 
                key=f"print_{row['id']}", 
                on_click=lambda h=html_content: st.html(f"<script>var win = window.open('', '_blank'); win.document.write({json.dumps(h)}); win.document.close(); win.print();</script>")
            )

def render_assessment_calendar(teacher: dict[str, str]) -> None:
    st.subheader("📅 Calendário de Avaliações")
    rooms = classroom_rows()
    with st.form("assessment_form", clear_on_submit=True):
        title = st.text_input("Avaliação", placeholder="Ex.: Avaliação de leitura")
        col1, col2, col3 = st.columns(3)
        room_name = col1.selectbox("Sala", [row["name"] for row in rooms])
        subject = col2.text_input("Componente curricular")
        assessment_type = col3.selectbox("Tipo", ["Prova", "Trabalho", "Apresentação", "Recuperação", "Outro"])
        assessment_date = st.date_input("Data", value=date.today())
        notes = st.text_area("Orientações para a turma", height=90)
        submitted = st.form_submit_button("Adicionar avaliação", type="primary")
        
    if submitted:
        if not title.strip() or not subject.strip():
            st.error("Preencha o nome da avaliação e o componente curricular.")
        else:
            classroom_id = next(row["id"] for row in rooms if row["name"] == room_name)
            save_assessment(title, classroom_id, subject, assessment_type, assessment_date, notes, teacher)
            st.success("Avaliação adicionada ao calendário.")

    rows = fetch_all(
        """
        SELECT assessments.*, classrooms.name AS classroom 
        FROM assessments 
        JOIN classrooms ON classrooms.id = assessments.classroom_id 
        ORDER BY assessments.assessment_date DESC
        """
    )
    st.divider()
    if rows:
        st.dataframe(
            [{"Data": format_date(r["assessment_date"]), "Sala": r["classroom"], "Avaliação": r["title"], "Componente": r["subject"], "Tipo": r["assessment_type"]} for r in rows], 
            use_container_width=True, 
            hide_index=True
        )

def render_aee_and_pdf_uploads(teacher: dict[str, str]) -> None:
    st.subheader("🧩 Atendimento Educacional Especializado (AEE)")
    aba_aee = st.radio("Escolha a Operação:", ["Anexar Arquivo PDF Externo / Laudo", "Histórico de Prontuários e PDFs"], horizontal=True)
    
    if aba_aee == "Anexar Arquivo PDF Externo / Laudo":
        all_students = fetch_all("SELECT id, name FROM students WHERE active = 1")
        student_sel = st.selectbox("Selecione o Aluno para Vincular o PDF:", [r["name"] for r in all_students])
        arquivo_enviado = st.file_uploader("Escolha o arquivo PDF do Laudo/PEI:", type=["pdf"])
        nome_doc = st.text_input("Identificação do Documento (Ex: Laudo Fonoaudiologia 2026):")
        
        if st.button("➕ Enviar e Salvar PDF no Prontuário"):
            if arquivo_enviado is not None and nome_doc.strip():
                nome_limpo = f"{student_sel.replace(' ', '')}{nome_doc.replace(' ', '_')}.pdf"
                caminho_salvamento = os.path.join(str(UPLOAD_DIR), nome_limpo)
                with open(caminho_salvamento, "wb") as f:
                    f.write(arquivo_enviado.getbuffer())
                    
                student_id = next(r["id"] for r in all_students if r["name"] == student_sel)
                student_row = fetch_one("SELECT arquivos_pdf FROM students WHERE id = ?", (student_id,))
                lista_pdf = json.loads(student_row["arquivos_pdf"] if student_row["arquivos_pdf"] else "[]")
                lista_pdf.append({"nome": nome_doc, "data": date.today().strftime("%d/%m/%Y"), "caminho": caminho_salvamento})
                
                with connection_scope() as conn:
                    conn.execute("UPDATE students SET arquivos_pdf = ? WHERE id = ?", (json.dumps(lista_pdf), student_id))
                st.success("Arquivo PDF anexado com sucesso!")
                st.rerun()

    elif aba_aee == "Histórico de Prontuários e PDFs":
        all_students = fetch_all("SELECT id, name, allergies, food_restrictions, authorized_pickup, emergency_contact, arquivos_pdf FROM students WHERE active = 1")
        if all_students:
            student_sel = st.selectbox("Selecione o Aluno para Consulta Completa:", [r["name"] for r in all_students])
            aluno = next(r for r in all_students if r["name"] == student_sel)
            
            st.markdown(f"### Ficha de Saúde Global: {aluno['name']}")
            st.write(f"🔴 **Alergias:** {aluno.get('allergies','Nenhuma')}")
            st.write(f"🥛 **Restrições:** {aluno.get('food_restrictions','Nenhuma')}")
            st.write(f"🪪 **Retirada:** {aluno.get('authorized_pickup','Não informado')}")
            st.write(f"📞 **Contato de Emergência:** {aluno.get('emergency_contact','Não informado')}")
            
            pdfs = json.loads(aluno["arquivos_pdf"] if aluno["arquivos_pdf"] else "[]")
            if pdfs:
                st.write("---")
                st.subheader("📁 Arquivos PDF Anexados no Prontuário Escolar")
                for doc in pdfs:
                    with st.container(border=True):
                        c1, c2 = st.columns([3, 1])
                        c1.write(f"📄 {doc['nome']} (Anexado em {doc['data']})")
                        if os.path.exists(doc["caminho"]):
                            with open(doc["caminho"], "rb") as f_pdf:
                                c2.download_button(
                                    "📥 Abrir PDF", 
                                    data=f_pdf.read(), 
                                    file_name=os.path.basename(doc["caminho"]), 
                                    mime="application/pdf", 
                                    key=doc["caminho"]
                                )
def render_admin_dashboard() -> None:
    st.header("⚙️ Painel Administrativo de Controle Geral")
    aba_gerencia = st.radio("Escolha a Ação Administrativa:", ["👥 Cadastrar/Editar Funcionários", "👶 Matricular Novo Aluno no Carômetro"], horizontal=True)
    rooms = classroom_rows()
    
    if aba_gerencia == "👥 Cadastrar/Editar Funcionários":
        with st.form("form_add_teacher"):
            st.write("### Vincular Nova Matrícula Autorizada")
            t_mat = st.text_input("Matrícula (Código de Acesso)")
            t_nome = st.text_input("Nome Completo")
            t_cargo = st.selectbox("Cargo Escolar:", ["Professor", "Monitor", "Administrador"])
            t_type = st.selectbox("Segmento (Se Professor):", ["Regular", "AEE"])
            t_sala = st.selectbox("Sala Atribuída:", [r["name"] for r in rooms])
            if st.form_submit_button("➕ Salvar Funcionário"):
                sala_id = next(r["id"] for r in rooms if r["name"] == t_sala)
                with connection_scope() as conn:
                    conn.execute(
                        "INSERT OR IGNORE INTO authorized_users (registry, role, full_name, email, teacher_type, classroom_id, active, created_at) VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
                        (t_mat.strip().lower(), t_cargo, t_nome.strip(), "", t_type, sala_id, datetime.now().isoformat(timespec="minutes"))
                    )
                st.success("Funcionário integrado com sucesso!")
                st.rerun()

    elif aba_gerencia == "👶 Matricular Novo Aluno no Carômetro":
        with st.form("form_adm_aluno"):
            st.write("### Ficha de Matrícula e Saúde Geral Infantil")
            a_nome = st.text_input("Nome Completo da Criança:")
            a_sala = st.selectbox("Sala Escolar:", [r["name"] for r in rooms])
            a_alergias = st.text_input("Alergias / Restrições Médicas:", value="Nenhuma")
            a_restricoes = st.text_input("Restrições Alimentares (Ex: Lactose):", value="Nenhuma")
            a_retirada = st.text_input("Pessoas Autorizadas para Retirada (Nome/Parentesco):")
            a_contato = st.text_input("Telefones de Emergência dos Pais:")
            
            if st.form_submit_button("➕ Gravar e Matricular"):
                if a_nome.strip():
                    sala_id = next(r["id"] for r in rooms if r["name"] == a_sala)
                    add_student(a_nome, sala_id, allergies=a_alergias, food_restrictions=a_restricoes, authorized_pickup=a_retirada, emergency_contact=a_contato)
                    st.success("Criança matriculada e inserida de forma vitalícia no banco de dados!")
                    st.rerun()

# =====================================================================
# 8. ROTEAMENTO DE SESSÃO E PÁGINAS PRINCIPAIS
# =====================================================================
if "teacher_profile" not in st.session_state:
    render_login()
else:
    prof = st.session_state["teacher_profile"]
    st.sidebar.markdown(f"### 👤 {prof['name']}")
    st.sidebar.caption(f"Cargo: {prof['role']} | Acesso: {prof['registry']}")
    if st.sidebar.button("🚪 Sair do Sistema"):
        del st.session_state["teacher_profile"]
        st.rerun()
        
    st.sidebar.divider()
      # 🚨 REGRA CRÍTICA DE EVASÃO: ALERTA VERMELHO DE BUSCA ATIVA PARA A DIREÇÃO
    st.subheader("🚨 Central Escolar de Alertas Críticos (Evasão)")
    evasao_rows = fetch_all(
        """
        SELECT students.name, students.classroom_id, students.faltas_consecutivas, students.emergency_contact
        FROM students 
        WHERE students.faltas_consecutivas >= 3
        """
    )
    if evasao_rows:
        for ev in evasao_rows:
            st.error(f"⚠️ **RISCO DE EVASÃO DETECTADO:** A criança **{ev['name']}** acumulou {ev['faltas_consecutivas']} faltas consecutivas! Telefone de contato dos pais para busca ativa imediata: {ev['emergency_contact']}")
    else:
        st.success("✅ Nenhuma evasão detectada nas salas de Educação Infantil.")
    st.divider()
  

    # Roteamento administrativo ou pedagógico com base no cargo autenticado
    if prof["role"] == "Administrador":
        menu_escolha = st.sidebar.radio("Navegar para:", [ADMIN_PAGE] + PEDAGOGICAL_PAGES)
        if menu_escolha == ADMIN_PAGE: render_admin_dashboard()
        elif menu_escolha == "📢 Quadro de Aviso": render_announcements()
        elif menu_escolha == "📋 Chamada Diária": render_daily_attendance(prof)
        elif menu_escolha == "📝 Planejamentos & Atas de Conselho": render_minutes_and_plans(prof)
        elif menu_escolha == "📅 Calendário de Avaliações": render_assessment_calendar(prof)
        elif menu_escolha == "🧒 Carômetro e Histórico de Alunos": render_aee_and_pdf_uploads(prof)
        else: st.info("Módulo pedagógico em desenvolvimento estrutural.")
        
    elif prof["role"] == "Professor":
        menu_escolha = st.sidebar.radio("Navegar para:", PEDAGOGICAL_PAGES)
        if menu_escolha == "📢 Quadro de Avisos": render_announcements()
        elif menu_escolha == "📋 Chamada Diária": render_daily_attendance(prof)
        elif menu_escolha == "📝 Planejamentos & Atas de Conselho": render_minutes_and_plans(prof)
        elif menu_escolha == "📅 Calendário de Avaliações": render_assessment_calendar(prof)
        elif menu_escolha == "🧒 Carômetro e Histórico de Alunos": render_aee_and_pdf_uploads(prof)
        else: st.info("Acesse a aba selecionada na barra lateral para iniciar os lançamentos da rotina.")
        
    elif prof["role"] == "Monitor":
        st.title(MONITOR_PAGE)
        render_aee_and_pdf_uploads(prof)
