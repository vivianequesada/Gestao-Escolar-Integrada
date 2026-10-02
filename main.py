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
                classroom_id INTEGER NOT NULL REFERENCES classrooms(id),
                allergies TEXT NOT NULL DEFAULT '',
                food_restrictions TEXT NOT NULL DEFAULT '',
                authorized_pickup TEXT NOT NULL DEFAULT '',
                emergency_contact TEXT NOT NULL DEFAULT '',
                avatar TEXT NOT NULL DEFAULT '👶',
                active INTEGER NOT NULL DEFAULT 1
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
                "classroom_id": "INTEGER REFERENCES classrooms(id)",
            },
            "students": {
                "allergies": "TEXT NOT NULL DEFAULT ''",
                "food_restrictions": "TEXT NOT NULL DEFAULT ''",
                "authorized_pickup": "TEXT NOT NULL DEFAULT ''",
                "emergency_contact": "TEXT NOT NULL DEFAULT ''",
                "avatar": "TEXT NOT NULL DEFAULT '👶'",
                "active": "INTEGER NOT NULL DEFAULT 1",
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


def save_occurrence(
    student_id: int,
    occurrence_type: str,
    severity: str,
    details: str,
    occurrence_date: date,
    teacher: dict[str, str],
) -> None:
    with connection_scope() as connection:
        connection.execute(
            """
            INSERT INTO occurrences
                (student_id, occurrence_type, severity, details, occurrence_date,
                 teacher_name, teacher_registry, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                student_id,
                occurrence_type,
                severity,
                details.strip(),
                occurrence_date.isoformat(),
                teacher["name"],
                teacher["registry"],
                datetime.now().isoformat(timespec="minutes"),
            ),
        )


def save_development_report(
    student_id: int,
    report_date: date,
    social_interaction: str,
    motor_language_development: str,
    teacher: dict[str, str],
) -> None:
    with connection_scope() as connection:
        connection.execute(
            """
            INSERT INTO development_reports
                (student_id, report_date, social_interaction, motor_language_development,
                 teacher_name, teacher_registry, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                student_id,
                report_date.isoformat(),
                social_interaction.strip(),
                motor_language_development.strip(),
                teacher["name"],
                teacher["registry"],
                datetime.now().isoformat(timespec="minutes"),
            ),
        )


def consecutive_absence_alerts(minimum_streak: int = 3) -> list[dict[str, str | int]]:
    rows = fetch_all(
        """
        SELECT students.id AS student_id, students.name, students.code,
               students.emergency_contact, classrooms.name AS classroom,
               attendance.attendance_date, attendance.status
        FROM attendance
        JOIN students ON students.id = attendance.student_id
        JOIN classrooms ON classrooms.id = students.classroom_id
        WHERE students.active = 1
        ORDER BY students.id, attendance.attendance_date DESC, attendance.id DESC
        """
    )
    by_student: dict[int, list[sqlite3.Row]] = {}
    for row in rows:
        by_student.setdefault(row["student_id"], []).append(row)

    alerts: list[dict[str, str | int]] = []
    for student_rows in by_student.values():
        streak = 0
        for row in student_rows:
            if row["status"] == "Presente":
                break
            streak += 1
        if streak >= minimum_streak:
            latest = student_rows[0]
            alerts.append(
                {
                    "student_id": latest["student_id"],
                    "name": latest["name"],
                    "code": latest["code"],
                    "classroom": latest["classroom"],
                    "emergency_contact": latest["emergency_contact"],
                    "streak": streak,
                    "last_absence": latest["attendance_date"],
                }
            )
    return sorted(alerts, key=lambda alert: (-int(alert["streak"]), str(alert["name"])))


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
    rooms = classrooms_for_teacher(teacher)
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
                bncc_experiences = st.multiselect(
                    "Campos de Experiência (BNCC)",
                    BNCC_EXPERIENCES,
                    key="regular_plan_bncc",
                )
                general_activities = st.text_area(
                    "Descrição das vivências e brincadeiras",
                    height=110,
                    key="regular_plan_general_activities",
                )
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
                if not bncc_experiences:
                    st.error("Selecione ao menos um Campo de Experiência da BNCC.")
                elif not general_activities.strip():
                    st.error("Descreva as vivências e brincadeiras do período.")
                elif missing_areas:
                    st.error("Preencha as seis áreas. Faltam: " + ", ".join(missing_areas))
                else:
                    record_id = save_plan_or_minutes(
                        "Planejamento Quinzenal",
                        record_date,
                        room_ids[room_name],
                        "Planejamento por áreas",
                        f"Planejamento Quinzenal — {month_name} — {quinzena}",
                        json.dumps(
                            {
                                "activities": activities,
                                "bncc_experiences": bncc_experiences,
                                "general_activities": general_activities.strip(),
                            },
                            ensure_ascii=False,
                        ),
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
                WHERE students.active = 1 AND classrooms.name IN ({})
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
                bncc_experiences = payload.get("bncc_experiences", [])
                if bncc_experiences:
                    st.markdown("**Campos de Experiência (BNCC)**")
                    st.write(", ".join(bncc_experiences))
                if payload.get("general_activities"):
                    st.markdown("**Vivências e brincadeiras**")
                    st.write(payload["general_activities"])
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
    st.caption("Consulte os alunos ativos e os registros pedagógicos vinculados ao seu acesso.")
    rooms = classrooms_for_teacher(teacher)
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
    if teacher.get("role") == "Administrador":
        with st.expander("Dados de segurança do aluno"):
            st.write(f"**Alergias:** {student['allergies'] or 'Não informado'}")
            st.write(f"**Restrições alimentares:** {student['food_restrictions'] or 'Não informado'}")
            st.write(f"**Autorizados para retirada:** {student['authorized_pickup'] or 'Não informado'}")
            st.write(f"**Contato de emergência:** {student['emergency_contact'] or 'Não informado'}")

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


def render_student_safety() -> None:
    st.subheader("Carômetro de Segurança Escolar")
    st.caption("Acesso rápido a informações necessárias para o cuidado e a retirada dos alunos.")
    search = st.text_input("Buscar aluno por nome, código ou turma")
    pattern = f"%{search.strip()}%"
    students = fetch_all(
        """
        SELECT students.id, students.code, students.name, students.allergies,
               students.food_restrictions, students.authorized_pickup,
               students.emergency_contact, students.avatar,
               classrooms.name AS classroom
        FROM students
        JOIN classrooms ON classrooms.id = students.classroom_id
        WHERE students.active = 1
          AND (? = '' OR students.name LIKE ? OR students.code LIKE ? OR classrooms.name LIKE ?)
        ORDER BY students.name
        """,
        (search.strip(), pattern, pattern, pattern),
    )
    if not students:
        st.info("Nenhum aluno ativo corresponde à busca.")
        return
    for student in students:
        with st.container(border=True):
            avatar = student["avatar"] or "👶"
            st.subheader(f"{avatar} {student['name']}")
            st.caption(f"{student['classroom']} · {student['code']}")
            left, right = st.columns(2)
            with left:
                st.markdown(f"**Alergias:** {student['allergies'] or 'Não informado'}")
                st.markdown(
                    f"**Restrições alimentares:** "
                    f"{student['food_restrictions'] or 'Não informado'}"
                )
            with right:
                st.markdown(
                    f"**Autorizados para retirada:** "
                    f"{student['authorized_pickup'] or 'Não informado'}"
                )
                st.markdown(
                    f"**Contato de emergência:** "
                    f"{student['emergency_contact'] or 'Não informado'}"
                )


def render_occurrences(teacher: dict[str, str], admin_view: bool = False) -> None:
    st.subheader("Ocorrências da Rotina")
    if not admin_view:
        rooms = classrooms_for_teacher(teacher)
        if not rooms:
            st.info("Nenhuma turma está disponível para este cadastro.")
            return
        room_name = st.selectbox(
            "Turma da ocorrência",
            [row["name"] for row in rooms],
            key="occurrence_room",
        )
        classroom_id = next(row["id"] for row in rooms if row["name"] == room_name)
        students = students_in_classroom(classroom_id)
        if not students:
            st.info("Não há alunos ativos nesta turma.")
            return
        student_labels = {
            f"{row['name']} · {row['code']}": row["id"] for row in students
        }
        with st.form("occurrence_form", clear_on_submit=True):
            student_label = st.selectbox("Criança envolvida", list(student_labels))
            occurrence_type = st.selectbox("Tipo de ocorrência", OCCURRENCE_TYPES)
            severity = st.select_slider(
                "Classificação de gravidade",
                options=OCCURRENCE_SEVERITIES,
            )
            occurrence_date = st.date_input("Data da ocorrência", value=date.today())
            details = st.text_area("Descrição detalhada", height=120)
            submitted = st.form_submit_button("Registrar ocorrência", type="primary")
        if submitted:
            if not details.strip():
                st.error("Descreva a ocorrência antes de registrar.")
            else:
                save_occurrence(
                    student_labels[student_label],
                    occurrence_type,
                    severity,
                    details,
                    occurrence_date,
                    teacher,
                )
                st.success("Ocorrência registrada.")

    if admin_view:
        rows = fetch_all(
            """
            SELECT occurrences.id, occurrences.occurrence_type, occurrences.severity,
                   occurrences.details, occurrences.occurrence_date,
                   occurrences.teacher_name, students.name AS student_name,
                   students.code, classrooms.name AS classroom
            FROM occurrences
            JOIN students ON students.id = occurrences.student_id
            JOIN classrooms ON classrooms.id = students.classroom_id
            ORDER BY occurrences.occurrence_date DESC, occurrences.id DESC
            """
        )
    else:
        rows = fetch_all(
            """
            SELECT occurrences.id, occurrences.occurrence_type, occurrences.severity,
                   occurrences.details, occurrences.occurrence_date,
                   occurrences.teacher_name, students.name AS student_name,
                   students.code, classrooms.name AS classroom
            FROM occurrences
            JOIN students ON students.id = occurrences.student_id
            JOIN classrooms ON classrooms.id = students.classroom_id
            WHERE occurrences.teacher_registry = ?
            ORDER BY occurrences.occurrence_date DESC, occurrences.id DESC
            """,
            (teacher["registry"],),
        )
    st.divider()
    st.markdown("#### Histórico de ocorrências")
    if not rows:
        st.info("Nenhuma ocorrência registrada.")
        return
    for row in rows:
        with st.expander(
            f"{row['occurrence_type']} · {row['student_name']} · "
            f"{format_date(row['occurrence_date'])} · {row['severity']}"
        ):
            st.caption(f"{row['classroom']} · {row['code']} · Registrado por {row['teacher_name']}")
            st.write(row["details"])


def render_development_reports(teacher: dict[str, str], admin_view: bool = False) -> None:
    st.subheader("Relatório Descritivo de Desenvolvimento")
    if not admin_view:
        rooms = classrooms_for_teacher(teacher)
        if not rooms:
            st.info("Nenhuma turma está disponível para este cadastro.")
            return
        room_name = st.selectbox(
            "Turma do relatório",
            [row["name"] for row in rooms],
            key="development_report_room",
        )
        classroom_id = next(row["id"] for row in rooms if row["name"] == room_name)
        students = students_in_classroom(classroom_id)
        if not students:
            st.info("Não há alunos ativos nesta turma.")
            return
        student_labels = {
            f"{row['name']} · {row['code']}": row["id"] for row in students
        }
        with st.form("development_report_form", clear_on_submit=True):
            student_label = st.selectbox("Aluno", list(student_labels))
            report_date = st.date_input("Data do parecer", value=date.today())
            social_interaction = st.text_area("Aspectos sociais e interação", height=120)
            motor_language_development = st.text_area(
                "Desenvolvimento motor e linguagem",
                height=120,
            )
            submitted = st.form_submit_button("Salvar parecer pedagógico", type="primary")
        if submitted:
            if not social_interaction.strip() or not motor_language_development.strip():
                st.error("Preencha os dois campos do relatório descritivo.")
            else:
                save_development_report(
                    student_labels[student_label],
                    report_date,
                    social_interaction,
                    motor_language_development,
                    teacher,
                )
                st.success("Relatório descritivo salvo.")

    query = """
        SELECT development_reports.id, development_reports.report_date,
               development_reports.social_interaction,
               development_reports.motor_language_development,
               development_reports.teacher_name, students.name AS student_name,
               students.code, classrooms.name AS classroom
        FROM development_reports
        JOIN students ON students.id = development_reports.student_id
        JOIN classrooms ON classrooms.id = students.classroom_id
    """
    parameters: tuple = ()
    if not admin_view and teacher.get("classroom_id") is not None:
        query += " WHERE students.classroom_id = ?"
        parameters = (teacher["classroom_id"],)
    query += " ORDER BY development_reports.report_date DESC, development_reports.id DESC"
    rows = fetch_all(query, parameters)
    st.divider()
    st.markdown("#### Relatórios registrados")
    if not rows:
        st.info("Nenhum relatório descritivo registrado.")
        return
    for row in rows:
        with st.expander(
            f"{row['student_name']} · {row['classroom']} · "
            f"{format_date(row['report_date'])}"
        ):
            st.markdown("**Aspectos sociais e interação**")
            st.write(row["social_interaction"])
            st.markdown("**Desenvolvimento motor e linguagem**")
            st.write(row["motor_language_development"])
            st.caption(f"Registrado por {row['teacher_name']}")


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


def render_absence_alerts() -> None:
    st.subheader("Alertas de faltas consecutivas")
    st.caption(
        "Conta ausências nos dias com chamada registrada; faltas justificadas também contam."
    )
    alerts = consecutive_absence_alerts(minimum_streak=3)
    if not alerts:
        st.success("Nenhum aluno ativo atingiu três ausências consecutivas nas chamadas registradas.")
        return
    for alert in alerts:
        contact = alert["emergency_contact"] or "Contato de emergência não cadastrado"
        st.error(
            f"{alert['name']} ({alert['code']}) · {alert['classroom']} — "
            f"{alert['streak']} ausências consecutivas. "
            f"Última chamada: {format_date(str(alert['last_absence']))}. "
            f"Contato: {contact}."
        )


def render_admin_student_management() -> None:
    rooms = classroom_rows()
    room_names = [row["name"] for row in rooms]
    action = st.radio(
        "Operação de alunos",
        ["Cadastrar novo", "Editar / ativar ou arquivar"],
        horizontal=True,
        key="admin_student_action",
    )

    if action == "Cadastrar novo":
        with st.form("admin_student_form", clear_on_submit=True):
            student_name = st.text_input("Nome do aluno")
            room_name = st.selectbox("Turma", room_names, key="admin_new_student_room")
            student_code = st.text_input(
                "Código do aluno (opcional)",
                placeholder="Gerado automaticamente se vazio",
            )
            allergies = st.text_area("Alergias", height=70)
            food_restrictions = st.text_area("Restrições alimentares", height=70)
            authorized_pickup = st.text_area("Pessoas autorizadas para retirada", height=70)
            emergency_contact = st.text_input("Contato de emergência")
            avatar = st.text_input("Ícone do carômetro", value="👶", max_chars=8)
            submitted = st.form_submit_button("Cadastrar aluno", type="primary")
        if submitted:
            if not student_name.strip():
                st.error("Informe o nome do aluno.")
            else:
                classroom_id = next(row["id"] for row in rooms if row["name"] == room_name)
                try:
                    created_code = add_student(
                        student_name,
                        classroom_id,
                        student_code,
                        allergies=allergies,
                        food_restrictions=food_restrictions,
                        authorized_pickup=authorized_pickup,
                        emergency_contact=emergency_contact,
                        avatar=avatar,
                    )
                    st.success(f"Aluno cadastrado em {room_name}. Código: {created_code}.")
                except sqlite3.IntegrityError:
                    st.error("Esse código já está em uso. Informe outro código ou deixe o campo vazio.")
    else:
        student_rows = fetch_all(
            """
            SELECT students.id, students.code, students.name, students.classroom_id,
                   students.allergies, students.food_restrictions,
                   students.authorized_pickup, students.emergency_contact,
                   students.avatar, students.active, classrooms.name AS classroom
            FROM students
            JOIN classrooms ON classrooms.id = students.classroom_id
            WHERE classrooms.name IN ({})
            ORDER BY students.active DESC, students.name
            """.format(",".join("?" for _ in SALAS_CADASTRADAS)),
            SALAS_CADASTRADAS,
        )
        if not student_rows:
            st.info("Ainda não há alunos cadastrados.")
        else:
            student_labels = {
                (
                    f"{row['name']} · {row['code']} · {row['classroom']}"
                    f"{'' if row['active'] else ' · Arquivado'}"
                ): row["id"]
                for row in student_rows
            }
            selected_label = st.selectbox("Selecione o aluno", list(student_labels))
            student = next(
                row for row in student_rows if row["id"] == student_labels[selected_label]
            )
            selected_room_index = (
                room_names.index(student["classroom"])
                if student["classroom"] in room_names
                else 0
            )
            with st.form(f"edit_student_form_{student['id']}"):
                student_name = st.text_input(
                    "Nome do aluno",
                    value=student["name"],
                    key=f"edit_student_name_{student['id']}",
                )
                room_name = st.selectbox(
                    "Turma",
                    room_names,
                    index=selected_room_index,
                    key=f"edit_student_room_{student['id']}",
                )
                st.text_input("Código do aluno", value=student["code"], disabled=True)
                allergies = st.text_area(
                    "Alergias",
                    value=student["allergies"],
                    key=f"edit_student_allergies_{student['id']}",
                    height=70,
                )
                food_restrictions = st.text_area(
                    "Restrições alimentares",
                    value=student["food_restrictions"],
                    key=f"edit_student_food_{student['id']}",
                    height=70,
                )
                authorized_pickup = st.text_area(
                    "Pessoas autorizadas para retirada",
                    value=student["authorized_pickup"],
                    key=f"edit_student_pickup_{student['id']}",
                    height=70,
                )
                emergency_contact = st.text_input(
                    "Contato de emergência",
                    value=student["emergency_contact"],
                    key=f"edit_student_contact_{student['id']}",
                )
                avatar = st.text_input(
                    "Ícone do carômetro",
                    value=student["avatar"] or "👶",
                    max_chars=8,
                    key=f"edit_student_avatar_{student['id']}",
                )
                active = st.checkbox(
                    "Cadastro ativo",
                    value=bool(student["active"]),
                    key=f"edit_student_active_{student['id']}",
                )
                confirm_archive = st.checkbox(
                    "Confirmo o arquivamento, se o cadastro estiver inativo",
                    key=f"confirm_archive_student_{student['id']}",
                )
                submitted = st.form_submit_button("Salvar alterações", type="primary")
            if submitted:
                if not student_name.strip():
                    st.error("Informe o nome do aluno.")
                elif bool(student["active"]) and not active and not confirm_archive:
                    st.error("Confirme o arquivamento para preservar o histórico sem exibir o aluno nos cadastros ativos.")
                else:
                    classroom_id = next(row["id"] for row in rooms if row["name"] == room_name)
                    update_student(
                        student["id"],
                        student_name,
                        classroom_id,
                        allergies,
                        food_restrictions,
                        authorized_pickup,
                        emergency_contact,
                        avatar,
                        active,
                    )
                    st.success("Cadastro do aluno atualizado.")

    student_rows = fetch_all(
        """
        SELECT students.code, students.name, classrooms.name AS classroom,
               students.active
        FROM students
        JOIN classrooms ON classrooms.id = students.classroom_id
        WHERE classrooms.name IN ({})
        ORDER BY classrooms.name, students.name
        """.format(",".join("?" for _ in SALAS_CADASTRADAS)),
        SALAS_CADASTRADAS,
    )
    st.markdown("#### Alunos cadastrados")
    st.dataframe(
        [
            {
                "Código": row["code"],
                "Aluno": row["name"],
                "Turma": row["classroom"],
                "Situação": "Ativo" if row["active"] else "Arquivado",
            }
            for row in student_rows
        ],
        width="stretch",
        hide_index=True,
    )


def staff_label(row: sqlite3.Row) -> str:
    if row["role"] == "Monitor":
        return "Monitor"
    return "Professor AEE" if row["teacher_type"] == "AEE" else "Professor Regular"


def render_admin_staff_management() -> None:
    rooms = classroom_rows()
    room_names = [row["name"] for row in rooms]
    classroom_options = ["Sem turma específica", *room_names]
    action = st.radio(
        "Operação da equipe",
        ["Cadastrar novo", "Editar / ativar ou arquivar"],
        horizontal=True,
        key="admin_staff_action",
    )
    role_options = ["Professor Regular", "Professor AEE", "Monitor"]

    if action == "Cadastrar novo":
        with st.form("admin_teacher_form", clear_on_submit=True):
            teacher_name = st.text_input("Nome completo")
            teacher_registry = st.text_input("Matrícula permitida")
            teacher_email = st.text_input("E-mail institucional (obrigatório para professores)")
            role_label = st.selectbox("Cargo do profissional", role_options)
            classroom_label = st.selectbox("Turma atribuída", classroom_options)
            submitted = st.form_submit_button("Cadastrar profissional", type="primary")
        if submitted:
            registry = teacher_registry.strip().lower()
            email = teacher_email.strip().lower()
            role = "Monitor" if role_label == "Monitor" else "Professor"
            teacher_type = "AEE" if role_label == "Professor AEE" else "Regular"
            classroom_id = (
                None
                if classroom_label == "Sem turma específica"
                else next(row["id"] for row in rooms if row["name"] == classroom_label)
            )
            if not teacher_name.strip() or not registry:
                st.error("Preencha o nome e a matrícula.")
            elif registry == "adm123":
                st.error("Essa matrícula é reservada ao administrador.")
            elif role == "Professor" and not email:
                st.error("Professores precisam ter um e-mail cadastrado.")
            elif email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
                st.error("Informe um endereço de e-mail válido ou deixe-o em branco para Monitores.")
            else:
                try:
                    add_authorized_teacher(
                        teacher_name,
                        registry,
                        email,
                        teacher_type,
                        role=role,
                        classroom_id=classroom_id,
                    )
                    st.success(f"{role_label} cadastrado e autorizado a entrar.")
                except sqlite3.IntegrityError:
                    st.error("Essa matrícula já está cadastrada.")
    else:
        staff_rows = fetch_all(
            """
            SELECT authorized_users.registry, authorized_users.role,
                   authorized_users.full_name, authorized_users.email,
                   authorized_users.teacher_type, authorized_users.classroom_id,
                   authorized_users.active, classrooms.name AS classroom
            FROM authorized_users
            LEFT JOIN classrooms ON classrooms.id = authorized_users.classroom_id
            WHERE authorized_users.role IN ('Professor', 'Monitor')
            ORDER BY authorized_users.active DESC, authorized_users.full_name,
                     authorized_users.registry
            """
        )
        if not staff_rows:
            st.info("Ainda não há professores ou Monitores cadastrados.")
        else:
            staff_labels = {
                (
                    f"{row['full_name'] or row['registry']} · {row['registry']} · "
                    f"{staff_label(row)}"
                    f"{'' if row['active'] else ' · Arquivado'}"
                ): row["registry"]
                for row in staff_rows
            }
            selected_label = st.selectbox("Selecione o profissional", list(staff_labels))
            staff = next(
                row for row in staff_rows if row["registry"] == staff_labels[selected_label]
            )
            current_role = staff_label(staff)
            current_room = staff["classroom"] or "Sem turma específica"
            room_index = (
                classroom_options.index(current_room)
                if current_room in classroom_options
                else 0
            )
            with st.form(f"edit_staff_form_{staff['registry']}"):
                name = st.text_input(
                    "Nome completo",
                    value=staff["full_name"],
                    key=f"edit_staff_name_{staff['registry']}",
                )
                st.text_input("Matrícula", value=staff["registry"], disabled=True)
                email = st.text_input(
                    "E-mail institucional",
                    value=staff["email"],
                    key=f"edit_staff_email_{staff['registry']}",
                )
                role_label = st.selectbox(
                    "Cargo do profissional",
                    role_options,
                    index=role_options.index(current_role),
                    key=f"edit_staff_role_{staff['registry']}",
                )
                classroom_label = st.selectbox(
                    "Turma atribuída",
                    classroom_options,
                    index=room_index,
                    key=f"edit_staff_room_{staff['registry']}",
                )
                active = st.checkbox(
                    "Cadastro ativo",
                    value=bool(staff["active"]),
                    key=f"edit_staff_active_{staff['registry']}",
                )
                confirm_archive = st.checkbox(
                    "Confirmo o arquivamento, se o cadastro estiver inativo",
                    key=f"confirm_archive_staff_{staff['registry']}",
                )
                submitted = st.form_submit_button("Salvar alterações", type="primary")
            if submitted:
                email = email.strip().lower()
                role = "Monitor" if role_label == "Monitor" else "Professor"
                teacher_type = "AEE" if role_label == "Professor AEE" else "Regular"
                classroom_id = (
                    None
                    if classroom_label == "Sem turma específica"
                    else next(row["id"] for row in rooms if row["name"] == classroom_label)
                )
                if not name.strip():
                    st.error("Informe o nome do profissional.")
                elif role == "Professor" and not email:
                    st.error("Professores precisam ter um e-mail cadastrado.")
                elif email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
                    st.error("Informe um endereço de e-mail válido.")
                elif bool(staff["active"]) and not active and not confirm_archive:
                    st.error("Confirme o arquivamento do cadastro.")
                else:
                    update_authorized_teacher(
                        staff["registry"],
                        name,
                        email,
                        role,
                        teacher_type,
                        classroom_id,
                        active,
                    )
                    st.success("Cadastro do profissional atualizado.")

    staff_rows = fetch_all(
        """
        SELECT authorized_users.registry, authorized_users.role,
               authorized_users.full_name, authorized_users.email,
               authorized_users.teacher_type, authorized_users.active,
               classrooms.name AS classroom
        FROM authorized_users
        LEFT JOIN classrooms ON classrooms.id = authorized_users.classroom_id
        WHERE authorized_users.role IN ('Professor', 'Monitor')
        ORDER BY authorized_users.active DESC, authorized_users.full_name,
                 authorized_users.registry
        """
    )
    st.markdown("#### Equipe cadastrada")
    st.dataframe(
        [
            {
                "Matrícula": row["registry"],
                "Nome": row["full_name"] or "Nome não informado",
                "Cargo": staff_label(row),
                "Turma": row["classroom"] or "Sem turma específica",
                "E-mail": row["email"] or "Não informado",
                "Situação": "Ativo" if row["active"] else "Arquivado",
            }
            for row in staff_rows
        ],
        width="stretch",
        hide_index=True,
    )


def render_admin_panel() -> None:
    st.subheader("Painel de Controle")
    st.caption("Cadastros disponíveis somente para a matrícula administrativa.")
    render_absence_alerts()
    st.divider()
    students_tab, staff_tab = st.tabs(["Gerenciar alunos", "Gerenciar equipe"])
    with students_tab:
        render_admin_student_management()
    with staff_tab:
        render_admin_staff_management()


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
        teacher["classroom_id"] = account["classroom_id"]
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
    MONITOR_PAGE,
]
if teacher["role"] == "Administrador":
    pages = admin_pages
elif teacher["role"] == "Monitor":
    pages = [MONITOR_PAGE]
elif teacher.get("teacher_type") == "AEE":
    pages = [
        "📋 Chamada Diária",
        "🧒 Carômetro e Histórico de Alunos",
        "📝 Planejamentos & Atas de Conselho",
        "🏢 Agendamento de Espaços",
    ]
else:
    pages = PEDAGOGICAL_PAGES

with st.sidebar:
    st.title("Portal Digital")
    role_label = (
        f"Professor {'AEE' if teacher.get('teacher_type') == 'AEE' else 'Regular'}"
        if teacher["role"] == "Professor"
        else teacher["role"]
    )
    st.subheader(role_label)
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
elif selected_page == "🚨 Ocorrências da Rotina":
    render_occurrences(teacher, admin_view=teacher["role"] == "Administrador")
elif selected_page == "📝 Relatório Descritivo":
    render_development_reports(teacher, admin_view=teacher["role"] == "Administrador")
elif selected_page == "📢 Quadro de Avisos":
    if teacher["role"] == "Administrador":
        render_announcements()
elif selected_page == "🧩 Relatório de Inclusão AEE":
    if teacher["role"] == "Administrador":
        render_aee_reports(teacher)
elif selected_page == MONITOR_PAGE:
    render_student_safety()
        # =====================================================================
    # PERFIL: ADMINISTRADOR (Painel Geral da Direção + CRUD Completo)
    # =====================================================================
elif usuario['cargo'] == "Administrador":
        st.header("⚙️ Painel de Controle da Direção e Coordenação")
        
        # 1. Alertas Críticos de Faltas
        st.subheader("🚨 Central de Alertas Críticos (Faltas Consecutivas)")
        alertas_ativos = False
        for aluno in st.session_state.alunos_db:
            if aluno['faltas_consecutivas'] >= 3:
                alertas_ativos = True
                st.error(f"⚠️ **ALERTA:** A criança **{aluno['nome']}** ({aluno['turma']}) acumulou **{aluno['faltas_consecutivas']} faltas seguidas**. Contato: **{aluno['contato']}**")
        if not alertas_ativos: st.success("✅ Nenhuma evasão detectada.")
            
        st.divider()
        
        # Abas de Gestão Administrativa (CRUD)
        maba1, maba2, maba3 = st.tabs(["👥 Gerenciar Professores", "👶 Gerenciar Alunos", "📋 Histórico de Ocorrências"])
        
        # CRUD PROFESSORES
        with maba1:
            st.subheader("Gerenciamento de Funcionários")
            acao_p = st.radio("Operação (Professores):", ["Cadastrar Novo", "Editar Perfil", "Excluir Registro"], horizontal=True)
            
            if acao_p == "Cadastrar Novo":
                with st.form("add_prof", clear_on_submit=True):
                    mat_n = st.text_input("Nova Matrícula (Código de Acesso):")
                    nome_p = st.text_input("Nome Completo:")
                    cargo_p = st.selectbox("Cargo:", ["Professor Regular", "Professor AEE", "Monitor", "Administrador"])
                    turma_p = st.selectbox("Turma Atribuída:", ["Berçário", "Maternal I", "Maternal II", "Pré I", "Pré II", "Geral"])
                    if st.form_submit_button("➕ Salvar Funcionário"):
                        if mat_n and nome_p:
                            st.session_state.professores_db[mat_n] = {"nome": nome_p, "cargo": cargo_p, "turma": turma_p}
                            salvar_dados("db")
                            st.success(f"{nome_p} cadastrado!")
                            st.rerun()
            
            elif acao_p == "Editar Perfil":
                p_sel = st.selectbox("Selecione para Editar:", list(st.session_state.professores_db.keys()), format_func=lambda x: f"{st.session_state.professores_db[x]['nome']} ({x})")
                with st.form("edit_prof"):
                    nome_e = st.text_input("Alterar Nome:", value=st.session_state.professores_db[p_sel]['nome'])
                    cargo_e = st.selectbox("Alterar Cargo:", ["Professor Regular", "Professor AEE", "Monitor", "Administrador"], index=["Professor Regular", "Professor AEE", "Monitor", "Administrador"].index(st.session_state.professores_db[p_sel]['cargo']))
                    turma_e = st.selectbox("Alterar Turma:", ["Berçário", "Maternal I", "Maternal II", "Pré I", "Pré II", "Geral", "Inclusão Geral", "Plantão"], value=st.session_state.professores_db[p_sel]['turma'])
                    if st.form_submit_button("💾 Atualizar Dados"):
                        st.session_state.professores_db[p_sel] = {"nome": nome_e, "cargo": cargo_e, "turma": turma_e}
                        salvar_dados("db")
                        st.success("Dados updated!")
                        st.rerun()
                        
            elif acao_p == "Excluir Registro":
                p_del = st.selectbox("Selecione para Deletar:", list(st.session_state.professores_db.keys()), format_func=lambda x: f"{st.session_state.professores_db[x]['nome']} ({x})")
                if st.button("❌ Confirmar Exclusão Definitiva"):
                    if p_del == matricula:
                        st.error("Você não pode excluir a sua própria conta ativa.")
                    else:
                        del st.session_state.professores_db[p_del]
                        salvar_dados("db")
                        st.success("Funcionário removido com sucesso!")
                        st.rerun()

        # CRUD ALUNOS (ATUALIZADO COM EXCLUSÃO MANUAL POR ID/NOME)
        with maba2:
            st.subheader("Gerenciamento do Carômetro de Alunos")
            acao_a = st.radio("Operação (Alunos):", ["Cadastrar Novo Aluno", "Editar Ficha de Saúde", "Excluir Aluno (Lista)", "Excluir Aluno (Manual)"], horizontal=True)
            
            if acao_a == "Cadastrar Novo Aluno":
                with st.form("add_aluno", clear_on_submit=True):
                    nome_n = st.text_input("Nome Completo do Aluno:")
                    turma_n = st.selectbox("Turma Escolar:", ["Berçário", "Maternal I", "Maternal II", "Pré I", "Pré II"])
                    alergias_n = st.text_input("Alergias:", value="Nenhuma")
                    rest_n = st.text_input("Restrições Alimentares:", value="Nenhuma")
                    retirada_n = st.text_input("Autorizados para Retirada:")
                    contato_n = st.text_input("Contatos de Emergência:")
                    if st.form_submit_button("➕ Registrar Criança"):
                        if nome_n:
                            # Gera um ID sequencial seguro baseado no maior ID existente
                            ids_existentes = [int(a['id']) for a in st.session_state.alunos_db if a['id'].isdigit()]
                            novo_id = str(max(ids_existentes) + 1) if ids_existentes else "1"
                            
                            novo_a = {"id": novo_id, "nome": nome_n, "turma": turma_n, "alergias": allergies_n, "restricoes": rest_n, "retirada": retirada_n, "contato": contato_n, "foto": "👶", "faltas_consecutivas": 0}
                            st.session_state.alunos_db.append(novo_a)
                            salvar_dados("alunos")
                            st.success(f"{nome_n} adicionado com o ID: {novo_id}!")
                            st.rerun()
            
            elif acao_a == "Editar Ficha de Saúde":
                a_sel_idx = st.selectbox("Selecione a Criança:", range(len(st.session_state.alunos_db)), format_func=lambda x: f"ID: {st.session_state.alunos_db[x]['id']} - {st.session_state.alunos_db[x]['nome']}")
                aluno_e = st.session_state.alunos_db[a_sel_idx]
                with st.form("edit_aluno"):
                    nome_ae = st.text_input("Nome:", value=aluno_e['nome'])
                    turma_ae = st.selectbox("Turma:", ["Berçário", "Maternal I", "Maternal II", "Pré I", "Pré II"], index=["Berçário", "Maternal I", "Maternal II", "Pré I", "Pré II"].index(aluno_e['turma']))
                    alergias_ae = st.text_input("Alergias:", value=aluno_e['alergias'])
                    rest_ae = st.text_input("Restrições:", value=aluno_e['restricoes'])
                    retirada_ae = st.text_input("Retirada:", value=aluno_e['retirada'])
                    contato_ae = st.text_input("Contatos:", value=aluno_e['contato'])
                    if st.form_submit_button("💾 Salvar Alterações na Ficha"):
                        st.session_state.alunos_db[a_sel_idx] = {"id": aluno_e['id'], "nome": nome_ae, "turma": turma_ae, "alergias": allergies_ae, "restricoes": rest_ae, "retirada": retirada_ae, "contato": contato_ae, "foto": aluno_e['foto'], "faltas_consecutivas": aluno_e['faltas_consecutivas']}
                        salvar_dados("alunos")
                        st.success("Ficha atualizada!")
                        st.rerun()
                        
            elif acao_a == "Excluir Aluno (Lista)":
                a_del_idx = st.selectbox("Selecione o Aluno para Remover:", range(len(st.session_state.alunos_db)), format_func=lambda x: f"ID: {st.session_state.alunos_db[x]['id']} - {st.session_state.alunos_db[x]['nome']} ({st.session_state.alunos_db[x]['turma']})")
                if st.button("❌ Confirmar Exclusão Selecionada"):
                    nome_removido = st.session_state.alunos_db[a_del_idx]['nome']
                    st.session_state.alunos_db.pop(a_del_idx)
                    salvar_dados("alunos")
                    st.success(f"{nome_removido} removido do sistema!")
                    st.rerun()

            # NOVO MÓDULO: EXCLUSÃO MANUAL POR TEXTO (ID OU NOME EXACTO)
            elif acao_a == "Excluir Aluno (Manual)":
                st.warning("⚠️ Cuidado: Esta ação removerá o aluno de forma permanente do banco de dados.")
                termo_exclusao = st.text_input("Digite o ID exato ou o Nome Completo da criança para excluir:")
                
                if st.button("🗑️ Executar Exclusão Manual"):
                    aluno_encontrado = None
                    # Procura pelo ID ou pelo Nome Exato
                    for idx, aluno in enumerate(st.session_state.alunos_db):
                        if aluno['id'] == termo_exclusao.strip() or aluno['nome'].lower().strip() == termo_exclusao.lower().strip():
                            aluno_encontrado = idx
                            break
                    
                    if aluno_encontrado is not None:
                        nome_removido = st.session_state.alunos_db[aluno_encontrado]['nome']
                        st.session_state.alunos_db.pop(aluno_encontrado)
                        salvar_dados("alunos")
                        st.success(f"Sucesso! O registro de '{nome_removido}' foi completamente deletado.")
                        st.rerun()
                    else:
                        st.error("Nenhum aluno foi localizado com esse ID ou Nome exato. Verifique os dados e tente novamente.")

        # HISTÓRICO DE OCORRÊNCIAS
        with maba3:
            st.subheader("📋 Histórico Recente de Ocorrências")
            if st.session_state.get('ocorrencias_salvas'):
                for oc in reversed(st.session_state.ocorrencias_salvas):
                with st.expander(f"📌 {oc['tipo']} - {oc['aluno']}"):
# Verifique se o seu código está alinhado exatamente degrau por degrau assim:
for oc in reversed(st.session_state.ocorrencias_salvas):
    with st.expander(f"📌 {oc['tipo']} - {oc['aluno']}"):
        st.write(f"**Relator:** {oc['professor']} | **Gravidade:** {oc['gravidade']}") # <-- 4 ESPAÇOS A MAIS QUE O WITH
        st.info(f"**Detalhes:** {oc['detalhes']}")                                   # <-- 4 ESPAÇOS A MAIS QUE O WITH
