from __future__ import annotations

from typing import Any, Optional
import streamlit as st
import psycopg
from psycopg.rows import dict_row


@st.cache_resource
def get_conn() -> psycopg.Connection:
    db_url = st.secrets["SUPABASE_DB_URL"]
    return psycopg.connect(db_url, row_factory=dict_row, autocommit=True)


def create_session(user_id: Optional[str] = None) -> str:
    conn = get_conn()
    row = conn.execute(
        """
        insert into public.sessions (user_id)
        values (%s)
        returning session_id::text
        """,
        (user_id,),
    ).fetchone()
    return row["session_id"]


def insert_shot(session_id: str, shot: dict[str, Any]) -> str:
    """
    Expects shot dict with ONLY:
      speed, launch_angle, side_angle, backspin, sidespin, carry, timestamp (ISO string)
    """
    conn = get_conn()
    row = conn.execute(
        """
        insert into public.shots (
          session_id, ts,
          speed, launch_angle, side_angle, backspin, sidespin, carry
        )
        values (
          %s, %s::timestamptz,
          %s, %s, %s, %s, %s, %s
        )
        returning shot_id::text
        """,
        (
            session_id,
            shot["timestamp"],                 # required
            shot.get("speed"),
            shot.get("launch_angle"),
            shot.get("side_angle"),
            shot.get("backspin"),
            shot.get("sidespin"),
            shot.get("carry"),
        ),
    ).fetchone()
    return row["shot_id"]


def upsert_insight_for_shot(
    shot_id: str,
    message: str,
    rule_id: Optional[str] = None,
    severity: Optional[int] = None,
) -> None:
    conn = get_conn()
    conn.execute(
        """
        insert into public.insights (shot_id, rule_id, severity, message)
        values (%s, %s, %s, %s)
        on conflict (shot_id)
        do update set
          rule_id = excluded.rule_id,
          severity = excluded.severity,
          message = excluded.message,
          created_at = now()
        """,
        (shot_id, rule_id, severity, message),
    )


def end_session(session_id: str) -> None:
    """
    Sets ended_at and stores summary averages computed from shots in the session.
    """
    conn = get_conn()

    stats = conn.execute(
        """
        select
          count(*)::int as num_shots,
          avg(speed) as avg_speed,
          avg(launch_angle) as avg_launch_angle,
          avg(side_angle) as avg_side_angle,
          avg(backspin) as avg_backspin,
          avg(sidespin) as avg_sidespin,
          avg(carry) as avg_carry
        from public.shots
        where session_id = %s
        """,
        (session_id,),
    ).fetchone()

    conn.execute(
        """
        update public.sessions
        set
          ended_at = now(),
          num_shots = %s,
          avg_speed = %s,
          avg_launch_angle = %s,
          avg_side_angle = %s,
          avg_backspin = %s,
          avg_sidespin = %s,
          avg_carry = %s
        where session_id = %s
        """,
        (
            stats["num_shots"],
            stats["avg_speed"],
            stats["avg_launch_angle"],
            stats["avg_side_angle"],
            stats["avg_backspin"],
            stats["avg_sidespin"],
            stats["avg_carry"],
            session_id,
        ),
    )


def list_sessions(limit: int = 25, user_id: Optional[str] = None) -> list[dict[str, Any]]:
    conn = get_conn()
    if user_id:
        rows = conn.execute(
            """
            select *
            from public.sessions
            where user_id = %s
            order by started_at desc
            limit %s
            """,
            (user_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            select *
            from public.sessions
            order by started_at desc
            limit %s
            """,
            (limit,),
        ).fetchall()
    return list(rows)


def get_session_shots(session_id: str) -> list[dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute(
        """
        select
          s.shot_id::text,
          s.ts,
          s.speed, s.launch_angle, s.side_angle, s.backspin, s.sidespin, s.carry,
          i.message as insight
        from public.shots s
        left join public.insights i on i.shot_id = s.shot_id
        where s.session_id = %s
        order by s.ts asc
        """,
        (session_id,),
    ).fetchall()
    return list(rows)