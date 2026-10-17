from pydantic import BaseModel, ConfigDict


class FaultStatusResponse(BaseModel):
    """GET /internal/v1/faults/authorization and the ENABLE endpoint's
    own response -- the current state, never a secret, never arbitrary
    free text."""

    model_config = ConfigDict(extra="forbid")

    active: bool


class FaultClearResponse(BaseModel):
    """POST /internal/v1/faults/authorization/clear's response.
    `changed` distinguishes "this call actually transitioned
    active -> inactive" from "the fault was already inactive" --
    idempotent either way (both return active=False), but tool-gateway
    can use `changed` for its own bounded diagnostics."""

    model_config = ConfigDict(extra="forbid")

    active: bool
    changed: bool
