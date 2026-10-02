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
