from __future__ import annotations

import json
import html
import re
import sqlite3
import subprocess
from contextlib import contextmanager
from datetime import date, datetime, time
from pathlib import Path
from typing import Iterator

import streamlit as st


APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "gestao_escolar.db"
APP_TITLE = "🏫 Portal Digital - CI Prefeito Ary Levy Pereira"

# Matrículas iniciais. Professores adicionais são persistidos pelo painel administrativo.
# Troque as matrículas de demonstração antes de usar o sistema com dados reais.
MATRICULAS_PERMITIDAS: dict[str, dict[str, str]] = {
    "adm123": {"role": "Administrador", "name": "Administrador", "email": "", "teacher_type": "Regular"},
    "12345": {"role": "Professor", "name": "", "email": "", "teacher_type": "Regular"},
    "67890": {"role": "Professor", "name": "", "email": "", "teacher_type": "Regular"},
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
ALUNOS_DE_EXEMPLO = (
    ("ALU-001", "Lia Monteiro", "Berçário I"),
    ("ALU-002", "Caio Nunes", "Berçário I"),
    ("ALU-003", "Ravi Oliveira", "Maternal I"),
    ("ALU-004", "Bia Martins", "Maternal I"),
    ("ALU-005", "Maya Ferreira", "Primeira Etapa - Turma 1"),
    ("ALU-006", "Davi Santos", "Primeira Etapa - Turma 1"),
)
ESPACOS = ("Quadra", "Informática", "Leitura")
STATUS_CHAMADA = ("Presente", "Falta", "Falta justificada")
ADMIN_PAGE = "⚙️ Painel de Controle (Adm)"
PEDAGOGICAL_PAGES = [
    "📋 Chamada Diária",
    "🧒 Carômetro e Histórico de Alunos",
    "📝 Planejamentos & Atas de Conselho",
    "🏢 Agendamento de Espaços",
]
AREAS_PEDAGOGICAS = (
    "Linguagem verbal",
    "Linguagem matemática",
    "Indivíduo e sociedade",
    "Linguagens e tecnologias",
    "Artes",
    "Cultura, corpo e movimento",
)
MESES_DO_ANO = (
    "Janeiro",
    "Fevereiro",
    "Março",
    "Abril",
    "Maio",
    "Junho",
    "Julho",
    "Agosto",
    "Setembro",
    "Outubro",
    "Novembro",
    "Dezembro",
)
QUINZENAS = ("1ª Quinzena", "2ª Quinzena")
TRIMESTRES = ("1º Trimestre", "2º Trimestre", "3º Trimestre")

# O SDK oficial de conectores está instalado no workspace JavaScript. O processo
# auxiliar recebe somente os dados desta mensagem via stdin; credenciais não são
# lidas nem exibidas pelo aplicativo.
NODE_EMAIL_SENDER = r"""
import { ReplitConnectors } from "@replit/connectors-sdk";

let input = "";
for await (const chunk of process.stdin) input += chunk;

try {
  const { to, subject, body } = JSON.parse(input);
  if (
    typeof to !== "string" ||
    typeof subject !== "string" ||
    typeof body !== "string" ||
    !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(to)
  ) {
    throw new Error("Invalid email payload");
  }

  const encodedSubject = `=?UTF-8?B?${Buffer.from(subject, "utf8").toString("base64")}?=`;
  const encodedBody = Buffer.from(body, "utf8").toString("base64").match(/.{1,76}/g)?.join("\r\n") ?? "";
  const mimeMessage = [
    `To: ${to}`,
    `Subject: ${encodedSubject}`,
    "MIME-Version: 1.0",
    "Content-Type: text/plain; charset=UTF-8",
    "Content-Transfer-Encoding: base64",
    "",
    encodedBody,
  ].join("\r\n");
  const raw = Buffer.from(mimeMessage, "utf8").toString("base64url");

  const connectors = new ReplitConnectors();
  const response = await connectors.proxy(
    "google-mail",
    "/gmail/v1/users/me/messages/send",
    { method: "POST", body: { raw } },
  );
  if (!response.ok) {
    process.stderr.write(`Gmail respondeu HTTP ${response.status}.`);
    process.exit(1);
  }
  const result = await response.json();
  process.stdout.write(JSON.stringify({ ok: true, id: result.id ?? null }));
} catch (error) {
  if (!process.exitCode) process.exitCode = 1;
  if (!process.stderr.writableEnded) process.stderr.write("Falha ao enviar a mensagem pelo Gmail.");
}
"""


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
                classroom_id INTEGER NOT NULL REFERENCES classrooms(id)
            );

            CREATE TABLE IF NOT EXISTS authorized_users (
                registry TEXT PRIMARY KEY,
                role TEXT NOT NULL CHECK(role IN ('Administrador', 'Professor')),
                full_name TEXT NOT NULL DEFAULT '',
                email TEXT NOT NULL DEFAULT '',
                teacher_type TEXT NOT NULL DEFAULT 'Regular',
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

            CREATE TABLE IF NOT EXISTS student_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL REFERENCES students(id),
                record_type TEXT NOT NULL,
                record_date TEXT NOT NULL,
                summary TEXT NOT NULL,
                action TEXT NOT NULL,
                teacher_name TEXT NOT NULL,
                teacher_registry TEXT NOT NULL,
                teacher_email TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )

        # Migra instalações anteriores sem apagar os avisos, agendamentos ou AEE.
        migrations = {
            "reservations": {
                "teacher_name": "TEXT NOT NULL DEFAULT ''",
                "teacher_registry": "TEXT NOT NULL DEFAULT ''",
                "teacher_email": "TEXT NOT NULL DEFAULT ''",
            },
            "aee_reports": {
                "teacher_name": "TEXT NOT NULL DEFAULT ''",
                "teacher_registry": "TEXT NOT NULL DEFAULT ''",
                "teacher_email": "TEXT NOT NULL DEFAULT ''",
            },
            "authorized_users": {
                "teacher_type": "TEXT NOT NULL DEFAULT 'Regular'",
            },
            "plans_minutes": {
                "student_id": "INTEGER REFERENCES students(id)",
                "month_name": "TEXT NOT NULL DEFAULT ''",
                "quinzena": "TEXT NOT NULL DEFAULT ''",
                "trimester": "TEXT NOT NULL DEFAULT ''",
            },
        }
        for table, columns in migrations.items():
            existing = {
                row["name"]
                for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
            }
            for column, definition in columns.items():
                if column not in existing:
                    connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

        for room in SALAS_CADASTRADAS:
            connection.execute("INSERT OR IGNORE INTO classrooms (name) VALUES (?)", (room,))

        # Reclassifica somente as salas de demonstração da versão anterior,
        # preservando os alunos e registros vinculados a elas.
        legacy_rooms = {
            "1º ano A": "Primeira Etapa - Turma 1",
            "2º ano B": "Segunda Etapa - Turma 1",
            "5º ano A": "Segunda Etapa - Turma 2",
        }
        for old_name, new_name in legacy_rooms.items():
            old_room = connection.execute(
                "SELECT id FROM classrooms WHERE name = ?", (old_name,)
            ).fetchone()
            new_room = connection.execute(
                "SELECT id FROM classrooms WHERE name = ?", (new_name,)
            ).fetchone()
            if old_room and new_room:
                for table in ("students", "assessments", "plans_minutes"):
                    connection.execute(
                        f"UPDATE {table} SET classroom_id = ? WHERE classroom_id = ?",
                        (new_room["id"], old_room["id"]),
                    )
                connection.execute("DELETE FROM classrooms WHERE id = ?", (old_room["id"],))

        room_ids = {
            row["name"]: row["id"]
            for row in connection.execute("SELECT id, name FROM classrooms").fetchall()
        }
        for code, name, room in ALUNOS_DE_EXEMPLO:
            connection.execute(
                "INSERT OR IGNORE INTO students (code, name, classroom_id) VALUES (?, ?, ?)",
                (code, name, room_ids[room]),
            )

        now = datetime.now().isoformat(timespec="minutes")
        for registry, user in MATRICULAS_PERMITIDAS.items():
            connection.execute(
                """
                INSERT OR IGNORE INTO authorized_users
                    (registry, role, full_name, email, teacher_type, active, created_at)
                VALUES (?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    registry,
                    user["role"],
                    user["name"],
                    user["email"],
                    user["teacher_type"],
                    now,
                ),
            )


def fetch_all(query: str, parameters: tuple = ()) -> list[sqlite3.Row]:
    with connection_scope() as connection:
        return connection.execute(query, parameters).fetchall()


def fetch_one(query: str, parameters: tuple = ()) -> sqlite3.Row | None:
    with connection_scope() as connection:
        return connection.execute(query, parameters).fetchone()


def format_date(value: str) -> str:
    return date.fromisoformat(value).strftime("%d/%m/%Y")


def classroom_rows() -> list[sqlite3.Row]:
    rooms = fetch_all(
        "SELECT id, name FROM classrooms WHERE name IN ({})".format(
            ",".join("?" for _ in SALAS_CADASTRADAS)
        ),
        SALAS_CADASTRADAS,
    )
    by_name = {row["name"]: row for row in rooms}
    return [by_name[name] for name in SALAS_CADASTRADAS if name in by_name]


def get_authorized_user(registry: str) -> sqlite3.Row | None:
    return fetch_one(
        "SELECT registry, role, full_name, email, teacher_type, active "
        "FROM authorized_users WHERE registry = ?",
        (registry.strip().lower(),),
    )


def add_student(name: str, classroom_id: int, code: str = "") -> str:
    with connection_scope() as connection:
        if not code.strip():
            next_id = connection.execute(
                "SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM students"
            ).fetchone()["next_id"]
            code = f"ALU-{next_id:03d}"
        connection.execute(
            "INSERT INTO students (code, name, classroom_id) VALUES (?, ?, ?)",
            (code.strip().upper(), name.strip(), classroom_id),
        )
    return code.strip().upper()


def add_authorized_teacher(name: str, registry: str, email: str, teacher_type: str) -> None:
    with connection_scope() as connection:
        connection.execute(
            """
            INSERT INTO authorized_users
                (registry, role, full_name, email, teacher_type, active, created_at)
            VALUES (?, 'Professor', ?, ?, ?, 1, ?)
            """,
            (
                registry.strip().lower(),
                name.strip(),
                email.strip().lower(),
                teacher_type,
                datetime.now().isoformat(timespec="minutes"),
            ),
        )


def complete_teacher_profile(registry: str, name: str, email: str) -> None:
    with connection_scope() as connection:
        connection.execute(
            """
            UPDATE authorized_users
            SET full_name = CASE WHEN full_name = '' THEN ? ELSE full_name END,
                email = CASE WHEN email = '' THEN ? ELSE email END
            WHERE registry = ? AND role = 'Professor'
            """,
            (name.strip(), email.strip().lower(), registry.strip().lower()),
        )


def students_in_classroom(classroom_id: int) -> list[sqlite3.Row]:
    return fetch_all(
        """
        SELECT students.id, students.code, students.name, classrooms.name AS classroom
        FROM students JOIN classrooms ON classrooms.id = students.classroom_id
        WHERE classrooms.id = ?
        ORDER BY students.name
        """,
        (classroom_id,),
    )


def save_announcement(title: str, category: str, audience: str, body: str) -> None:
    with connection_scope() as connection:
        connection.execute(
            """
            INSERT INTO announcements (title, category, audience, body, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                title.strip(),
                category,
                audience,
                body.strip(),
                datetime.now().isoformat(timespec="minutes"),
            ),
        )


def add_reservation(
    space: str,
    teacher: dict[str, str],
    group_name: str,
    reservation_date: date,
    start_time: time,
    end_time: time,
    purpose: str,
) -> tuple[bool, str]:
    start_text = start_time.strftime("%H:%M")
    end_text = end_time.strftime("%H:%M")
    with connection_scope() as connection:
        conflict = connection.execute(
            """
            SELECT start_time, end_time
            FROM reservations
            WHERE space = ? AND reservation_date = ?
              AND start_time < ? AND end_time > ?
            LIMIT 1
            """,
            (space, reservation_date.isoformat(), end_text, start_text),
        ).fetchone()
        if conflict:
            return False, f"Esse horário já está reservado ({conflict['start_time']}–{conflict['end_time']})."

        connection.execute(
            """
            INSERT INTO reservations
                (space, responsible, teacher_name, teacher_registry, teacher_email,
                 group_name, reservation_date, start_time, end_time, purpose, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                space,
                teacher["name"],
                teacher["name"],
                teacher["registry"],
                teacher["email"],
                group_name.strip(),
                reservation_date.isoformat(),
                start_text,
                end_text,
                purpose.strip(),
                datetime.now().isoformat(timespec="minutes"),
            ),
        )
    return True, "Agendamento registrado."


def add_aee_report(
    student_ref: str,
    grade: str,
    period: str,
    goals: str,
    supports: str,
    progress: str,
    status: str,
    teacher: dict[str, str],
) -> None:
    with connection_scope() as connection:
        connection.execute(
            """
            INSERT INTO aee_reports
                (student_ref, grade, period, goals, supports, progress, status, created_at,
                 teacher_name, teacher_registry, teacher_email)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                student_ref.strip(),
                grade.strip(),
                period.strip(),
                goals.strip(),
                supports.strip(),
                progress.strip(),
                status,
                datetime.now().isoformat(timespec="minutes"),
                teacher["name"],
                teacher["registry"],
                teacher["email"],
            ),
        )


def save_attendance(
    student_statuses: dict[int, str],
    attendance_date: date,
    teacher: dict[str, str],
) -> None:
    now = datetime.now().isoformat(timespec="minutes")
    with connection_scope() as connection:
        for student_id, status in student_statuses.items():
            connection.execute(
                """
                INSERT INTO attendance
                    (student_id, attendance_date, status, teacher_name, teacher_registry,
                     teacher_email, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(student_id, attendance_date) DO UPDATE SET
                    status = excluded.status,
                    teacher_name = excluded.teacher_name,
                    teacher_registry = excluded.teacher_registry,
                    teacher_email = excluded.teacher_email,
                    created_at = excluded.created_at
                """,
                (
                    student_id,
                    attendance_date.isoformat(),
                    status,
                    teacher["name"],
                    teacher["registry"],
                    teacher["email"],
                    now,
                ),
            )


def save_assessment(
    title: str,
    classroom_id: int,
    subject: str,
    assessment_type: str,
    assessment_date: date,
    notes: str,
    teacher: dict[str, str],
) -> None:
    with connection_scope() as connection:
        connection.execute(
            """
            INSERT INTO assessments
                (title, classroom_id, subject, assessment_type, assessment_date, notes,
                 teacher_name, teacher_registry, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title.strip(),
                classroom_id,
                subject.strip(),
                assessment_type,
                assessment_date.isoformat(),
                notes.strip(),
                teacher["name"],
                teacher["registry"],
                datetime.now().isoformat(timespec="minutes"),
            ),
        )


def save_plan_or_minutes(
    record_type: str,
    record_date: date,
    classroom_id: int | None,
    subject: str,
    title: str,
    content: str,
    teacher: dict[str, str],
    month_name: str = "",
    quinzena: str = "",
    trimester: str = "",
    student_id: int | None = None,
) -> int:
    with connection_scope() as connection:
        cursor = connection.execute(
            """
            INSERT INTO plans_minutes
                (record_type, record_date, classroom_id, student_id, month_name, quinzena,
                 trimester, subject, title, content, teacher_name, teacher_registry, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record_type,
                record_date.isoformat(),
                classroom_id,
                student_id,
                month_name,
                quinzena,
                trimester,
                subject.strip(),
                title.strip(),
                content.strip(),
                teacher["name"],
                teacher["registry"],
                datetime.now().isoformat(timespec="minutes"),
            ),
        )
        return int(cursor.lastrowid)


def save_student_history(
    student_id: int,
    record_type: str,
    record_date: date,
    summary: str,
    action: str,
    teacher: dict[str, str],
) -> None:
    with connection_scope() as connection:
        connection.execute(
            """
            INSERT INTO student_history
                (student_id, record_type, record_date, summary, action, teacher_name,
                 teacher_registry, teacher_email, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                student_id,
                record_type,
                record_date.isoformat(),
                summary.strip(),
                action.strip(),
                teacher["name"],
                teacher["registry"],
                teacher["email"],
                datetime.now().isoformat(timespec="minutes"),
            ),
        )


def delete_record(table: str, record_id: int) -> None:
    allowed_tables = {
        "announcements",
        "reservations",
        "aee_reports",
        "assessments",
        "plans_minutes",
        "student_history",
    }
    if table not in allowed_tables:
        raise ValueError("Tipo de registro inválido.")
    with connection_scope() as connection:
        connection.execute(f"DELETE FROM {table} WHERE id = ?", (record_id,))


def send_gmail_copy(to: str, subject: str, body: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["node", "--input-type=module", "-e", NODE_EMAIL_SENDER],
            cwd=APP_DIR,
            input=json.dumps({"to": to, "subject": subject, "body": body}, ensure_ascii=False),
            text=True,
            capture_output=True,
            timeout=40,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, "O Gmail não confirmou o envio dentro do tempo esperado."
    except OSError:
        return False, "Não foi possível iniciar o serviço de envio Gmail."

    if result.returncode != 0:
        return False, "O Gmail não confirmou o envio. Confira a pasta Enviados antes de tentar novamente."
    try:
        response = json.loads(result.stdout)
    except json.JSONDecodeError:
        return False, "O Gmail retornou uma resposta inesperada."
    if not response.get("ok"):
        return False, "O Gmail não confirmou o envio."
    return True, "Cópia enviada."


def build_aee_report_text(row: sqlite3.Row | dict[str, str]) -> str:
    created_at = row["created_at"]
    try:
        created_label = datetime.fromisoformat(created_at).strftime("%d/%m/%Y %H:%M")
    except (TypeError, ValueError):
        created_label = created_at
    return f"""RELATÓRIO DE ACOMPANHAMENTO — AEE

Referência do estudante: {row['student_ref']}
Turma: {row['grade']}
Período: {row['period']}
Situação: {row['status']}
Professor responsável: {row['teacher_name']}
Matrícula do professor: {row['teacher_registry']}
E-mail do professor: {row['teacher_email']}

Objetivos de aprendizagem e participação:
{row['goals']}

Atendimentos e recursos de apoio:
{row['supports']}

Avanços observados e próximos passos:
{row['progress']}

Registro criado em: {created_label}
"""


def render_login() -> None:
    st.title(APP_TITLE)
    st.subheader("Acesso ao sistema")
    st.caption("Informe sua matrícula e os dados solicitados para entrar.")
    with st.form("teacher_login_form"):
        teacher_name = st.text_input("Nome completo", help="Pode ficar em branco se já estiver cadastrado.")
        teacher_registry = st.text_input("Matrícula da Prefeitura")
        teacher_email = st.text_input(
            "E-mail",
            placeholder="professor@escola.edu.br",
            help="Pode ficar em branco se o administrador já cadastrou seu e-mail.",
        )
        login_submitted = st.form_submit_button("Acessar", type="primary")

    if login_submitted:
        normalized_registry = teacher_registry.strip().lower()
        normalized_email = teacher_email.strip().lower()
        account = get_authorized_user(normalized_registry)
        if not normalized_registry or account is None or not account["active"]:
            st.error("Matrícula não autorizada. Solicite à administração o cadastro da sua matrícula.")
        elif account["role"] == "Administrador":
            if normalized_email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized_email):
                st.error("Informe um endereço de e-mail válido ou deixe o campo em branco.")
            else:
                st.session_state["teacher_profile"] = {
                    "name": account["full_name"] or "Administrador",
                    "registry": account["registry"],
                    "email": normalized_email or account["email"],
                    "role": "Administrador",
                    "teacher_type": account["teacher_type"],
                }
                st.rerun()
        else:
            resolved_name = account["full_name"] or teacher_name.strip()
            resolved_email = account["email"] or normalized_email
            if not resolved_name or not resolved_email:
                st.error("Preencha o nome e o e-mail, ou solicite ao administrador que complete seu cadastro.")
            elif not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", resolved_email):
                st.error("Informe um endereço de e-mail válido.")
            else:
                complete_teacher_profile(account["registry"], resolved_name, resolved_email)
                st.session_state["teacher_profile"] = {
                    "name": resolved_name,
                    "registry": account["registry"],
                    "email": resolved_email,
                    "role": "Professor",
                    "teacher_type": account["teacher_type"],
                }
                st.rerun()

    st.info(
        "O acesso por matrícula é uma lista de permissões e não confirma a identidade do usuário. "
        "Use autenticação institucional antes de guardar dados reais de estudantes."
    )


def render_announcements() -> None:
    st.subheader("Quadro de Avisos")
    with st.form("announcement_form", clear_on_submit=True):
        title = st.text_input("Título", max_chars=120)
        col1, col2 = st.columns(2)
        category = col1.selectbox("Categoria", ["Comunicado", "Evento", "Reunião", "Prazo", "Outro"])
        audience = col2.selectbox(
            "Público",
            ["Toda a comunidade", "Estudantes", "Famílias", "Equipe escolar"],
        )
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
    if not announcements:
        st.info("Ainda não há avisos. Publique o primeiro comunicado acima.")
        return
    for row in announcements:
        with st.container(border=True):
            st.markdown(f"**{row['title']}**")
            st.caption(
                f"{row['category']} · {row['audience']} · "
                f"{datetime.fromisoformat(row['created_at']).strftime('%d/%m/%Y às %H:%M')}"
            )
            st.write(row["body"])
            if st.button("Excluir aviso", key=f"delete_announcement_{row['id']}"):
                delete_record("announcements", row["id"])
                st.rerun()


def render_daily_attendance(teacher: dict[str, str]) -> None:
    st.subheader("Chamada Diária")
    st.caption("Registre presença por turma e consulte as chamadas já salvas.")
    rooms = classroom_rows()
    room_names = [row["name"] for row in rooms]
    selected_room = st.selectbox("Sala de aula", room_names, key="attendance_room")
    classroom_id = next(row["id"] for row in rooms if row["name"] == selected_room)
    attendance_date = st.date_input("Data da chamada", value=date.today(), key="attendance_date")
    students = students_in_classroom(classroom_id)
    existing = {
        row["student_id"]: row["status"]
        for row in fetch_all(
            "SELECT student_id, status FROM attendance WHERE attendance_date = ?",
            (attendance_date.isoformat(),),
        )
    }
    with st.form("daily_attendance_form"):
        statuses: dict[int, str] = {}
        for student in students:
            current = existing.get(student["id"], "Presente")
            statuses[student["id"]] = st.selectbox(
                f"{student['name']} · {student['code']}",
                STATUS_CHAMADA,
                index=STATUS_CHAMADA.index(current) if current in STATUS_CHAMADA else 0,
                key=f"attendance_{attendance_date.isoformat()}_{student['id']}",
            )
        submitted = st.form_submit_button("Salvar chamada", type="primary")
    if submitted:
        save_attendance(statuses, attendance_date, teacher)
        st.success("Chamada salva.")

    st.divider()
    rows = fetch_all(
        """
        SELECT students.name, students.code, attendance.status
        FROM attendance
        JOIN students ON students.id = attendance.student_id
        WHERE students.classroom_id = ? AND attendance.attendance_date = ?
        ORDER BY students.name
        """,
        (classroom_id, attendance_date.isoformat()),
    )
    if rows:
        st.dataframe(
            [{"Aluno": row["name"], "Código": row["code"], "Situação": row["status"]} for row in rows],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Ainda não há chamada salva para esta turma e data.")


def render_assessment_calendar(teacher: dict[str, str]) -> None:
    st.subheader("Calendário de Avaliações")
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
        SELECT assessments.id, assessments.title, classrooms.name AS classroom,
               assessments.subject, assessments.assessment_type, assessments.assessment_date,
               assessments.notes, assessments.teacher_name
        FROM assessments JOIN classrooms ON classrooms.id = assessments.classroom_id
        ORDER BY assessments.assessment_date, assessments.title
        """
    )
    st.divider()
    if not rows:
        st.info("Nenhuma avaliação cadastrada.")
        return
    st.dataframe(
        [
            {
                "Data": format_date(row["assessment_date"]),
                "Sala": row["classroom"],
                "Avaliação": row["title"],
                "Componente": row["subject"],
                "Tipo": row["assessment_type"],
                "Orientações": row["notes"],
            }
            for row in rows
        ],
        use_container_width=True,
        hide_index=True,
    )
    labels = {
        f"{format_date(row['assessment_date'])} · {row['classroom']} · {row['title']}": row["id"]
        for row in rows
    }
    selected = st.selectbox("Remover avaliação", list(labels), key="delete_assessment_choice")
    if st.button("Excluir avaliação", key="delete_assessment_button"):
        delete_record("assessments", labels[selected])
        st.rerun()


def decode_plan_content(content: str) -> dict:
    try:
        decoded = json.loads(content)
    except (TypeError, json.JSONDecodeError):
        return {"legacy_text": content}
    return decoded if isinstance(decoded, dict) else {"legacy_text": content}


def registered_teacher_rows() -> list[sqlite3.Row]:
    return fetch_all(
        """
        SELECT registry, full_name
        FROM authorized_users
        WHERE role = 'Professor' AND active = 1
        ORDER BY full_name COLLATE NOCASE, registry
        """
    )


def build_minutes_print_html(row: sqlite3.Row, teachers: list[sqlite3.Row]) -> str:
    payload = decode_plan_content(row["content"])
    subject_reports = payload.get("subject_reports", {})
    if not isinstance(subject_reports, dict):
        subject_reports = {}

    subject_sections = "".join(
        "<section class='subject-report'>"
        f"<h3>{html.escape(area)}</h3>"
        f"<div>{html.escape(str(subject_reports.get(area, ''))).replace(chr(10), '<br>') or '—'}</div>"
        "</section>"
        for area in AREAS_PEDAGOGICAS
    )
    legacy_text = payload.get("legacy_text", "")
    if legacy_text and not payload.get("subject_reports"):
        subject_sections = (
            "<section class='subject-report legacy-report'>"
            f"<div>{html.escape(str(legacy_text)).replace(chr(10), '<br>')}</div>"
            "</section>"
        )

    aee_report = str(payload.get("aee_report", "")).strip()
    signatures = []
    for row_teacher in teachers:
        full_name = (row_teacher["full_name"] or "").strip()
        label = (
            f"Prof. {full_name}"
            if full_name
            else f"Professor(a) — matrícula {row_teacher['registry']}"
        )
        signatures.append(
            "<div class='signature-block'>"
            "<div class='signature-line'></div>"
            f"<div class='signature-name'>{html.escape(label)}</div>"
            "</div>"
        )
    signatures_html = "".join(signatures) or (
        "<p class='no-signatures'>Nenhum professor está cadastrado para assinatura.</p>"
    )
    trimester = row["trimester"] or payload.get("trimestre", "")
    trimester_html = (
        f"<span><strong>Trimestre:</strong> {html.escape(trimester)}</span>"
        if trimester
        else ""
    )
    author = html.escape(row["teacher_name"] or "Equipe pedagógica")
    classroom = html.escape(row["classroom"] or "Turma não informada")
    title = html.escape(row["title"])
    record_date = html.escape(format_date(row["record_date"]))
    aee_html = (
        html.escape(aee_report).replace("\n", "<br>")
        if aee_report
        else "Sem registro de AEE informado para este conselho."
    )

    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
* {{ box-sizing: border-box; }}
body {{ margin: 0; color: #202124; font-family: Arial, sans-serif; line-height: 1.5; }}
.page {{ max-width: 900px; margin: 0 auto; padding: 24px; }}
.toolbar {{ display: flex; justify-content: flex-end; margin-bottom: 18px; }}
.toolbar button {{ border: 0; border-radius: 6px; background: #1769aa; color: #fff; padding: 11px 16px; font-size: 15px; }}
.school-header {{ text-align: center; border-bottom: 1px solid #777; padding-bottom: 14px; margin-bottom: 18px; }}
.school-header h1 {{ font-size: 20px; margin: 0 0 4px; }}
.school-header p {{ margin: 0; }}
h2 {{ font-size: 20px; margin: 18px 0 8px; }}
h3 {{ font-size: 15px; margin: 14px 0 4px; }}
.metadata {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px 18px; margin: 14px 0 20px; }}
.subject-report {{ margin: 12px 0; break-inside: avoid; page-break-inside: avoid; }}
.subject-report div, .aee-report {{ white-space: normal; }}
.aee-report {{ border-top: 1px solid #aaa; margin-top: 18px; padding-top: 12px; }}
.signature-heading {{ margin-top: 32px; }}
.signature-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 28px 24px; margin-top: 22px; }}
.signature-block {{ min-width: 0; text-align: center; break-inside: avoid; page-break-inside: avoid; }}
.signature-line {{ height: 30px; border-bottom: 1px dotted #333; }}
.signature-name {{ margin-top: 7px; overflow-wrap: anywhere; }}
.no-signatures {{ grid-column: 1 / -1; }}
@media screen and (max-width: 600px) {{
  .page {{ padding: 14px; }}
  .metadata, .signature-grid {{ grid-template-columns: 1fr; }}
}}
@media print {{
  @page {{ size: A4; margin: 16mm; }}
  body {{ font-size: 11pt; }}
  .page {{ max-width: none; padding: 0; }}
  .toolbar {{ display: none !important; }}
  .signature-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 26px 20px; }}
  .signature-block {{ break-inside: avoid; page-break-inside: avoid; }}
}}
</style>
</head>
<body>
<main class="page">
  <div class="toolbar"><button type="button" onclick="window.print()">Imprimir / Salvar em PDF</button></div>
  <header class="school-header">
    <h1>CI Prefeito Ary Levy Pereira</h1>
    <p>Ata de Conselho</p>
  </header>
  <h2>{title}</h2>
  <div class="metadata">
    <span><strong>Turma:</strong> {classroom}</span>
    <span><strong>Data:</strong> {record_date}</span>
    {trimester_html}
    <span><strong>Responsável pelo registro:</strong> {author}</span>
  </div>
  <section>{subject_sections}</section>
  <section class="aee-report">
    <h3>Relatório do AEE da turma</h3>
    <div>{aee_html}</div>
  </section>
  <h2 class="signature-heading">Assinaturas dos professores</h2>
  <div class="signature-grid">{signatures_html}</div>
</main>
</body>
</html>"""


def render_plans_minutes(teacher: dict[str, str]) -> None:
    st.subheader("Planejamentos & Atas de Conselho")
    rooms = classroom_rows()
    room_names = [row["name"] for row in rooms]
    room_ids = {row["name"]: row["id"] for row in rooms}
    teacher_type = teacher.get("teacher_type", "Regular")
    is_admin = teacher.get("role") == "Administrador"

    tab_names = []
    if is_admin or teacher_type != "AEE":
        tab_names.append("Planejamento Quinzenal")
    if is_admin or teacher_type == "AEE":
        tab_names.append("Planejamento Individualizado AEE")
    tab_names.append("Ata de Conselho")
    tabs_by_name = dict(zip(tab_names, st.tabs(tab_names)))

    if "Planejamento Quinzenal" in tabs_by_name:
        with tabs_by_name["Planejamento Quinzenal"]:
            st.caption("Preencha os objetivos e as atividades das seis áreas para a turma.")
            with st.form("regular_quinzena_form", clear_on_submit=True):
                col1, col2, col3 = st.columns(3)
                month_name = col1.selectbox("Mês do ano", MESES_DO_ANO, key="regular_plan_month")
                quinzena = col2.selectbox("Quinzena", QUINZENAS, key="regular_plan_quinzena")
                record_date = col3.date_input("Data do registro", value=date.today(), key="regular_plan_date")
                room_name = st.selectbox("Turma", room_names, key="regular_plan_room")
                activities = {
                    area: st.text_area(
                        f"{area} — objetivos e atividades",
                        height=90,
                        key=f"regular_plan_area_{index}",
                    )
                    for index, area in enumerate(AREAS_PEDAGOGICAS)
                }
                submitted = st.form_submit_button("Salvar Planejamento Quinzenal", type="primary")
            if submitted:
                missing_areas = [
                    area for area, text in activities.items() if not text.strip()
                ]
                if missing_areas:
                    st.error("Preencha as seis áreas. Faltam: " + ", ".join(missing_areas))
                else:
                    record_id = save_plan_or_minutes(
                        "Planejamento Quinzenal",
                        record_date,
                        room_ids[room_name],
                        "Planejamento por áreas",
                        f"Planejamento Quinzenal — {month_name} — {quinzena}",
                        json.dumps({"activities": activities}, ensure_ascii=False),
                        teacher,
                        month_name=month_name,
                        quinzena=quinzena,
                    )
                    st.success("Planejamento Quinzenal salvo.")

    if "Planejamento Individualizado AEE" in tabs_by_name:
        with tabs_by_name["Planejamento Individualizado AEE"]:
            students = fetch_all(
                """
                SELECT students.id, students.code, students.name, students.classroom_id,
                       classrooms.name AS classroom
                FROM students JOIN classrooms ON classrooms.id = students.classroom_id
                WHERE classrooms.name IN ({})
                ORDER BY students.name, students.code
                """.format(",".join("?" for _ in SALAS_CADASTRADAS)),
                SALAS_CADASTRADAS,
            )
            if not students:
                st.info("Cadastre ao menos um aluno antes de criar um planejamento AEE.")
            else:
                student_options = {
                    f"{student['name']} · {student['classroom']} · {student['code']}": student["id"]
                    for student in students
                }
                students_by_id = {student["id"]: student for student in students}
                with st.form("aee_individual_plan_form", clear_on_submit=True):
                    student_label = st.selectbox(
                        "Aluno",
                        list(student_options),
                        key="aee_plan_student",
                    )
                    col1, col2, col3 = st.columns(3)
                    month_name = col1.selectbox("Mês do ano", MESES_DO_ANO, key="aee_plan_month")
                    quinzena = col2.selectbox("Quinzena", QUINZENAS, key="aee_plan_quinzena")
                    record_date = col3.date_input("Data do registro", value=date.today(), key="aee_plan_date")
                    adapted_plan = st.text_area(
                        "Plano adaptado para este aluno",
                        height=180,
                        key="aee_adapted_plan",
                    )
                    submitted = st.form_submit_button(
                        "Salvar Planejamento Individualizado AEE",
                        type="primary",
                    )
                if submitted:
                    if not adapted_plan.strip():
                        st.error("Preencha o plano adaptado para o aluno.")
                    else:
                        student = students_by_id[student_options[student_label]]
                        record_id = save_plan_or_minutes(
                            "Planejamento Individualizado AEE",
                            record_date,
                            student["classroom_id"],
                            "AEE",
                            (
                                f"Planejamento Individualizado AEE — {student['name']} — "
                                f"{month_name} — {quinzena}"
                            ),
                            json.dumps(
                                {
                                    "student_name": student["name"],
                                    "student_code": student["code"],
                                    "adapted_plan": adapted_plan.strip(),
                                },
                                ensure_ascii=False,
                            ),
                            teacher,
                            month_name=month_name,
                            quinzena=quinzena,
                            student_id=student["id"],
                        )
                        st.success("Planejamento Individualizado AEE salvo.")

    with tabs_by_name["Ata de Conselho"]:
        st.caption("Registre o desempenho da turma nas seis áreas e o relatório do AEE.")
        with st.form("council_minutes_form", clear_on_submit=True):
            title = st.text_input("Título da ata", value="Ata de Conselho", max_chars=160)
            col1, col2, col3 = st.columns(3)
            record_date = col1.date_input("Data da reunião", value=date.today(), key="minutes_date")
            room_name = col2.selectbox("Turma", room_names, key="minutes_room")
            trimester = col3.selectbox("Trimestre", TRIMESTRES, key="minutes_trimester")
            subject_reports = {
                area: st.text_area(
                    f"Desempenho — {area}",
                    height=90,
                    key=f"minutes_area_{index}",
                )
                for index, area in enumerate(AREAS_PEDAGOGICAS)
            }
            aee_report = st.text_area(
                "Relatório do AEE da turma (opcional quando não se aplicar)",
                height=120,
                key="minutes_aee_report",
            )
            submitted = st.form_submit_button("Salvar Ata de Conselho", type="primary")
        if submitted:
            missing_areas = [
                area for area, text in subject_reports.items() if not text.strip()
            ]
            if not title.strip():
                st.error("Informe o título da ata.")
            elif missing_areas:
                st.error("Preencha o desempenho das seis áreas. Faltam: " + ", ".join(missing_areas))
            else:
                record_id = save_plan_or_minutes(
                    "Ata de Conselho",
                    record_date,
                    room_ids[room_name],
                    "Desempenho e acompanhamento da turma",
                    title,
                    json.dumps(
                        {
                            "subject_reports": subject_reports,
                            "aee_report": aee_report.strip(),
                            "trimestre": trimester,
                        },
                        ensure_ascii=False,
                    ),
                    teacher,
                    trimester=trimester,
                )
                st.session_state["minutes_preview_id"] = record_id
                st.success("Ata salva. A visualização para impressão está disponível abaixo.")

    rows = fetch_all(
        """
        SELECT plans_minutes.id, plans_minutes.record_type, plans_minutes.record_date,
               plans_minutes.classroom_id, plans_minutes.student_id, plans_minutes.month_name,
               plans_minutes.quinzena, plans_minutes.trimester, plans_minutes.subject,
               plans_minutes.title, plans_minutes.content, plans_minutes.teacher_name,
               classrooms.name AS classroom, students.name AS student_name,
               students.code AS student_code
        FROM plans_minutes
        LEFT JOIN classrooms ON classrooms.id = plans_minutes.classroom_id
        LEFT JOIN students ON students.id = plans_minutes.student_id
        ORDER BY plans_minutes.record_date DESC, plans_minutes.id DESC
        """
    )
    st.divider()
    if not rows:
        st.info("Nenhum planejamento ou ata cadastrado.")
        st.session_state.pop("minutes_preview_id", None)
        return

    rows_by_id = {row["id"]: row for row in rows}
    preview_id = st.session_state.get("minutes_preview_id")
    if preview_id not in rows_by_id:
        st.session_state.pop("minutes_preview_id", None)
        preview_id = None

    st.markdown("#### Registros salvos")
    for row in rows:
        payload = decode_plan_content(row["content"])
        room_label = row["classroom"] or "Sem sala específica"
        expander_title = (
            f"{row['record_type']} · {format_date(row['record_date'])} · {row['title']}"
        )
        with st.expander(expander_title):
            details = [room_label]
            if row["month_name"]:
                details.append(row["month_name"])
            if row["quinzena"]:
                details.append(row["quinzena"])
            if row["trimester"]:
                details.append(row["trimester"])
            if row["student_name"]:
                details.append(f"Aluno: {row['student_name']} · {row['student_code']}")
            details.append(row["teacher_name"])
            st.caption(" · ".join(details))

            if row["record_type"] == "Planejamento Quinzenal":
                activities = payload.get("activities", {})
                for area in AREAS_PEDAGOGICAS:
                    st.markdown(f"**{area}**")
                    st.write(activities.get(area, ""))
            elif row["record_type"] == "Planejamento Individualizado AEE":
                st.markdown("**Plano adaptado**")
                st.write(payload.get("adapted_plan", payload.get("legacy_text", "")))
            elif row["record_type"] == "Ata de Conselho":
                reports = payload.get("subject_reports", {})
                if isinstance(reports, dict):
                    for area in AREAS_PEDAGOGICAS:
                        st.markdown(f"**{area}**")
                        st.write(reports.get(area, ""))
                    st.markdown("**Relatório do AEE da turma**")
                    st.write(payload.get("aee_report", ""))
                else:
                    st.write(payload.get("legacy_text", row["content"]))
                if st.button("Visualizar / imprimir Ata", key=f"preview_minutes_{row['id']}"):
                    st.session_state["minutes_preview_id"] = row["id"]
                    st.rerun()
            else:
                st.write(payload.get("legacy_text", row["content"]))

            if st.button("Excluir registro", key=f"delete_plan_{row['id']}"):
                delete_record("plans_minutes", row["id"])
                st.session_state.pop("minutes_preview_id", None)
                st.rerun()

    preview_row = rows_by_id.get(st.session_state.get("minutes_preview_id"))
    if preview_row and preview_row["record_type"] == "Ata de Conselho":
        st.divider()
        st.subheader("Visualização pronta para impressão")
        st.caption("Use “Imprimir / Salvar em PDF” na visualização; as assinaturas são atualizadas com o cadastro de professores.")
        st.iframe(
            build_minutes_print_html(preview_row, registered_teacher_rows()),
            height=1250,
        )
        if st.button("Fechar visualização da ata", key="close_minutes_preview"):
            st.session_state.pop("minutes_preview_id", None)
            st.rerun()


def render_student_directory(teacher: dict[str, str]) -> None:
    st.subheader("Carômetro e Histórico de Alunos")
    st.caption("Os nomes e códigos exibidos são fictícios e servem apenas para demonstração.")
    rooms = classroom_rows()
    selected_room = st.selectbox("Filtrar por sala de aula", [row["name"] for row in rooms], key="student_room")
    classroom_id = next(row["id"] for row in rooms if row["name"] == selected_room)
    students = students_in_classroom(classroom_id)
    if not students:
        st.info("Não há alunos cadastrados nesta sala.")
        return

    cards = st.columns(3)
    for index, student in enumerate(students):
        with cards[index % len(cards)]:
            with st.container(border=True):
                initials = "".join(part[0] for part in student["name"].split()[:2]).upper()
                st.subheader(initials)
                st.markdown(f"**{student['name']}**")
                st.caption(f"{student['code']} · {student['classroom']}")
                if st.button("Abrir histórico", key=f"open_student_{student['id']}"):
                    st.session_state["selected_student_id"] = student["id"]
                    st.rerun()

    valid_ids = [student["id"] for student in students]
    selected_id = st.session_state.get("selected_student_id")
    if selected_id not in valid_ids:
        selected_id = valid_ids[0]
    student = next(row for row in students if row["id"] == selected_id)
    st.divider()
    st.markdown(f"### Histórico de {student['name']}")
    st.caption(f"Código: {student['code']} · Sala: {student['classroom']}")

    with st.form(f"student_history_form_{student['id']}", clear_on_submit=True):
        record_type = st.selectbox(
            "Tipo de registro",
            ["Comportamento", "Relatório", "Encaminhamento"],
            key=f"history_type_{student['id']}",
        )
        record_date = st.date_input("Data do registro", value=date.today(), key=f"history_date_{student['id']}")
        summary = st.text_area("Registro / observações", height=110)
        action = st.text_area("Providências, encaminhamentos ou acompanhamento", height=90)
        submitted = st.form_submit_button("Salvar no histórico", type="primary")
    if submitted:
        if not summary.strip():
            st.error("Descreva o registro antes de salvar.")
        else:
            save_student_history(student["id"], record_type, record_date, summary, action, teacher)
            st.success(f"{record_type} adicionado ao histórico.")

    records = fetch_all(
        """
        SELECT id, record_type, record_date, summary, action, teacher_name
        FROM student_history
        WHERE student_id = ?
        ORDER BY record_date DESC, id DESC
        """,
        (student["id"],),
    )
    st.markdown("#### Histórico registrado")
    if not records:
        st.info("Ainda não há registros para este aluno.")
        return
    for record in records:
        with st.expander(f"{record['record_type']} · {format_date(record['record_date'])}"):
            st.write(record["summary"])
            st.markdown(f"**Providências / acompanhamento:** {record['action'] or 'Não informado'}")
            st.caption(f"Registrado por {record['teacher_name']}")
            if st.button("Excluir registro", key=f"delete_student_history_{record['id']}"):
                delete_record("student_history", record["id"])
                st.rerun()


def render_space_booking(teacher: dict[str, str]) -> None:
    st.subheader("Agendamento de Espaços")
    st.caption("O sistema bloqueia sobreposição de horários para o mesmo espaço.")
    if teacher["email"]:
        st.info(f"A confirmação será enviada pelo Gmail para **{teacher['email']}** após salvar.")
    else:
        st.info("Esta sessão não tem e-mail cadastrado; o agendamento será salvo sem envio de cópia.")
    with st.form("reservation_form", clear_on_submit=True):
        space = st.selectbox("Espaço", ESPACOS)
        col1, col2 = st.columns(2)
        col1.text_input("Professor responsável", value=teacher["name"], disabled=True)
        group_name = col2.text_input("Turma ou grupo", placeholder="Ex.: 2º ano B")
        col3, col4, col5 = st.columns(3)
        reservation_date = col3.date_input("Data", min_value=date.today(), value=date.today())
        start_time = col4.time_input("Início", value=time(8, 0), step=1800)
        end_time = col5.time_input("Término", value=time(9, 0), step=1800)
        purpose = st.text_input("Atividade", placeholder="Ex.: aula de educação física")
        submitted = st.form_submit_button("Salvar agendamento", type="primary")
    if submitted:
        if not group_name.strip() or not purpose.strip():
            st.error("Preencha a turma ou grupo e a atividade.")
        elif end_time <= start_time:
            st.error("O horário de término deve ser posterior ao início.")
        else:
            success, message = add_reservation(
                space, teacher, group_name, reservation_date, start_time, end_time, purpose
            )
            if not success:
                st.warning(message)
            else:
                st.success(message)
                if teacher["email"]:
                    subject = f"Confirmação de agendamento — {space}"
                    body = f"""Olá, {teacher['name']}.

Seu agendamento foi registrado:
Espaço: {space}
Data: {reservation_date.strftime('%d/%m/%Y')}
Horário: {start_time.strftime('%H:%M')}–{end_time.strftime('%H:%M')}
Turma/grupo: {group_name.strip()}
Atividade: {purpose.strip()}
Matrícula: {teacher['registry']}
"""
                    sent, mail_message = send_gmail_copy(teacher["email"], subject, body)
                    if sent:
                        st.success(f"Cópia enviada para {teacher['email']}.")
                    else:
                        st.warning(
                            f"O agendamento foi salvo, mas o e-mail não foi confirmado. {mail_message}"
                        )

    rows = fetch_all(
        """
        SELECT id, reservation_date, start_time, end_time, group_name, responsible, purpose, space
        FROM reservations
        ORDER BY reservation_date, start_time
        """
    )
    st.divider()
    st.markdown("#### Agenda dos espaços")
    if not rows:
        st.info("Nenhum agendamento cadastrado.")
        return
    st.dataframe(
        [
            {
                "Espaço": row["space"],
                "Data": format_date(row["reservation_date"]),
                "Horário": f"{row['start_time']}–{row['end_time']}",
                "Turma/grupo": row["group_name"],
                "Responsável": row["responsible"],
                "Atividade": row["purpose"],
            }
            for row in rows
        ],
        use_container_width=True,
        hide_index=True,
    )
    options = {
        f"{row['space']} · {format_date(row['reservation_date'])} · {row['start_time']} · {row['group_name']}": row[
            "id"
        ]
        for row in rows
    }
    with st.form("cancel_reservation_form"):
        selected = st.selectbox("Cancelar um agendamento", list(options))
        confirm = st.checkbox("Confirmo o cancelamento deste horário.")
        delete_clicked = st.form_submit_button("Cancelar agendamento")
    if delete_clicked:
        if confirm:
            delete_record("reservations", options[selected])
            st.success("Agendamento cancelado.")
            st.rerun()
        else:
            st.warning("Marque a confirmação para cancelar.")


def render_aee_reports(teacher: dict[str, str]) -> None:
    st.subheader("Relatório de Inclusão — Atendimento Educacional Especializado")
    st.caption("Registre objetivos, apoios e avanços para apoiar o planejamento pedagógico.")
    if teacher["email"]:
        st.warning(
            "Privacidade: use somente informações necessárias ao acompanhamento pedagógico. "
            f"A cópia contém dados educacionais e será enviada a {teacher['email']}."
        )
    else:
        st.warning(
            "Privacidade: use somente informações necessárias ao acompanhamento pedagógico. "
            "Nenhum e-mail está cadastrado para esta sessão."
        )
    rooms = classroom_rows()
    room_name = st.selectbox("Turma", [row["name"] for row in rooms], key="aee_room")
    classroom_id = next(row["id"] for row in rooms if row["name"] == room_name)
    students = students_in_classroom(classroom_id)
    if not students:
        st.info("Esta turma ainda não tem alunos cadastrados. Cadastre-os no Painel de Controle do administrador.")
        return
    student_label = st.selectbox(
        "Estudante",
        [f"{row['name']} · {row['code']}" for row in students],
        key="aee_student",
    )
    selected_student = next(
        row for row in students if f"{row['name']} · {row['code']}" == student_label
    )
    with st.form("aee_report_form", clear_on_submit=True):
        period = st.text_input("Período de acompanhamento", placeholder="Ex.: 1º bimestre de 2026")
        goals = st.text_area("Objetivos de aprendizagem e participação", height=100)
        supports = st.text_area("Atendimentos, recursos e estratégias de apoio", height=100)
        progress = st.text_area("Avanços observados e próximos passos", height=100)
        status = st.selectbox(
            "Situação do acompanhamento",
            ["Em acompanhamento", "Revisão necessária", "Concluído"],
        )
        confirm_email = (
            st.checkbox(
                f"Confirmo que {teacher['email']} está correto e autorizo o envio desta cópia."
            )
            if teacher["email"]
            else False
        )
        submitted = st.form_submit_button("Salvar e enviar relatório AEE", type="primary")
    if submitted:
        if not all([period.strip(), goals.strip(), supports.strip(), progress.strip()]):
            st.error("Preencha o período, os objetivos, os apoios e os avanços.")
        elif teacher["email"] and not confirm_email:
            st.error("Confirme o destinatário antes de salvar e enviar o relatório.")
        else:
            report = {
                "student_ref": selected_student["code"],
                "grade": room_name,
                "period": period.strip(),
                "goals": goals.strip(),
                "supports": supports.strip(),
                "progress": progress.strip(),
                "status": status,
                "teacher_name": teacher["name"],
                "teacher_registry": teacher["registry"],
                "teacher_email": teacher["email"],
                "created_at": datetime.now().isoformat(timespec="minutes"),
            }
            add_aee_report(
                report["student_ref"],
                report["grade"],
                report["period"],
                report["goals"],
                report["supports"],
                report["progress"],
                report["status"],
                teacher,
            )
            st.success("Relatório registrado.")
            if teacher["email"]:
                sent, mail_message = send_gmail_copy(
                    teacher["email"],
                    f"Relatório AEE — {report['student_ref']} — {report['period']}",
                    build_aee_report_text(report),
                )
                if sent:
                    st.success(f"Cópia enviada para {teacher['email']}.")
                else:
                    st.warning(f"O relatório foi salvo, mas o envio não foi confirmado. {mail_message}")
            else:
                st.info("O relatório foi salvo, mas nenhuma cópia foi enviada porque não há e-mail cadastrado.")

    st.divider()
    st.subheader("Relatórios registrados")
    reports = fetch_all("SELECT * FROM aee_reports ORDER BY created_at DESC, id DESC")
    if not reports:
        st.info("Nenhum relatório AEE registrado.")
        return
    report_options = {
        f"{row['student_ref']} · {row['grade']} · {row['period']}": row["id"] for row in reports
    }
    selected_label = st.selectbox("Selecione um relatório para consultar ou baixar", list(report_options))
    selected_report = next(row for row in reports if row["id"] == report_options[selected_label])
    with st.container(border=True):
        st.markdown(
            f"**Código:** {selected_report['student_ref']} &nbsp; · &nbsp; "
            f"**Turma:** {selected_report['grade']}"
        )
        st.caption(f"{selected_report['period']} · {selected_report['status']}")
        st.caption(
            f"Registrado por {selected_report['teacher_name']} "
            f"({selected_report['teacher_registry']})"
        )
        st.markdown("**Objetivos**")
        st.write(selected_report["goals"])
        st.markdown("**Apoios e estratégias**")
        st.write(selected_report["supports"])
        st.markdown("**Avanços e próximos passos**")
        st.write(selected_report["progress"])
    report_text = build_aee_report_text(selected_report)
    safe_ref = "".join(char for char in selected_report["student_ref"] if char.isalnum() or char in "-_")
    st.download_button(
        "Baixar relatório em TXT",
        data=report_text.encode("utf-8"),
        file_name=f"relatorio_aee_{safe_ref or 'estudante'}.txt",
        mime="text/plain",
    )
    with st.form("delete_aee_report"):
        confirm_delete = st.checkbox("Confirmo a exclusão deste relatório.")
        delete_clicked = st.form_submit_button("Excluir relatório")
    if delete_clicked:
        if confirm_delete:
            delete_record("aee_reports", selected_report["id"])
            st.success("Relatório excluído.")
            st.rerun()
        else:
            st.warning("Marque a confirmação para excluir.")


def render_admin_panel() -> None:
    st.subheader("Painel de Controle")
    st.caption("Cadastros disponíveis somente para a matrícula administrativa.")
    students_tab, teachers_tab = st.tabs(["Cadastrar aluno", "Cadastrar professor"])

    with students_tab:
        rooms = classroom_rows()
        room_names = [row["name"] for row in rooms]
        with st.form("admin_student_form", clear_on_submit=True):
            student_name = st.text_input("Nome do aluno")
            room_name = st.selectbox("Turma", room_names)
            student_code = st.text_input(
                "Código do aluno (opcional)",
                placeholder="Gerado automaticamente se vazio",
            )
            submitted = st.form_submit_button("Cadastrar aluno", type="primary")
        if submitted:
            if not student_name.strip():
                st.error("Informe o nome do aluno.")
            else:
                classroom_id = next(row["id"] for row in rooms if row["name"] == room_name)
                try:
                    created_code = add_student(student_name, classroom_id, student_code)
                    st.success(f"Aluno cadastrado em {room_name}. Código: {created_code}.")
                except sqlite3.IntegrityError:
                    st.error("Esse código já está em uso. Informe outro código ou deixe o campo vazio.")

        student_rows = fetch_all(
            """
            SELECT students.code, students.name, classrooms.name AS classroom
            FROM students JOIN classrooms ON classrooms.id = students.classroom_id
            WHERE classrooms.name IN ({})
            ORDER BY classrooms.name, students.name
            """.format(",".join("?" for _ in SALAS_CADASTRADAS)),
            SALAS_CADASTRADAS,
        )
        st.markdown("#### Alunos cadastrados")
        st.dataframe(
            [{"Código": row["code"], "Aluno": row["name"], "Turma": row["classroom"]} for row in student_rows],
            width="stretch",
            hide_index=True,
        )

    with teachers_tab:
        with st.form("admin_teacher_form", clear_on_submit=True):
            teacher_name = st.text_input("Nome completo do professor")
            teacher_registry = st.text_input("Matrícula permitida")
            teacher_email = st.text_input("E-mail institucional")
            teacher_type_label = st.selectbox(
                "Cargo do profissional",
                ["Professor Regular", "Professor AEE"],
            )
            submitted = st.form_submit_button("Cadastrar professor", type="primary")
        if submitted:
            registry = teacher_registry.strip().lower()
            email = teacher_email.strip().lower()
            teacher_type = "AEE" if teacher_type_label == "Professor AEE" else "Regular"
            if not teacher_name.strip() or not registry or not email:
                st.error("Preencha o nome, a matrícula e o e-mail.")
            elif registry == "adm123":
                st.error("Essa matrícula é reservada ao administrador.")
            elif not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
                st.error("Informe um endereço de e-mail válido.")
            else:
                try:
                    add_authorized_teacher(teacher_name, registry, email, teacher_type)
                    st.success("Professor cadastrado e autorizado a entrar.")
                except sqlite3.IntegrityError:
                    st.error("Essa matrícula já está cadastrada.")

        teacher_rows = fetch_all(
            """
            SELECT registry, full_name, email, teacher_type
            FROM authorized_users
            WHERE role = 'Professor' AND active = 1
            ORDER BY full_name, registry
            """
        )
        st.markdown("#### Professores autorizados")
        st.dataframe(
            [
                {
                    "Matrícula": row["registry"],
                    "Professor": row["full_name"] or "Nome informado no acesso",
                    "E-mail": row["email"] or "Informado no acesso",
                    "Cargo": "Professor AEE" if row["teacher_type"] == "AEE" else "Professor Regular",
                }
                for row in teacher_rows
            ],
            width="stretch",
            hide_index=True,
        )


st.set_page_config(page_title=APP_TITLE, layout="wide")
initialize_database()

teacher = st.session_state.get("teacher_profile")
if teacher:
    account = get_authorized_user(teacher.get("registry", ""))
    if account is None or not account["active"]:
        st.session_state.pop("teacher_profile", None)
        teacher = None
    else:
        teacher["teacher_type"] = account["teacher_type"]
        teacher["role"] = account["role"]
        if account["role"] == "Administrador":
            teacher["name"] = account["full_name"] or "Administrador"
            if account["email"]:
                teacher["email"] = account["email"]
        else:
            if account["full_name"]:
                teacher["name"] = account["full_name"]
            if account["email"]:
                teacher["email"] = account["email"]
        st.session_state["teacher_profile"] = teacher

if teacher is None:
    render_login()
    st.stop()

teacher = st.session_state["teacher_profile"]
admin_pages = [
    ADMIN_PAGE,
    *PEDAGOGICAL_PAGES,
    "📅 Calendário de Avaliações",
    "📢 Quadro de Avisos",
    "🧩 Relatório de Inclusão AEE",
]
pages = admin_pages if teacher["role"] == "Administrador" else PEDAGOGICAL_PAGES

with st.sidebar:
    st.title("Portal Digital")
    st.subheader(teacher["role"])
    st.write(teacher["name"])
    st.caption(f"Matrícula: {teacher['registry']}")
    if teacher["email"]:
        st.caption(teacher["email"])
    else:
        st.caption("E-mail não cadastrado")
    st.divider()
    selected_page = st.radio("Menu", pages, label_visibility="collapsed")
    if st.button("Sair", use_container_width=True):
        st.session_state.pop("teacher_profile", None)
        st.rerun()

st.title(APP_TITLE)
st.subheader(selected_page)
if selected_page == ADMIN_PAGE:
    if teacher["role"] == "Administrador":
        render_admin_panel()
    else:
        st.error("Acesso restrito ao administrador.")
if selected_page == "📋 Chamada Diária":
    render_daily_attendance(teacher)
elif selected_page == "📅 Calendário de Avaliações":
    if teacher["role"] == "Administrador":
        render_assessment_calendar(teacher)
elif selected_page == "📝 Planejamentos & Atas de Conselho":
    render_plans_minutes(teacher)
elif selected_page == "🧒 Carômetro e Histórico de Alunos":
    render_student_directory(teacher)
elif selected_page == "🏢 Agendamento de Espaços":
    render_space_booking(teacher)
elif selected_page == "📢 Quadro de Avisos":
    if teacher["role"] == "Administrador":
        render_announcements()
elif selected_page == "🧩 Relatório de Inclusão AEE":
    if teacher["role"] == "Administrador":
        render_aee_reports(teacher)