"""Client for tool-gateway's two Phase 8 endpoints (Phase 8
§TOOL-GATEWAY EXECUTION API / §PRECONDITION ENDPOINT):

  GET  /api/v1/remediation-capabilities  -- read-only precondition check
  POST /api/v1/remediation-actions/execute -- execute ONLY the approved,
       allowlisted action tool-gateway independently verifies

Authenticated with TOOL_GATEWAY_EXECUTION_TOKEN for BOTH calls (Phase 8
correction round: the capability/precondition endpoint is not public).
This token alone never authorizes an action -- see tool-gateway's own
docs; it only lets this service ASK. This client never sends a URL,
hostname, shell command, container id, or any execution target of its
own in the execute request body -- only `proposal_id` (Phase 8 §NO
CALLER-SUPPLIED EXECUTION TARGET); the allowlisted action/target
always comes from control-plane's own approved proposal record, which
tool-gateway independently re-fetches itself.
"""

import logging

import httpx
from pydantic import ValidationError

from agent_runtime_service.authz import current_actor, sign_derivative_assertion
from agent_runtime_service.config import ServiceAssertionSettings
from agent_runtime_service.domain.remediation import (
    KubernetesRemediationCapability,
    RemediationCapability,
    RemediationExecutionResult,
)

logger = logging.getLogger("agent_runtime_service.tool_gateway")


class ToolGatewayUnavailableError(Exception):
    """tool-gateway (or a dependency it needs to answer) could not be
    reached at all -- genuinely transient, left UNCAUGHT by the graph
    node that calls this client (same TRANSIENT/RETRYABLE convention
    as ControlPlaneUnavailableError/InvestigatorUnavailableError,
    Phase 7 correction round finding #3)."""


class ToolGatewayOutputError(Exception):
    """tool-gateway responded, but not with a 2xx this client
    understands, or with a 2xx body that did not match the expected
    shape -- never trusted into durable graph state regardless (same
    discipline as ControlPlaneOutputError/InvestigatorOutputError)."""


class ToolGatewayAmbiguousExecutionError(Exception):
    """Phase 8 correction round (finding #1): the execute() call's own
    response was ambiguous (a non-JSON body, a malformed 200, an HTTP
    502, or any other shape ToolGatewayOutputError already covers) AND,
    on independent reconciliation against control-plane's own durable
    proposal record (graph/nodes.py::execute_remediation), the proposal
    was found still genuinely in flight (status 'approved' or
    'executing') -- truly unknown whether the real action has finished
    yet. Deliberately TRANSIENT/RETRYABLE, never terminal: left
    UNCAUGHT by the node that raises it (same convention as
    ToolGatewayUnavailableError) so the checkpoint is never committed
    and the thread remains resumable at the SAME node; a retried
    resume safely re-attempts the SAME idempotent execute() call."""


class ToolGatewayRefusedError(Exception):
    """tool-gateway responded with a definitive 409/404/400 -- a
    genuine business-level refusal (not approved yet, rejected,
    unknown proposal, wrong action/target, already-failed with no
    retry policy, or a malformed request), never a transient outage.
    Carries the refusal's own bounded detail text and status code."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"tool-gateway refused (http {status_code}): {detail}")
        self.status_code = status_code
        self.detail = detail


class ToolGatewayClient:
    def __init__(
        self,
        base_url: str,
        execution_token: str,
        connect_timeout: float,
        request_timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,
        service_assertion_settings: ServiceAssertionSettings | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._execution_token = execution_token
        self._timeout = httpx.Timeout(request_timeout, connect=connect_timeout)
        self._transport = transport
        # Phase 14 FINAL MACHINE-IDENTITY TENANT-BOUNDARY FIX, Issue B:
        # when a verified actor is bound for the current request (the
        # resume_agent_run flow that drives execute_remediation always
        # has one bound once organization-context enforcement is on --
        # see api/agent_runs.py), execute() below ALSO relays a
        # derived assertion naming that exact actor, in its own
        # dedicated header -- never the body (Phase 8 §NO
        # CALLER-SUPPLIED EXECUTION TARGET's own "a bare proposal id,
        # nothing else" contract is unchanged). tool-gateway forwards
        # this header, UNVERIFIED BY ITSELF (it holds no copy of the
        # shared signing secret), straight through to its own
        # GetProposal/StartExecution/RecordExecutionResult calls --
        # control-plane is the only party that ever cryptographically
        # verifies it.
        self._service_assertion_settings = service_assertion_settings

    def _headers(self) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self._execution_token}"}
        actor = current_actor()
        if actor is not None and self._service_assertion_settings is not None:
            headers["X-Service-Assertion"] = sign_derivative_assertion(
                actor, self._service_assertion_settings, audience=self._service_assertion_settings.control_plane_audience
            )
        return headers

    async def get_capability(self) -> RemediationCapability:
        url = f"{self._base_url}/api/v1/remediation-capabilities"
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                resp = await client.get(url, headers=self._headers())
        except httpx.HTTPError as exc:
            raise ToolGatewayUnavailableError(f"could not reach tool-gateway at {url}: {exc}") from exc

        if resp.status_code != 200:
            raise ToolGatewayUnavailableError(f"tool-gateway returned HTTP {resp.status_code} for {url}")

        try:
            body = resp.json()
        except ValueError as exc:
            raise ToolGatewayOutputError("tool-gateway returned a non-JSON response") from exc

        try:
            return RemediationCapability.model_validate(body)
        except ValidationError as exc:
            logger.warning("tool-gateway capability response failed shape validation (%d error(s))", exc.error_count())
            raise ToolGatewayOutputError(
                "tool-gateway capability response did not match the expected response contract"
            ) from exc

    async def get_kubernetes_capability(self) -> KubernetesRemediationCapability:
        """Phase 12B-D: GET /api/v1/remediation-capabilities/kubernetes
        -- the Kubernetes analogue of get_capability() above. A
        SEPARATE route (never overloading the payment capability
        contract); same auth, same error-handling discipline."""
        url = f"{self._base_url}/api/v1/remediation-capabilities/kubernetes"
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                resp = await client.get(url, headers=self._headers())
        except httpx.HTTPError as exc:
            raise ToolGatewayUnavailableError(f"could not reach tool-gateway at {url}: {exc}") from exc

        if resp.status_code != 200:
            raise ToolGatewayUnavailableError(f"tool-gateway returned HTTP {resp.status_code} for {url}")

        try:
            body = resp.json()
        except ValueError as exc:
            raise ToolGatewayOutputError("tool-gateway returned a non-JSON response") from exc

        try:
            return KubernetesRemediationCapability.model_validate(body)
        except ValidationError as exc:
            logger.warning(
                "tool-gateway kubernetes capability response failed shape validation (%d error(s))", exc.error_count()
            )
            raise ToolGatewayOutputError(
                "tool-gateway kubernetes capability response did not match the expected response contract"
            ) from exc

    async def execute(self, proposal_id: str) -> RemediationExecutionResult:
        url = f"{self._base_url}/api/v1/remediation-actions/execute"
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                resp = await client.post(url, headers=self._headers(), json={"proposal_id": proposal_id})
        except httpx.HTTPError as exc:
            raise ToolGatewayUnavailableError(f"could not reach tool-gateway at {url}: {exc}") from exc

        if resp.status_code == 503:
            # tool-gateway's own explicit "a downstream dependency is
            # temporarily unavailable; retry" signal -- transient.
            raise ToolGatewayUnavailableError(f"tool-gateway reported a transient dependency outage for {url}")

        try:
            body = resp.json()
        except ValueError as exc:
            raise ToolGatewayOutputError("tool-gateway returned a non-JSON response") from exc

        if resp.status_code in (400, 404, 409):
            detail = body.get("detail") if isinstance(body, dict) else None
            raise ToolGatewayRefusedError(resp.status_code, str(detail) if detail else "refused")

        if resp.status_code != 200:
            raise ToolGatewayOutputError(f"tool-gateway returned HTTP {resp.status_code} for {url}")

        try:
            return RemediationExecutionResult.model_validate(body)
        except ValidationError as exc:
            logger.warning("tool-gateway execute response failed shape validation (%d error(s))", exc.error_count())
            raise ToolGatewayOutputError(
                "tool-gateway execute response did not match the expected response contract"
            ) from exc
