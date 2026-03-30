from pathlib import Path
from typing import Any, Dict, Optional

import streamlit.components.v1 as components

_COMPONENT_PATH = Path(__file__).resolve().parent / "components" / "visor_connector"

_visor_connector_component = components.declare_component(
    "visor_connector",
    path=str(_COMPONENT_PATH),
)


def visor_connector(
    service_uuid: str,
    characteristic_uuid: str,
    button_label: str = "Connect Visor",
    key: str = "visor-connector",
) -> Optional[Dict[str, Any]]:
    return _visor_connector_component(
        serviceUuid=service_uuid,
        characteristicUuid=characteristic_uuid,
        buttonLabel=button_label,
        default=None,
        key=key,
    )
