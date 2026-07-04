"""Request and response models for API endpoint validation."""

from typing import List
from typing import Optional

from pydantic import BaseModel
from pydantic import Field


class MachineUpdateRequest(BaseModel):
    """Request body for POST /api/machine/update."""

    machine_name: str = Field(description="Name of the machine sending the update.")
    oops: bool = Field(description="Whether the oops button is pressed.")
    rfid_value: str = Field(
        description="Value of the RFID fob/card currently present, "
        "or empty string if none. ESPHome strips leading zeroes; "
        "the server left-pads to 10 characters."
    )
    uptime: float = Field(description="Uptime of the ESP32 (MCU) in seconds.")
    wifi_signal_db: float = Field(description="WiFi signal strength in dB.")
    wifi_signal_percent: float = Field(description="WiFi signal strength in percent.")
    internal_temperature_c: float = Field(
        description="Internal temperature of the ESP32 in °C."
    )
    amps: float = Field(
        default=0.0,
        description="Amperage from the current clamp ammeter, if present.",
    )
    second_relay_state: Optional[bool] = Field(
        default=None,
        description="Actual current state of the second relay as known to the "
        "MCU; reported for observability only and never used in "
        "authorization decisions. Older firmware omits this field.",
    )


class MachineUpdateResponse(BaseModel):
    """Response body for POST /api/machine/update (200)."""

    relay: bool = Field(description="Desired relay state (true = machine enabled).")
    display: str = Field(description="Text to show on the MCU's LCD display.")
    oops_led: bool = Field(description="Whether the oops LED should be lit.")
    status_led_rgb: List[float] = Field(
        description="RGB values for the status LED as [red, green, blue] (0.0-1.0)."
    )
    status_led_brightness: float = Field(
        description="Brightness of the status LED (0.0-1.0)."
    )
    second_relay: bool = Field(
        default=False,
        description="Desired state of the second relay (V1 hardware GPIO14). "
        "Always emitted; firmware that does not know about this "
        "field ignores it.",
    )


class MachineStatusUser(BaseModel):
    """The user currently logged in to a machine, if any."""

    account_id: str = Field(description="Unique account ID of the user.")
    full_name: str = Field(description="Full name of the user.")


class MachineStatus(BaseModel):
    """Current status of a single machine.

    Shared representation used by ``GET /api/machines`` and the status-change
    webhook (which adds ``event`` and ``timestamp`` fields).
    """

    name: str = Field(description="Unique machine name.")
    display_name: str = Field(
        description="Human-friendly name (alias if configured, else name)."
    )
    status: str = Field(
        description="Derived status: one of 'locked_out', 'oops', 'in_use', "
        "'idle', or 'unknown' (never checked in)."
    )
    relay: bool = Field(description="Whether the primary relay is energized.")
    oops: bool = Field(description="Whether the machine is in Oops state.")
    locked_out: bool = Field(
        description="Whether the machine is locked out for maintenance."
    )
    current_user: Optional[MachineStatusUser] = Field(
        default=None,
        description="The logged-in user, or null if no user is logged in.",
    )
    last_checkin: Optional[float] = Field(
        default=None,
        description="Epoch seconds of the machine's last check-in, or null "
        "if it has never checked in.",
    )
    last_update: Optional[float] = Field(
        default=None,
        description="Epoch seconds of the machine's last meaningful state "
        "change, or null until the first such change. Independent of "
        "last_checkin: a machine that has only sent idle heartbeats has a "
        "last_checkin but a null last_update.",
    )


class MachinesListResponse(BaseModel):
    """Response body for GET /api/machines (200)."""

    machines: List[MachineStatus] = Field(
        description="Status of all configured machines, sorted by name."
    )


class SuccessResponse(BaseModel):
    """Generic success response."""

    success: bool = Field(description="Whether the operation succeeded.")


class ErrorResponse(BaseModel):
    """Generic error response."""

    error: str = Field(description="Error message describing what went wrong.")


class StateSaveTimeoutResponse(BaseModel):
    """503 response body for the oops and locked_out endpoints when
    persisting machine state to disk exceeds ``STATE_SAVE_TIMEOUT_SEC``.

    The in-memory state mutation (and any fire-and-forget Slack
    notification) has already taken effect; only the pickle write
    timed out. The next successful save will catch up.
    """

    error: str = Field(description="Error message; always 'state save timeout'.")
    action_applied: bool = Field(
        description="True; the requested state mutation took effect in "
        "memory even though persistence to disk timed out."
    )


class ReloadUsersResponse(BaseModel):
    """Response body for POST /api/reload-users (200)."""

    removed: int = Field(description="Number of users removed.")
    updated: int = Field(description="Number of users updated.")
    added: int = Field(description="Number of users added.")


class ApiIndexResponse(BaseModel):
    """Response body for GET /api/."""

    message: str = Field(description="Placeholder message.")
