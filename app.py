import random
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import streamlit as st

from db import create_session, end_session, insert_shot, upsert_insight_for_shot

st.set_page_config(page_title="Smart Golf Visor", layout="centered")

# ----------------------------
# Helpers (formatting)
# ----------------------------
def fmt_speed(mph: Optional[float]) -> str:
    return "—" if mph is None else f"{mph:.1f} mph"

def fmt_carry(yards: Optional[float]) -> str:
    # carry: no decimal precision (per your earlier preference)
    return "—" if yards is None else f"{int(round(yards))} yd"

def fmt_launch(deg: Optional[float]) -> str:
    # launch angle: 1 decimal
    return "—" if deg is None else f"{deg:.1f}°"

def fmt_side(deg: Optional[float]) -> str:
    return "—" if deg is None else f"{deg:.1f}°"

def fmt_rpm(rpm: Optional[float]) -> str:
    return "—" if rpm is None else f"{int(round(rpm))} rpm"

def now_iso_z() -> str:
    # e.g. "2025-09-03T14:30:45.123Z"
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def generate_mock_shot() -> Dict[str, Any]:
    """
    Generates a mock shot that matches the new schema:
      speed, launch_angle, side_angle, backspin, sidespin, carry, timestamp
    """
    speed = random.uniform(90.0, 165.0)          # mph
    launch_angle = random.uniform(8.0, 20.0)     # degrees
    side_angle = random.uniform(-6.0, 6.0)       # degrees (negative = left, positive = right, example)
    backspin = random.uniform(1800.0, 4200.0)    # rpm
    sidespin = random.uniform(-900.0, 900.0)     # rpm (sign indicates direction)
    carry = random.uniform(140.0, 290.0)         # yards

    # Simple placeholder insight rule (MVP)
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
        "_insight": {
            "message": insight,
            "rule_id": rule_id,
            "severity": severity,
        },
    }


# ----------------------------
# Session State Initialization
# ----------------------------
if "view" not in st.session_state:
    st.session_state.view = "home"  # "home" | "session"

if "session_id" not in st.session_state:
    st.session_state.session_id = None  # Supabase UUID (string)

if "shots" not in st.session_state:
    st.session_state.shots = []  # list of shot dicts (local cache for UI)


# ----------------------------
# UI: Home Screen
# ----------------------------
def render_home() -> None:
    st.title("Smart Golf Visor")
    st.caption("Prototype UI (BLE ignored for now)")

    st.markdown("")  # spacing

    # Single button as requested
    if st.button("Start Session", type="primary", use_container_width=True):
        # Create a real session row in Supabase
        session_id = create_session(user_id=None)
        st.session_state.session_id = session_id
        st.session_state.shots = []
        st.session_state.view = "session"
        st.rerun()


# ----------------------------
# UI: Current Session Screen
# ----------------------------
def render_session() -> None:
    st.title("Current Session")
    st.caption(f"Session ID: {st.session_state.session_id}")

    st.divider()

    # If no shots yet, show a friendly "waiting" message
    if len(st.session_state.shots) == 0:
        st.info("Waiting for shot data… (use Generate Test Shot for now)")

        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("Generate Test Shot", use_container_width=True):
                shot = generate_mock_shot()

                # Write to Supabase
                shot_id = insert_shot(st.session_state.session_id, {
                    "speed": shot["speed"],
                    "launch_angle": shot["launch_angle"],
                    "side_angle": shot["side_angle"],
                    "backspin": shot["backspin"],
                    "sidespin": shot["sidespin"],
                    "carry": shot["carry"],
                    "timestamp": shot["timestamp"],
                })

                upsert_insight_for_shot(
                    shot_id=shot_id,
                    message=shot["_insight"]["message"],
                    rule_id=shot["_insight"]["rule_id"],
                    severity=shot["_insight"]["severity"],
                )

                # Cache locally for UI
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

    # Show most recent shot
    shot = st.session_state.shots[-1]

    # Big metric tiles (6 metrics)
    c1, c2, c3 = st.columns(3)
    c4, c5, c6 = st.columns(3)

    c1.metric("Speed", fmt_speed(shot.get("speed")))
    c2.metric("Carry", fmt_carry(shot.get("carry")))
    c3.metric("Launch", fmt_launch(shot.get("launch_angle")))

    c4.metric("Side Angle", fmt_side(shot.get("side_angle")))
    c5.metric("Backspin", fmt_rpm(shot.get("backspin")))
    c6.metric("Sidespin", fmt_rpm(shot.get("sidespin")))

    st.markdown(f"**Last update:** {shot.get('timestamp', '—')}")
    if "_insight" in shot:
        st.success(f"**Insight:** {shot['_insight']['message']}")

    st.divider()

    # Controls
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Generate Test Shot", use_container_width=True):
            shot = generate_mock_shot()

            # Write to Supabase
            shot_id = insert_shot(st.session_state.session_id, {
                "speed": shot["speed"],
                "launch_angle": shot["launch_angle"],
                "side_angle": shot["side_angle"],
                "backspin": shot["backspin"],
                "sidespin": shot["sidespin"],
                "carry": shot["carry"],
                "timestamp": shot["timestamp"],
            })

            upsert_insight_for_shot(
                shot_id=shot_id,
                message=shot["_insight"]["message"],
                rule_id=shot["_insight"]["rule_id"],
                severity=shot["_insight"]["severity"],
            )

            # Cache locally for UI
            st.session_state.shots.append(shot)
            st.rerun()

    with col2:
        if st.button("End Session", use_container_width=True):
            if st.session_state.session_id:
                end_session(st.session_state.session_id)
            st.session_state.session_id = None
            st.session_state.view = "home"
            st.rerun()

    # Optional: show recent shots table
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
# Router
# ----------------------------
if st.session_state.view == "home":
    render_home()
else:
    render_session()