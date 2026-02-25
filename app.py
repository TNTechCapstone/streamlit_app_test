import random
from datetime import datetime, timezone
from typing import Any, Dict, Optional, List

import streamlit as st

from db import (
    create_session,
    end_session,
    insert_shot,
    upsert_insight_for_shot,
    list_sessions,
    get_session_shots,
)

st.set_page_config(page_title="Smart Golf Visor", layout="centered")

# ----------------------------
# Helpers (formatting)
# ----------------------------
def fmt_speed(mph: Optional[float]) -> str:
    return "—" if mph is None else f"{mph:.1f} mph"

def fmt_carry(yards: Optional[float]) -> str:
    # carry: no decimal precision
    return "—" if yards is None else f"{int(round(yards))} yd"

def fmt_launch(deg: Optional[float]) -> str:
    # launch angle: 1 decimal
    return "—" if deg is None else f"{deg:.1f}°"

def fmt_side(deg: Optional[float]) -> str:
    return "—" if deg is None else f"{deg:.1f}°"

def fmt_rpm(rpm: Optional[float]) -> str:
    return "—" if rpm is None else f"{int(round(rpm))} rpm"

def now_iso_z() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

def dt_to_iso_z(dt_val: Any) -> str:
    if dt_val is None:
        return "—"
    if isinstance(dt_val, str):
        return dt_val
    if isinstance(dt_val, datetime):
        if dt_val.tzinfo is None:
            dt_val = dt_val.replace(tzinfo=timezone.utc)
        return dt_val.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return str(dt_val)

def safe_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None

# ----------------------------
# Mock shot generator (schema-aligned)
# ----------------------------
def generate_mock_shot() -> Dict[str, Any]:
    speed = random.uniform(90.0, 165.0)          # mph
    launch_angle = random.uniform(8.0, 20.0)     # degrees
    side_angle = random.uniform(-6.0, 6.0)       # degrees
    backspin = random.uniform(1800.0, 4200.0)    # rpm
    sidespin = random.uniform(-900.0, 900.0)     # rpm
    carry = random.uniform(140.0, 290.0)         # yards

    if launch_angle < 10.0:
        insight = "Low launch — consider tee height or adding loft."
        rule_id, severity = "low_launch", 2
    elif backspin > 3800.0:
        insight = "High backspin — check strike location and dynamic loft."
        rule_id, severity = "high_backspin", 2
    elif abs(side_angle) > 4.0:
        insight = "Large side angle — face/path mismatch; work on start line control."
        rule_id, severity = "large_side_angle", 1
    else:
        insight = "Solid shot — keep repeating that swing."
        rule_id, severity = "good_shot", 0

    return {
        "timestamp": now_iso_z(),
        "speed": speed,
        "launch_angle": launch_angle,
        "side_angle": side_angle,
        "backspin": backspin,
        "sidespin": sidespin,
        "carry": carry,
        "_insight": {"message": insight, "rule_id": rule_id, "severity": severity},
    }

# ----------------------------
# Session State Initialization
# ----------------------------
if "view" not in st.session_state:
    st.session_state.view = "home"  # "home" | "session" | "history"

if "session_id" not in st.session_state:
    st.session_state.session_id = None  # Supabase UUID (string)

if "shots" not in st.session_state:
    st.session_state.shots = []  # local cache of current session shots

if "history_selected_session_id" not in st.session_state:
    st.session_state.history_selected_session_id = None  # chosen session in history view

# ----------------------------
# Resume helpers
# ----------------------------
def find_latest_open_session_id() -> Optional[str]:
    sessions = list_sessions(limit=50, user_id=None)
    for s in sessions:
        if s.get("ended_at") is None:
            return str(s.get("session_id"))
    return None

def load_session_into_ui(session_id: str) -> None:
    rows = get_session_shots(session_id)
    shots_ui: List[Dict[str, Any]] = []
    for r in rows:
        shots_ui.append(
            {
                "timestamp": dt_to_iso_z(r.get("ts")),
                "speed": safe_float(r.get("speed")),
                "launch_angle": safe_float(r.get("launch_angle")),
                "side_angle": safe_float(r.get("side_angle")),
                "backspin": safe_float(r.get("backspin")),
                "sidespin": safe_float(r.get("sidespin")),
                "carry": safe_float(r.get("carry")),
                "_insight": {"message": r.get("insight") or "", "rule_id": None, "severity": None},
            }
        )
    st.session_state.session_id = session_id
    st.session_state.shots = shots_ui
    st.session_state.view = "session"

# ----------------------------
# UI: Home Screen
# ----------------------------
def render_home() -> None:
    st.title("Smart Golf Visor")
    st.caption("Prototype UI (BLE ignored for now)")

    st.markdown("")

    if st.button("Start Session", type="primary", use_container_width=True):
        session_id = create_session(user_id=None)
        st.session_state.session_id = session_id
        st.session_state.shots = []
        st.session_state.view = "session"
        st.rerun()

    st.markdown("")

    # Continue previous (unfinished) session
    open_session_id = find_latest_open_session_id()

    if st.session_state.session_id:
        st.button(
            "Continue Previous Session",
            use_container_width=True,
            disabled=True,
            help="You already have a session loaded.",
        )
    else:
        if open_session_id is None:
            st.button(
                "Continue Previous Session",
                use_container_width=True,
                disabled=True,
                help="No unfinished session found.",
            )
        else:
            if st.button("Continue Previous Session", use_container_width=True):
                load_session_into_ui(open_session_id)
                st.rerun()

    st.markdown("")

    # Session History
    if st.button("Session History", use_container_width=True):
        st.session_state.history_selected_session_id = None
        st.session_state.view = "history"
        st.rerun()

# ----------------------------
# UI: Current Session Screen
# ----------------------------
def render_session() -> None:
    st.title("Current Session")
    st.caption(f"Session ID: {st.session_state.session_id}")

    st.divider()

    if len(st.session_state.shots) == 0:
        st.info("Waiting for shot data… (use Generate Test Shot for now)")

        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("Generate Test Shot", use_container_width=True):
                shot = generate_mock_shot()

                shot_id = insert_shot(
                    st.session_state.session_id,
                    {
                        "speed": shot["speed"],
                        "launch_angle": shot["launch_angle"],
                        "side_angle": shot["side_angle"],
                        "backspin": shot["backspin"],
                        "sidespin": shot["sidespin"],
                        "carry": shot["carry"],
                        "timestamp": shot["timestamp"],
                    },
                )

                upsert_insight_for_shot(
                    shot_id=shot_id,
                    message=shot["_insight"]["message"],
                    rule_id=shot["_insight"]["rule_id"],
                    severity=shot["_insight"]["severity"],
                )

                st.session_state.shots.append(shot)
                st.rerun()

        with col_b:
            if st.button("End Session", use_container_width=True):
                if st.session_state.session_id:
                    end_session(st.session_state.session_id)
                st.session_state.session_id = None
                st.session_state.view = "home"
                st.rerun()
        return

    shot = st.session_state.shots[-1]

    c1, c2, c3 = st.columns(3)
    c4, c5, c6 = st.columns(3)

    c1.metric("Speed", fmt_speed(shot.get("speed")))
    c2.metric("Carry", fmt_carry(shot.get("carry")))
    c3.metric("Launch", fmt_launch(shot.get("launch_angle")))
    c4.metric("Side Angle", fmt_side(shot.get("side_angle")))
    c5.metric("Backspin", fmt_rpm(shot.get("backspin")))
    c6.metric("Sidespin", fmt_rpm(shot.get("sidespin")))

    st.markdown(f"**Last update:** {shot.get('timestamp', '—')}")
    if shot.get("_insight", {}).get("message"):
        st.success(f"**Insight:** {shot['_insight']['message']}")

    st.divider()

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("Generate Test Shot", use_container_width=True):
            shot = generate_mock_shot()

            shot_id = insert_shot(
                st.session_state.session_id,
                {
                    "speed": shot["speed"],
                    "launch_angle": shot["launch_angle"],
                    "side_angle": shot["side_angle"],
                    "backspin": shot["backspin"],
                    "sidespin": shot["sidespin"],
                    "carry": shot["carry"],
                    "timestamp": shot["timestamp"],
                },
            )

            upsert_insight_for_shot(
                shot_id=shot_id,
                message=shot["_insight"]["message"],
                rule_id=shot["_insight"]["rule_id"],
                severity=shot["_insight"]["severity"],
            )

            st.session_state.shots.append(shot)
            st.rerun()

    with col2:
        if st.button("Reload Session", use_container_width=True):
            load_session_into_ui(st.session_state.session_id)
            st.rerun()

    with col3:
        if st.button("End Session", use_container_width=True):
            if st.session_state.session_id:
                end_session(st.session_state.session_id)
            st.session_state.session_id = None
            st.session_state.view = "home"
            st.rerun()

    with st.expander("Recent Shots"):
        st.dataframe(
            [
                {
                    "timestamp": s.get("timestamp"),
                    "speed_mph": round(float(s["speed"]), 1),
                    "carry_yd": int(round(float(s["carry"]))),
                    "launch_deg": round(float(s["launch_angle"]), 1),
                    "side_deg": round(float(s["side_angle"]), 1),
                    "backspin_rpm": int(round(float(s["backspin"]))),
                    "sidespin_rpm": int(round(float(s["sidespin"]))),
                    "insight": s.get("_insight", {}).get("message", ""),
                }
                for s in reversed(st.session_state.shots[-10:])
            ],
            use_container_width=True,
            hide_index=True,
        )

# ----------------------------
# UI: History Screen
# ----------------------------
def render_history() -> None:
    st.title("Session History")

    col_top_a, col_top_b = st.columns([1, 1])
    with col_top_a:
        if st.button("← Back to Home", use_container_width=True):
            st.session_state.view = "home"
            st.rerun()
    with col_top_b:
        if st.session_state.session_id:
            if st.button("Go to Current Session", use_container_width=True):
                st.session_state.view = "session"
                st.rerun()
        else:
            st.button("Go to Current Session", use_container_width=True, disabled=True)

    st.divider()

    sessions = list_sessions(limit=100, user_id=None)
    if not sessions:
        st.info("No sessions found yet.")
        return

    # Build selection options
    options: List[str] = []
    label_to_id: Dict[str, str] = {}

    for s in sessions:
        sid = str(s.get("session_id"))
        started = dt_to_iso_z(s.get("started_at"))
        ended = s.get("ended_at")
        status = "ACTIVE" if ended is None else "ENDED"
        nshots = s.get("num_shots", 0)
        label = f"{started} • {status} • {nshots} shots • {sid[:8]}"
        options.append(label)
        label_to_id[label] = sid

    default_index = 0
    if st.session_state.history_selected_session_id:
        # Try to keep selection stable
        for i, lab in enumerate(options):
            if label_to_id[lab] == st.session_state.history_selected_session_id:
                default_index = i
                break

    selected_label = st.selectbox(
        "Select a session",
        options,
        index=default_index if options else None,
    )
    selected_session_id = label_to_id[selected_label]
    st.session_state.history_selected_session_id = selected_session_id

    st.markdown("")
    if st.button("Load This Session", type="primary", use_container_width=True):
        # Loads session + shots into the UI, then navigates to session view
        load_session_into_ui(selected_session_id)
        st.rerun()

    st.divider()

    # Show shot list for the selected session
    rows = get_session_shots(selected_session_id)
    if not rows:
        st.info("No shots found for this session.")
        return

    st.subheader("Shots")
    st.dataframe(
        [
            {
                "timestamp": dt_to_iso_z(r.get("ts")),
                "speed_mph": None if r.get("speed") is None else round(float(r.get("speed")), 1),
                "carry_yd": None if r.get("carry") is None else int(round(float(r.get("carry")))),
                "launch_deg": None if r.get("launch_angle") is None else round(float(r.get("launch_angle")), 1),
                "side_deg": None if r.get("side_angle") is None else round(float(r.get("side_angle")), 1),
                "backspin_rpm": None if r.get("backspin") is None else int(round(float(r.get("backspin")))),
                "sidespin_rpm": None if r.get("sidespin") is None else int(round(float(r.get("sidespin")))),
                "insight": r.get("insight") or "",
            }
            for r in rows
        ],
        use_container_width=True,
        hide_index=True,
    )

# ----------------------------
# Router
# ----------------------------
if st.session_state.view == "home":
    render_home()
elif st.session_state.view == "session":
    render_session()
else:
    render_history()