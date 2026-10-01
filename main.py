from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, time
from pathlib import Path
from typing import Iterator

import streamlit as st


APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "gestao_escolar.db"


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


@contextmanager
def connection_scope() -> Iterator[sqlite3.Connection]:
    connection = get_connection()
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
                created_at TEXT NOT NULL
            );
            """
        )


def fetch_all(query: str, parameters: tuple = ()) -> list[sqlite3.Row]:
    with connection_scope() as connection:
        return connection.execute(query, parameters).fetchall()


def format_date(value: str) -> str:
    return date.fromisoformat(value).strftime("%d/%m/%Y")


def add_announcement(title: str, category: str, audience: str, body: str) -> None:
    with connection_scope() as connection:
        connection.execute(
            """
            INSERT INTO announcements (title, category, audience, body, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (title.strip(), category, audience, body.strip(), datetime.now().isoformat(timespec="minutes")),
        )


def add_reservation(
    space: str,
    responsible: str,
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
            SELECT id, start_time, end_time
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
                (space, responsible, group_name, reservation_date, start_time, end_time, purpose, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                space,
                responsible.strip(),
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
) -> None:
    with connection_scope() as connection:
        connection.execute(
            """
            INSERT INTO aee_reports
                (student_ref, grade, period, goals, supports, progress, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )


def delete_record(table: str, record_id: int) -> None:
    allowed_tables = {"announcements", "reservations", "aee_reports"}
    if table not in allowed_tables:
        raise ValueError("Tipo de registro inválido.")
    with get_connection() as connection:
        connection.execute(f"DELETE FROM {table} WHERE id = ?", (record_id,))


def render_reservation_tab(space: str) -> None:
    st.subheader(f"Agendamento de {space.lower()}")
    st.caption("Cadastre um horário e consulte os agendamentos existentes. Conflitos de horário são bloqueados.")

    with st.form(f"reservation_form_{space}", clear_on_submit=True):
        col1, col2 = st.columns(2)
        responsible = col1.text_input("Responsável", placeholder="Nome do professor ou funcionário")
        group_name = col2.text_input("Turma ou grupo", placeholder="Ex.: 7º ano A")
        col3, col4, col5 = st.columns(3)
        reservation_date = col3.date_input("Data", min_value=date.today(), value=date.today())
        start_time = col4.time_input("Início", value=time(8, 0), step=1800)
        end_time = col5.time_input("Término", value=time(9, 0), step=1800)
        purpose = st.text_input("Atividade", placeholder="Ex.: aula de educação física")
        submitted = st.form_submit_button("Salvar agendamento", type="primary")

    if submitted:
        if not responsible.strip() or not group_name.strip() or not purpose.strip():
            st.error("Preencha o responsável, a turma ou grupo e a atividade.")
        elif end_time <= start_time:
            st.error("O horário de término deve ser posterior ao horário de início.")
        else:
            success, message = add_reservation(
                space, responsible, group_name, reservation_date, start_time, end_time, purpose
            )
            if success:
                st.success(message)
                st.rerun()
            else:
                st.warning(message)

    st.divider()
    st.subheader("Agenda")
    reservations = fetch_all(
        """
        SELECT id, reservation_date, start_time, end_time, group_name, responsible, purpose
        FROM reservations
        WHERE space = ?
        ORDER BY reservation_date, start_time
        """,
        (space,),
    )
    if not reservations:
        st.info("Nenhum agendamento cadastrado.")
        return

    st.dataframe(
        [
            {
                "Data": format_date(row["reservation_date"]),
                "Horário": f"{row['start_time']}–{row['end_time']}",
                "Turma/grupo": row["group_name"],
                "Responsável": row["responsible"],
                "Atividade": row["purpose"],
            }
            for row in reservations
        ],
        use_container_width=True,
        hide_index=True,
    )
    options = {
        f"{format_date(row['reservation_date'])} · {row['start_time']} · {row['group_name']} — {row['purpose']}": row["id"]
        for row in reservations
    }
    with st.form(f"delete_reservation_{space}"):
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


def build_aee_report_text(row: sqlite3.Row) -> str:
    return f"""RELATÓRIO DE ACOMPANHAMENTO — AEE

Referência do estudante: {row['student_ref']}
Turma: {row['grade']}
Período: {row['period']}
Situação: {row['status']}

Objetivos de aprendizagem e participação:
{row['goals']}

Atendimentos e recursos de apoio:
{row['supports']}

Avanços observados e próximos passos:
{row['progress']}

Registro criado em: {datetime.fromisoformat(row['created_at']).strftime('%d/%m/%Y %H:%M')}
"""


st.set_page_config(page_title="Gestão Escolar", layout="wide")
initialize_database()

st.title("Gestão Escolar")
st.caption("Organização de comunicados, espaços pedagógicos e acompanhamento da inclusão.")

announcements_tab, court_tab, computer_tab, aee_tab = st.tabs(
    ["Quadro de Avisos", "Agendamento de Quadra", "Agendamento de Informática", "Relatório de Inclusão AEE"]
)

with announcements_tab:
    st.subheader("Quadro de Avisos")
    with st.form("announcement_form", clear_on_submit=True):
        title = st.text_input("Título", max_chars=120)
        col1, col2 = st.columns(2)
        category = col1.selectbox("Categoria", ["Comunicado", "Evento", "Reunião", "Prazo", "Outro"])
        audience = col2.selectbox("Público", ["Toda a comunidade", "Estudantes", "Famílias", "Equipe escolar"])
        body = st.text_area("Mensagem", height=120, placeholder="Escreva as informações importantes do aviso.")
        submitted = st.form_submit_button("Publicar aviso", type="primary")
    if submitted:
        if not title.strip() or not body.strip():
            st.error("Informe o título e a mensagem do aviso.")
        else:
            add_announcement(title, category, audience, body)
            st.success("Aviso publicado.")
            st.rerun()

    st.divider()
    announcements = fetch_all("SELECT * FROM announcements ORDER BY created_at DESC, id DESC")
    if not announcements:
        st.info("Ainda não há avisos. Publique o primeiro comunicado acima.")
    else:
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

with court_tab:
    render_reservation_tab("Quadra")

with computer_tab:
    render_reservation_tab("Informática")

with aee_tab:
    st.subheader("Relatório de Inclusão — Atendimento Educacional Especializado")
    st.caption("Registre objetivos, apoios e avanços para apoiar o planejamento pedagógico.")
    st.warning(
        "Privacidade: use uma matrícula ou código interno no lugar do nome. "
        "Não registre diagnósticos ou detalhes de saúde. Este protótipo não possui login nem controle de acesso."
    )

    with st.form("aee_report_form", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        student_ref = col1.text_input("Código do estudante", placeholder="Ex.: AEE-024")
        grade = col2.text_input("Turma", placeholder="Ex.: 5º ano B")
        period = col3.text_input("Período de acompanhamento", placeholder="Ex.: 1º bimestre de 2026")
        goals = st.text_area("Objetivos de aprendizagem e participação", height=100)
        supports = st.text_area("Atendimentos, recursos e estratégias de apoio", height=100)
        progress = st.text_area("Avanços observados e próximos passos", height=100)
        status = st.selectbox("Situação do acompanhamento", ["Em acompanhamento", "Revisão necessária", "Concluído"])
        submitted = st.form_submit_button("Salvar relatório AEE", type="primary")
    if submitted:
        if not all([student_ref.strip(), grade.strip(), period.strip(), goals.strip(), supports.strip(), progress.strip()]):
            st.error("Preencha todos os campos do relatório.")
        else:
            add_aee_report(student_ref, grade, period, goals, supports, progress, status)
            st.success("Relatório registrado.")
            st.rerun()

    st.divider()
    st.subheader("Relatórios registrados")
    reports = fetch_all("SELECT * FROM aee_reports ORDER BY created_at DESC, id DESC")
    if not reports:
        st.info("Nenhum relatório AEE registrado.")
    else:
        report_options = {
            f"{row['student_ref']} · {row['grade']} · {row['period']}": row["id"] for row in reports
        }
        selected_label = st.selectbox("Selecione um relatório para consultar ou baixar", list(report_options))
        selected_report = next(row for row in reports if row["id"] == report_options[selected_label])
        with st.container(border=True):
            st.markdown(f"**Código:** {selected_report['student_ref']} &nbsp; · &nbsp; **Turma:** {selected_report['grade']}")
            st.caption(f"{selected_report['period']} · {selected_report['status']}")
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