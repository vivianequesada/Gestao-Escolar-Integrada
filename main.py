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

ESPACOS = ("Quadra", "Informática", "Leitura")
STATUS_CHAMADA = ("Presente", "Falta", "Falta justificada")
ADMIN_PAGE = "⚙️ Painel de Controle (Adm)"
PEDAGOGICAL_PAGES = [
    "📋 Chamada Diária",
    "🧒 Carômetro e Histórico de Alunos",
    "📝 Planejamentos & Atas de Conselho",
    "🏢 Agendamento de Espaços",
    "🚨 Ocorrências da Rotina",
    "📝 Relatório Descritivo",
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
ALUNOS_DE_EXEMPLO = []

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
                classroom_id INTEGER NOT NULL REFERENCES classrooms(id),
                allergies TEXT NOT NULL DEFAULT '',
                food_restrictions TEXT NOT NULL DEFAULT '',
                authorized_pickup TEXT NOT NULL DEFAULT '',
                emergency_contact TEXT NOT NULL DEFAULT '',
                avatar TEXT NOT NULL DEFAULT '👶',
                active INTEGER NOT NULL DEFAULT 1,
                faltas_consecutivas INTEGER NOT NULL DEFAULT 0
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
        CREATE TABLE IF NOT EXISTS development_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL REFERENCES students(id),
            report_date TEXT NOT NULL,
            social_interaction TEXT NOT NULL,
            motor_language_development TEXT NOT NULL,
            teacher_name TEXT NOT NULL,
            teacher_registry TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )

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
            "classroom_id": "INTEGER REFERENCES classrooms(id)",
        },
        "students": {
            "allergies": "TEXT NOT NULL DEFAULT ''",
            "food_restrictions": "TEXT NOT NULL DEFAULT ''",
            "authorized_pickup": "TEXT NOT NULL DEFAULT ''",
            "emergency_contact": "TEXT NOT NULL DEFAULT ''",
            "avatar": "TEXT NOT NULL DEFAULT '👶'",
            "active": "INTEGER NOT NULL DEFAULT 1",
            "faltas_consecutivas": "INTEGER NOT NULL DEFAULT 0",
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

    authorization_schema = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'authorized_users'"
    ).fetchone()

    if authorization_schema and "'Monitor'" not in (authorization_schema["sql"] or ""):
        connection.execute("SAVEPOINT authorized_users_role_migration")
        try:
            connection.execute("DROP TABLE IF EXISTS authorized_users_migrated")
            connection.execute(
                """
                CREATE TABLE authorized_users_migrated (
                    registry TEXT PRIMARY KEY,
                    role TEXT NOT NULL CHECK(role IN ('Administrador', 'Professor', 'Monitor')),
                    full_name TEXT NOT NULL DEFAULT '',
                    email TEXT NOT NULL DEFAULT '',
                    teacher_type TEXT NOT NULL DEFAULT 'Regular',
                    classroom_id INTEGER REFERENCES classrooms(id),
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT INTO authorized_users_migrated
                    (registry, role, full_name, email, teacher_type, classroom_id, active, created_at)
                SELECT registry, role, full_name, email, teacher_type, classroom_id, active, created_at
                FROM authorized_users
                """
            )
            connection.execute("DROP TABLE authorized_users")
            connection.execute(
                "ALTER TABLE authorized_users_migrated RENAME TO authorized_users"
            )
            connection.execute("RELEASE SAVEPOINT authorized_users_role_migration")
        except Exception:
            connection.execute("ROLLBACK TO SAVEPOINT authorized_users_role_migration")
            connection.execute("RELEASE SAVEPOINT authorized_users_role_migration")
            raise

    for room in SALAS_CADASTRADAS:
        connection.execute("INSERT OR IGNORE INTO classrooms (name) VALUES (?)", (room,))

    room_ids = {
        row["name"]: row["id"]
        for row in connection.execute("SELECT id, name FROM classrooms").fetchall()
    }

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


def classrooms_for_teacher(teacher: dict[str, str | int | None]) -> list[sqlite3.Row]:
    rooms = classroom_rows()
    assigned_classroom = teacher.get("classroom_id")
    if (
        teacher.get("role") == "Professor"
        and teacher.get("teacher_type") == "Regular"
        and assigned_classroom is not None
    ):
        return [row for row in rooms if row["id"] == int(assigned_classroom)]
    return rooms


def get_authorized_user(registry: str) -> sqlite3.Row | None:
    return fetch_one(
        "SELECT registry, role, full_name, email, teacher_type, classroom_id, active "
        "FROM authorized_users WHERE registry = ?",
        (registry.strip().lower(),),
    )
def add_student(
    name: str,
    classroom_id: int,
    code: str = "",
    *,
    allergies: str = "",
    food_restrictions: str = "",
    authorized_pickup: str = "",
    emergency_contact: str = "",
    avatar: str = "👶",
) -> str:
    with connection_scope() as connection:
        if not code.strip():
            next_id = connection.execute(
                "SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM students"
            ).fetchone()["next_id"]
            code = f"ALU-{next_id:03d}"
        connection.execute(
            """
            INSERT INTO students
                (code, name, classroom_id, allergies, food_restrictions,
                 authorized_pickup, emergency_contact, avatar)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                code.strip().upper(),
                name.strip(),
                classroom_id,
                allergies.strip(),
                food_restrictions.strip(),
                authorized_pickup.strip(),
                emergency_contact.strip(),
                avatar.strip() or "👶",
            ),
        )
    return code.strip().upper()


def update_student(
    student_id: int,
    name: str,
    classroom_id: int,
    allergies: str,
    food_restrictions: str,
    authorized_pickup: str,
    emergency_contact: str,
    avatar: str,
    active: bool,
) -> None:
    with connection_scope() as connection:
        connection.execute(
            """
            UPDATE students
            SET name = ?, classroom_id = ?, allergies = ?, food_restrictions = ?,
                authorized_pickup = ?, emergency_contact = ?, avatar = ?, active = ?
            WHERE id = ?
            """,
            (
                name.strip(),
                classroom_id,
                allergies.strip(),
                food_restrictions.strip(),
                authorized_pickup.strip(),
                emergency_contact.strip(),
                avatar.strip() or "👶",
                int(active),
                student_id,
            ),
        )


def add_authorized_teacher(
    name: str,
    registry: str,
    email: str,
    teacher_type: str,
    role: str = "Professor",
    classroom_id: int | None = None,
) -> None:
    if role not in ("Professor", "Monitor"):
        raise ValueError("Cargo de funcionário inválido.")
    if teacher_type not in ("Regular", "AEE"):
        raise ValueError("Tipo de professor inválido.")
    with connection_scope() as connection:
        connection.execute(
            """
            INSERT INTO authorized_users
                (registry, role, full_name, email, teacher_type, classroom_id, active, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (
                registry.strip().lower(),
                role,
                name.strip(),
                email.strip().lower(),
                teacher_type if role == "Professor" else "Regular",
                classroom_id,
                datetime.now().isoformat(timespec="minutes"),
            ),
        )
def update_authorized_teacher(
    registry: str,
    name: str,
    email: str,
    role: str,
    teacher_type: str,
    classroom_id: int | None,
    active: bool,
) -> None:
    if role not in ("Professor", "Monitor"):
        raise ValueError("Cargo de funcionário inválido.")
    if teacher_type not in ("Regular", "AEE"):
        raise ValueError("Tipo de professor inválido.")
    with connection_scope() as connection:
        connection.execute(
            """
            UPDATE authorized_users
            SET full_name = ?, email = ?, role = ?, teacher_type = ?,
                classroom_id = ?, active = ?
            WHERE registry = ? AND role != 'Administrador'
            """,
            (
                name.strip(),
                email.strip().lower(),
                role,
                teacher_type if role == "Professor" else "Regular",
                classroom_id,
                int(active),
                registry.strip().lower(),
            ),
        )


def complete_teacher_profile(registry: str, name: str, email: str) -> None:
    with connection_scope() as connection:
        connection.execute(
            """
            UPDATE authorized_users
            SET full_name = CASE WHEN full_name = '' THEN ? ELSE full_name END,
                email = CASE WHEN email = '' THEN ? ELSE email END
            WHERE registry = ? AND role IN ('Professor', 'Monitor')
            """,
            (name.strip(), email.strip().lower(), registry.strip().lower()),
        )


def students_in_classroom(classroom_id: int) -> list[sqlite3.Row]:
    return fetch_all(
        """
        SELECT students.id, students.code, students.name, students.classroom_id,
               students.allergies, students.food_restrictions, students.authorized_pickup,
               students.emergency_contact, students.avatar, students.active,
               classrooms.name AS classroom
        FROM students JOIN classrooms ON classrooms.id = students.classroom_id
        WHERE classrooms.id = ? AND students.active = 1
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
        conflict = connection.execute(
            """
            SELECT start_time, end_time
            FROM reservations
            WHERE space = ? AND reservation_date = ?
              AND start_time < ? AND end_time > ?
            LIMIT 1
            """ or "",
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
            if status == "Presente":
                connection.execute("UPDATE students SET faltas_consecutivas = 0 WHERE id = ?", (student_id,))
            else:
                connection.execute("UPDATE students SET faltas_consecutivas = faltas_consecutivas + 1 WHERE id = ?", (student_id,))


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


def save_occurrence(
    student_id: int,
    occurrence_type: str,
    severity: str,
    details: str,
    occurrence_date: date,
    teacher: dict[str, str],
) -> None:
    with connection_scope() as connection:
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
                    "classroom_id": account["classroom_id"],
                }
                st.rerun()
        else:
            resolved_name = account["full_name"] or teacher_name.strip()
            resolved_email = account["email"] or normalized_email
            if not resolved_name:
                st.error("Preencha o nome ou solicite ao administrador que complete seu cadastro.")
            elif account["role"] == "Professor" and not resolved_email:
                st.error("Professores precisam ter um e-mail cadastrado.")
            elif resolved_email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", resolved_email):
                st.error("Informe um endereço de e-mail válido.")
            else:
                complete_teacher_profile(account["registry"], resolved_name, resolved_email)
                st.session_state["teacher_profile"] = {
                    "name": resolved_name,
                    "registry": account["registry"],
                    "email": resolved_email,
                    "role": account["role"],
                    "teacher_type": account["teacher_type"],
                    "classroom_id": account["classroom_id"],
                }
                st.rerun()


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
            st.markdown(f"{row['title']}")
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
    rooms = classrooms_for_teacher(teacher)
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
    )


def build_minutes_print_html(row: sqlite3.Row, teachers: list[sqlite3.Row]) -> str:
    payload = decode_plan_content(row["content"])
    subject_reports = payload.get("subject_reports", {})
    if not isinstance(subject_reports, dict):
        subject_reports = {}
        
    subject_sections = "".join(
        "<section class='subject-report'>"
        f"<h3>{html.escape(area)}</h3>"
        f"<div>{html.escape(str(subject_reports.get(area, ''))).replace(chr(10), '<br>')}</div>"
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
