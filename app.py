import random
import struct
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import streamlit as st

from db import (
    create_session,
    end_session,
    get_session_shots,
    insert_shot,
    list_sessions,
    upsert_insight_for_shot,
)
from visor_component import visor_connector

st.set_page_config(page_title="Smart Golf Visor", layout="centered")

VISOR_SERVICE_UUID = "b015fd54-f43f-4593-b843-da355e49b4d1"
VISOR_CHARACTERISTIC_UUID = "e0e85378-6c67-4f54-86cb-9b5c6aef0c4f"
PI_SERVICE_UUID = "b31072c3-27e7-4da5-95f3-6b59b4a38c61"
PI_CHARACTERISTIC_UUID = "7fc6f4b6-f4e6-4c65-8889-69e0b9bf9a17"

ADVICE_RULES: List[Dict[str, Any]] = [
    {
        "code": 0,
        "rule_id": "good_shot",
        "message": "Solid shot — keep repeating that swing.",
        "severity": 0,
    },
    {
        "code": 1,
        "rule_id": "large_side_angle",
        "message": "Large side angle — face/path mismatch; work on start line control.",
        "severity": 1,
    },
    {
        "code": 2,
        "rule_id": "high_backspin",
        "message": "High backspin — check strike location and dynamic loft.",
        "severity": 2,
    },
    {
        "code": 3,
        "rule_id": "low_launch",
        "message": "Low launch — consider tee height or adding loft.",
        "severity": 2,
    },
    {
        "code": 4,
        "rule_id": "coach_advice",
        "message": "Custom coaching advice received.",
        "severity": 1,
    },
]
ADVICE_BY_RULE_ID = {rule["rule_id"]: rule for rule in ADVICE_RULES}


# ----------------------------
# Helpers (formatting)
# ----------------------------
def fmt_speed(mph: Optional[float]) -> str:
    return "—" if mph is None else f"{mph:.1f} mph"


def fmt_carry(yards: Optional[float]) -> str:
    return "—" if yards is None else f"{int(round(yards))} yd"


def fmt_launch(deg: Optional[float]) -> str:
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


def make_insight(rule_id: str, message_override: Optional[str] = None) -> Dict[str, Any]:
    rule = ADVICE_BY_RULE_ID[rule_id]
    return {
        "code": rule["code"],
        "message": message_override or rule["message"],
        "rule_id": rule["rule_id"],
        "severity": rule["severity"],
    }


def init_visor_state() -> None:
    defaults = {
        "visor_status": "Not connected",
        "visor_device_name": None,
        "visor_last_event": "No visor connected yet.",
        "visor_connected": False,
        "visor_error": None,
        "visor_last_event_id": None,
        "visor_last_send_status": "No shot sent yet.",
        "visor_pending_write_token": None,
        "visor_pending_payload": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def init_pi_state() -> None:
    defaults = {
        "pi_status": "Not connected",
        "pi_device_name": None,
        "pi_last_event": "No Pi connected yet.",
        "pi_connected": False,
        "pi_error": None,
        "pi_last_event_id": None,
        "pi_last_shot_timestamp": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def build_shot_insight(
    launch_angle: Optional[float],
    side_angle: Optional[float],
    backspin: Optional[float],
    coach_advice: Optional[Any] = None,
) -> Dict[str, Any]:
    advice_text = None if coach_advice in (None, "", 0) else str(coach_advice)
    if advice_text:
        return make_insight("coach_advice", message_override=advice_text)
    if launch_angle is not None and launch_angle < 10.0:
        return make_insight("low_launch")
    if backspin is not None and backspin > 3800.0:
        return make_insight("high_backspin")
    if side_angle is not None and abs(side_angle) > 4.0:
        return make_insight("large_side_angle")
    return make_insight("good_shot")


def build_pi_shot(raw_shot: Dict[str, Any]) -> Dict[str, Any]:
    launch_angle = safe_float(raw_shot.get("la"))
    side_angle = safe_float(raw_shot.get("sa"))
    backspin = safe_float(raw_shot.get("bs"))
    return {
        "timestamp": now_iso_z(),
        "speed": safe_float(raw_shot.get("s")),
        "launch_angle": launch_angle,
        "side_angle": side_angle,
        "backspin": backspin,
        "sidespin": safe_float(raw_shot.get("ss")),
        "carry": safe_float(raw_shot.get("d")),
        "_insight": build_shot_insight(launch_angle, side_angle, backspin, raw_shot.get("ca")),
    }


def ensure_active_session() -> None:
    if st.session_state.session_id:
        return
    st.session_state.session_id = create_session(user_id=None)
    st.session_state.shots = []
    st.session_state.view = "session"


def persist_shot_to_current_session(shot: Dict[str, Any]) -> None:
    ensure_active_session()
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


def apply_visor_event(event: Dict[str, Any]) -> None:
    status = str(event.get("status") or "unknown")
    event_id = event.get("eventId")
    connected = bool(event.get("connected"))
    if event_id and event_id == st.session_state.visor_last_event_id:
        return

    st.session_state.visor_last_event_id = event_id
    st.session_state.visor_device_name = event.get("deviceName") or None
    st.session_state.visor_error = event.get("error") or None
    st.session_state.visor_last_event = event.get("lastEvent") or "Visor status updated."

    if status == "connected":
        st.session_state.visor_connected = True
        st.session_state.visor_status = "Connected"
    elif status == "connecting":
        st.session_state.visor_connected = False
        st.session_state.visor_status = "Connecting"
    elif status == "unsupported":
        st.session_state.visor_connected = False
        st.session_state.visor_status = "Web Bluetooth unavailable"
    elif status == "error":
        st.session_state.visor_connected = connected
        st.session_state.visor_status = "Connection error"
        st.session_state.visor_last_send_status = event.get("error") or "Visor communication error."
    elif status == "sent":
        st.session_state.visor_connected = True
        st.session_state.visor_status = "Connected"
        st.session_state.visor_last_send_status = event.get("lastEvent") or "Shot sent to visor."
        st.session_state.visor_pending_write_token = None
        st.session_state.visor_pending_payload = None
    else:
        st.session_state.visor_connected = False
        st.session_state.visor_status = "Disconnected"


def apply_pi_event(event: Dict[str, Any]) -> None:
    status = str(event.get("status") or "unknown")
    event_id = event.get("eventId")
    connected = bool(event.get("connected"))
    if event_id and event_id == st.session_state.pi_last_event_id:
        return

    st.session_state.pi_last_event_id = event_id
    st.session_state.pi_device_name = event.get("deviceName") or None
    st.session_state.pi_error = event.get("error") or None
    st.session_state.pi_last_event = event.get("lastEvent") or "Pi status updated."

    if status == "connected":
        st.session_state.pi_connected = True
        st.session_state.pi_status = "Connected"
        return
    if status == "connecting":
        st.session_state.pi_connected = False
        st.session_state.pi_status = "Connecting"
        return
    if status == "unsupported":
        st.session_state.pi_connected = False
        st.session_state.pi_status = "Web Bluetooth unavailable"
        return
    if status == "error":
        st.session_state.pi_connected = connected
        st.session_state.pi_status = "Connection error"
        return
    if status == "notification":
        st.session_state.pi_connected = True
        st.session_state.pi_status = "Connected"
        shot_data = event.get("shotData")
        if isinstance(shot_data, dict):
            shot = build_pi_shot(shot_data)
            persist_shot_to_current_session(shot)
            st.session_state.pi_last_shot_timestamp = shot["timestamp"]
            if st.session_state.visor_connected:
                queue_shot_for_visor(shot)
            else:
                st.session_state.visor_last_send_status = "Pi shot saved, but visor is not connected."
            st.rerun()
        return

    st.session_state.pi_connected = False
    st.session_state.pi_status = "Disconnected"


def encode_shot_for_visor(shot: Dict[str, Any]) -> List[int]:
    payload = struct.pack(
        "<HhhHHhB",
        int(round(float(shot["speed"]) * 10.0)),
        int(round(float(shot["launch_angle"]) * 10.0)),
        int(round(float(shot["side_angle"]) * 10.0)),
        int(round(float(shot["carry"]))),
        int(round(float(shot["backspin"]))),
        int(round(float(shot["sidespin"]))),
        int(shot.get("_insight", {}).get("code", ADVICE_BY_RULE_ID["good_shot"]["code"])),
    )
    return list(payload)


def queue_shot_for_visor(shot: Dict[str, Any]) -> None:
    st.session_state.visor_pending_payload = encode_shot_for_visor(shot)
    st.session_state.visor_pending_write_token = now_iso_z()
    advice_code = shot.get("_insight", {}).get("code", ADVICE_BY_RULE_ID["good_shot"]["code"])
    st.session_state.visor_last_send_status = f"Queued latest shot for visor delivery with advice code {advice_code}."


def mount_visor_connector() -> None:
    visor_event = visor_connector(
        service_uuid=VISOR_SERVICE_UUID,
        characteristic_uuid=VISOR_CHARACTERISTIC_UUID,
        button_label="Connect Visor",
        expected_device_name="SmartGolfVisor",
        pending_write_token=st.session_state.visor_pending_write_token,
        shot_payload=st.session_state.visor_pending_payload,
        key="visor-connector",
    )
    if visor_event:
        apply_visor_event(visor_event)


def render_visor_status(compact: bool = False) -> None:
    st.subheader("Visor Connection")
    if not compact:
        st.caption("Use a Chromium-based browser on HTTPS or localhost to pair with the ESP32 visor.")

    if st.session_state.visor_connected:
        device_label = st.session_state.visor_device_name or "Unknown visor"
        st.success(f"Connected to {device_label}.")
    elif st.session_state.visor_status == "Connection error":
        st.error(st.session_state.visor_error or "Unable to connect to the visor.")
    elif st.session_state.visor_status == "Web Bluetooth unavailable":
        st.warning("Web Bluetooth is not available in this browser.")
    elif st.session_state.visor_status == "Connecting":
        st.info("Connecting to visor...")
    else:
        st.info("Visor is not connected.")

    status_rows = [
        {
            "Status": st.session_state.visor_status,
            "Device": st.session_state.visor_device_name or "—",
            "Last Event": st.session_state.visor_last_event,
            "Last Send": st.session_state.visor_last_send_status,
        }
    ]
    st.dataframe(status_rows, use_container_width=True, hide_index=True)

    if st.session_state.visor_connected:
        st.caption("The BLE link is active. New test shots and live Pi shots will be sent to the visor automatically.")
    else:
        st.caption("Pair the visor here first. Generated test shots and Pi shots only send while the visor is connected.")


def mount_pi_connector() -> None:
    pi_event = visor_connector(
        service_uuid=PI_SERVICE_UUID,
        characteristic_uuid=PI_CHARACTERISTIC_UUID,
        button_label="Connect Pi",
        expected_device_name="PiTrac",
        enable_notifications=True,
        key="pi-connector",
    )
    if pi_event:
        apply_pi_event(pi_event)


def render_pi_status(compact: bool = False) -> None:
    st.subheader("Pi Connection")
    if not compact:
        st.caption("Connect to the Raspberry Pi BLE service to receive live shot notifications from PiTrac.")

    if st.session_state.pi_connected:
        device_label = st.session_state.pi_device_name or "Unknown Pi"
        st.success(f"Connected to {device_label}.")
    elif st.session_state.pi_status == "Connection error":
        st.error(st.session_state.pi_error or "Unable to connect to the Raspberry Pi.")
    elif st.session_state.pi_status == "Web Bluetooth unavailable":
        st.warning("Web Bluetooth is not available in this browser.")
    elif st.session_state.pi_status == "Connecting":
        st.info("Connecting to Raspberry Pi...")
    else:
        st.info("Pi is not connected.")

    status_rows = [
        {
            "Status": st.session_state.pi_status,
            "Device": st.session_state.pi_device_name or "—",
            "Last Event": st.session_state.pi_last_event,
            "Last Shot": st.session_state.pi_last_shot_timestamp or "—",
        }
    ]
    st.dataframe(status_rows, use_container_width=True, hide_index=True)

    if st.session_state.pi_connected:
        st.caption("Live Pi notifications are enabled. Incoming shots will be stored and shown in the active session.")
    else:
        st.caption("Connect the Pi here to receive shot notifications from its BLE characteristic.")


def render_connection_hub() -> None:
    st.title("Device Connections")
    st.caption("Connect Smart Visor and PiTrac devices below. Ensure that your browser has permission to connect with nearby devices via BLE.")
    render_visor_status(compact=True)
    mount_visor_connector()
    st.markdown("")
    render_pi_status(compact=True)
    mount_pi_connector()
    st.divider()


# ----------------------------
# Mock shot generator (schema-aligned)
# ----------------------------
def generate_mock_shot() -> Dict[str, Any]:
    speed = random.uniform(90.0, 165.0)
    launch_angle = random.uniform(8.0, 20.0)
    side_angle = random.uniform(-6.0, 6.0)
    backspin = random.uniform(1800.0, 4200.0)
    sidespin = random.uniform(-900.0, 900.0)
    carry = random.uniform(140.0, 290.0)
    insight = build_shot_insight(launch_angle, side_angle, backspin)

    return {
        "timestamp": now_iso_z(),
        "speed": speed,
        "launch_angle": launch_angle,
        "side_angle": side_angle,
        "backspin": backspin,
        "sidespin": sidespin,
        "carry": carry,
        "_insight": insight,
    }


# ----------------------------
# Session State Initialization
# ----------------------------
if "view" not in st.session_state:
    st.session_state.view = "home"

if "session_id" not in st.session_state:
    st.session_state.session_id = None

if "shots" not in st.session_state:
    st.session_state.shots = []

if "history_selected_session_id" not in st.session_state:
    st.session_state.history_selected_session_id = None

init_visor_state()
init_pi_state()


# ----------------------------
# Resume helpers
# ----------------------------
def find_latest_open_session_id() -> Optional[str]:
    sessions = list_sessions(limit=50, user_id=None)
    for session_row in sessions:
        if session_row.get("ended_at") is None:
            return str(session_row.get("session_id"))
    return None


def load_session_into_ui(session_id: str) -> None:
    rows = get_session_shots(session_id)
    shots_ui: List[Dict[str, Any]] = []
    for row in rows:
        shots_ui.append(
            {
                "timestamp": dt_to_iso_z(row.get("ts")),
                "speed": safe_float(row.get("speed")),
                "launch_angle": safe_float(row.get("launch_angle")),
                "side_angle": safe_float(row.get("side_angle")),
                "backspin": safe_float(row.get("backspin")),
                "sidespin": safe_float(row.get("sidespin")),
                "carry": safe_float(row.get("carry")),
                "_insight": {"code": None, "message": row.get("insight") or "", "rule_id": None, "severity": None},
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

    if st.button("Start Session", type="primary", use_container_width=True):
        st.session_state.session_id = create_session(user_id=None)
        st.session_state.shots = []
        st.session_state.view = "session"
        st.rerun()

    st.markdown("")

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
                persist_shot_to_current_session(shot)
                if st.session_state.visor_connected:
                    queue_shot_for_visor(shot)
                else:
                    st.session_state.visor_last_send_status = "Shot saved, but visor is not connected."
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
            persist_shot_to_current_session(shot)
            if st.session_state.visor_connected:
                queue_shot_for_visor(shot)
            else:
                st.session_state.visor_last_send_status = "Shot saved, but visor is not connected."
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
                    "timestamp": shot_row.get("timestamp"),
                    "speed_mph": round(float(shot_row["speed"]), 1),
                    "carry_yd": int(round(float(shot_row["carry"]))),
                    "launch_deg": round(float(shot_row["launch_angle"]), 1),
                    "side_deg": round(float(shot_row["side_angle"]), 1),
                    "backspin_rpm": int(round(float(shot_row["backspin"]))),
                    "sidespin_rpm": int(round(float(shot_row["sidespin"]))),
                    "insight": shot_row.get("_insight", {}).get("message", ""),
                }
                for shot_row in reversed(st.session_state.shots[-10:])
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

    options: List[str] = []
    label_to_id: Dict[str, str] = {}

    for session_row in sessions:
        sid = str(session_row.get("session_id"))
        started = dt_to_iso_z(session_row.get("started_at"))
        ended = session_row.get("ended_at")
        status = "ACTIVE" if ended is None else "ENDED"
        nshots = session_row.get("num_shots", 0)
        label = f"{started} • {status} • {nshots} shots • {sid[:8]}"
        options.append(label)
        label_to_id[label] = sid

    default_index = 0
    if st.session_state.history_selected_session_id:
        for index, label in enumerate(options):
            if label_to_id[label] == st.session_state.history_selected_session_id:
                default_index = index
                break

    selected_label = st.selectbox("Select a session", options, index=default_index if options else None)
    selected_session_id = label_to_id[selected_label]
    st.session_state.history_selected_session_id = selected_session_id

    st.markdown("")
    if st.button("Load This Session", type="primary", use_container_width=True):
        load_session_into_ui(selected_session_id)
        st.rerun()

    st.divider()

    rows = get_session_shots(selected_session_id)
    if not rows:
        st.info("No shots found for this session.")
        return

    st.subheader("Shots")
    st.dataframe(
        [
            {
                "timestamp": dt_to_iso_z(row.get("ts")),
                "speed_mph": None if row.get("speed") is None else round(float(row.get("speed")), 1),
                "carry_yd": None if row.get("carry") is None else int(round(float(row.get("carry")))),
                "launch_deg": None if row.get("launch_angle") is None else round(float(row.get("launch_angle")), 1),
                "side_deg": None if row.get("side_angle") is None else round(float(row.get("side_angle")), 1),
                "backspin_rpm": None if row.get("backspin") is None else int(round(float(row.get("backspin")))),
                "sidespin_rpm": None if row.get("sidespin") is None else int(round(float(row.get("sidespin")))),
                "insight": row.get("insight") or "",
            }
            for row in rows
        ],
        use_container_width=True,
        hide_index=True,
    )


# ----------------------------
# Router
# ----------------------------
render_connection_hub()

if st.session_state.view == "home":
    render_home()
elif st.session_state.view == "session":
    render_session()
else:
    render_history()
