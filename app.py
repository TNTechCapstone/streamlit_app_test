import time
import uuid
import random
import streamlit as st

st.set_page_config(page_title="Smart Golf Visor", layout="centered")

# ----------------------------
# Helpers
# ----------------------------
def fmt_carry(yards: float) -> str:
    # carry: no decimal precision
    return f"{int(round(yards))} yd"

def fmt_launch(deg: float) -> str:
    # launch angle: 1 decimal
    return f"{deg:.1f}°"

def fmt_ball_speed(mph: float) -> str:
    return f"{mph:.1f} mph"

def fmt_spin(rpm: float) -> str:
    return f"{int(round(rpm))} rpm"

def fmt_smash(sf: float) -> str:
    return f"{sf:.2f}"

def generate_mock_shot() -> dict:
    # You can adjust ranges to match your expected launch monitor behavior
    ball_speed = random.uniform(90, 165)          # mph
    launch = random.uniform(8, 20)                # degrees
    carry = random.uniform(140, 290)              # yards
    spin = random.uniform(1800, 4200)             # rpm
    smash = random.uniform(1.25, 1.52)            # unitless

    # Simple placeholder insight rule
    if launch < 10.0:
        insight = "Low launch — consider tee height or adding loft."
    elif spin > 3800:
        insight = "High spin — check strike location and club fit."
    else:
        insight = "Solid shot — keep repeating that swing."

    return {
        "timestamp": time.strftime("%H:%M:%S"),
        "ball_speed": ball_speed,
        "launch_angle": launch,
        "carry": carry,
        "spin_rate": spin,
        "smash_factor": smash,
        "insight": insight,
    }

# ----------------------------
# Session State Initialization
# ----------------------------
if "view" not in st.session_state:
    st.session_state.view = "home"  # "home" | "session"

if "session_active" not in st.session_state:
    st.session_state.session_active = False

if "session_id" not in st.session_state:
    st.session_state.session_id = None

if "shots" not in st.session_state:
    st.session_state.shots = []  # list of shot dicts

# ----------------------------
# UI: Home Screen
# ----------------------------
def render_home():
    st.title("Smart Golf Visor")
    st.caption("Prototype UI (BLE ignored for now)")

    st.markdown("")  # spacing

    # Single button as requested
    if st.button("Start Session", type="primary", use_container_width=True):
        st.session_state.session_active = True
        st.session_state.session_id = str(uuid.uuid4())[:8]
        st.session_state.shots = []
        st.session_state.view = "session"
        st.rerun()

# ----------------------------
# UI: Current Session Screen
# ----------------------------
def render_session():
    st.title("Current Session")
    st.caption(f"Session ID: {st.session_state.session_id}")

    st.divider()

    # If no shots yet, show a friendly "waiting" message
    if len(st.session_state.shots) == 0:
        st.info("Waiting for shot data… (use Generate Test Shot for now)")

        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("Generate Test Shot", use_container_width=True):
                st.session_state.shots.append(generate_mock_shot())
                st.rerun()
        with col_b:
            if st.button("End Session", use_container_width=True):
                st.session_state.session_active = False
                st.session_state.view = "home"
                st.rerun()
        return

    # Show most recent shot
    shot = st.session_state.shots[-1]

    # Big metric tiles
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Ball Speed", fmt_ball_speed(shot["ball_speed"]))
    c2.metric("Carry", fmt_carry(shot["carry"]))
    c3.metric("Launch", fmt_launch(shot["launch_angle"]))
    c4.metric("Spin", fmt_spin(shot["spin_rate"]))
    c5.metric("Smash", fmt_smash(shot["smash_factor"]))

    st.markdown(f"**Last update:** {shot['timestamp']}")
    st.success(f"**Insight:** {shot['insight']}")

    st.divider()

    # Controls
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Generate Test Shot", use_container_width=True):
            st.session_state.shots.append(generate_mock_shot())
            st.rerun()
    with col2:
        if st.button("End Session", use_container_width=True):
            st.session_state.session_active = False
            st.session_state.view = "home"
            st.rerun()

    # Optional: show recent shots table (comment out if you want super minimal)
    with st.expander("Recent Shots"):
        st.dataframe(
            [
                {
                    "time": s["timestamp"],
                    "ball_speed_mph": round(s["ball_speed"], 1),
                    "carry_yd": int(round(s["carry"])),
                    "launch_deg": round(s["launch_angle"], 1),
                    "spin_rpm": int(round(s["spin_rate"])),
                    "smash": round(s["smash_factor"], 2),
                    "insight": s["insight"],
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
