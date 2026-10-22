"""Phase 13, Gate 1/7: AWS client validation, error classification, and
structural safety checks. NEVER constructs `Boto3AwsClient` (which
would require boto3/botocore and, if misused, a real network reach) --
every test here exercises either the pure validation functions or the
error-classification logic directly, consistent with Gate 7's "do not
make any live AWS SDK calls while implementing/testing this phase"."""

import inspect

import pytest

from detectors.clients.aws_client import (
    AwsClientProtocol,
    AwsConfigError,
    AwsForbiddenError,
    AwsNotFoundError,
    AwsObserverScope,
    AwsThrottledError,
    AwsUnavailableError,
    _classify_client_error,
    validate_account_id,
    validate_alarm_name,
    validate_ecs_identifier,
    validate_instance_id,
    validate_region,
)


class _FakeClientError(Exception):
    """A minimal stand-in for botocore.exceptions.ClientError's own
    shape (`.response["Error"]["Code"]`) -- never imports botocore
    itself, so this test module has zero import-time dependency on it
    either."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


# ---------------------------------------------------------------------
# Identifier/account/region validation
# ---------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["12345", "abcdefghijkl", "1234567890123", "", "123456789012 "])
def test_invalid_account_id_is_rejected(bad):
    with pytest.raises(AwsConfigError):
        validate_account_id(bad)


def test_valid_account_id_passes():
    assert validate_account_id("123456789012") == "123456789012"


@pytest.mark.parametrize("bad", ["us-east", "US-EAST-1", "useast1", "", "us-east-1; rm -rf /"])
def test_invalid_region_is_rejected(bad):
    with pytest.raises(AwsConfigError):
        validate_region(bad)


@pytest.mark.parametrize("good", ["us-east-1", "eu-west-2", "ap-southeast-1", "us-gov-west-1"])
def test_valid_region_passes(good):
    assert validate_region(good) == good


@pytest.mark.parametrize("bad", ["i-123", "instance-1", "", "i-gggggggg", "i-0123456789abcdef0; rm -rf /"])
def test_invalid_instance_id_is_rejected(bad):
    with pytest.raises(AwsConfigError):
        validate_instance_id(bad)


def test_valid_instance_id_passes():
    assert validate_instance_id("i-0123456789abcdef0") == "i-0123456789abcdef0"


@pytest.mark.parametrize("bad", ["", "cluster name with spaces", "a" * 300])
def test_invalid_ecs_identifier_is_rejected(bad):
    with pytest.raises(AwsConfigError):
        validate_ecs_identifier(bad, kind="cluster", account_id="123456789012", region="us-east-1")


def test_valid_ecs_identifier_accepts_bare_name_and_same_account_region_arn():
    assert validate_ecs_identifier("my-cluster", kind="cluster", account_id="123456789012", region="us-east-1") == "my-cluster"
    assert validate_ecs_identifier(
        "arn:aws:ecs:us-east-1:123456789012:cluster/my-cluster", kind="cluster", account_id="123456789012", region="us-east-1"
    )


# ---------------------------------------------------------------------
# Correction round (final), Issue 3: ECS ARN account/region must match
# the configured scope -- never accepted from a different account or
# region, even though the ARN is otherwise well-formed.
# ---------------------------------------------------------------------


def test_ecs_identifier_rejects_a_different_account_arn():
    with pytest.raises(AwsConfigError):
        validate_ecs_identifier(
            "arn:aws:ecs:us-east-1:999999999999:cluster/my-cluster", kind="cluster",
            account_id="123456789012", region="us-east-1",
        )


def test_ecs_identifier_rejects_a_different_region_arn():
    with pytest.raises(AwsConfigError):
        validate_ecs_identifier(
            "arn:aws:ecs:eu-west-1:123456789012:cluster/my-cluster", kind="cluster",
            account_id="123456789012", region="us-east-1",
        )


def test_ecs_identifier_accepts_a_matching_service_arn():
    assert validate_ecs_identifier(
        "arn:aws:ecs:us-east-1:123456789012:service/my-cluster/my-service", kind="service",
        account_id="123456789012", region="us-east-1",
    )


def test_scope_construction_rejects_an_ecs_cluster_arn_from_a_different_account():
    with pytest.raises(AwsConfigError):
        AwsObserverScope(
            account_id="123456789012", region="us-east-1",
            enrolled_ecs_clusters=("arn:aws:ecs:us-east-1:999999999999:cluster/prod",),
        )


def test_scope_construction_rejects_an_ecs_cluster_arn_from_a_different_region():
    with pytest.raises(AwsConfigError):
        AwsObserverScope(
            account_id="123456789012", region="us-east-1",
            enrolled_ecs_clusters=("arn:aws:ecs:eu-west-1:123456789012:cluster/prod",),
        )


def test_scope_construction_rejects_an_ecs_service_arn_from_a_different_account():
    with pytest.raises(AwsConfigError):
        AwsObserverScope(
            account_id="123456789012", region="us-east-1",
            enrolled_ecs_services=(("prod", "arn:aws:ecs:us-east-1:999999999999:service/prod/checkout"),),
        )


def test_scope_construction_accepts_matching_ecs_cluster_and_service_arns():
    scope = AwsObserverScope(
        account_id="123456789012", region="us-east-1",
        enrolled_ecs_clusters=("arn:aws:ecs:us-east-1:123456789012:cluster/prod",),
        enrolled_ecs_services=(("prod", "arn:aws:ecs:us-east-1:123456789012:service/prod/checkout"),),
    )
    assert scope.enrolled_ecs_clusters == ("arn:aws:ecs:us-east-1:123456789012:cluster/prod",)


def test_scope_construction_still_accepts_bare_ecs_names_regardless_of_account_region():
    scope = AwsObserverScope(
        account_id="123456789012", region="us-east-1",
        enrolled_ecs_clusters=("prod",),
        enrolled_ecs_services=(("prod", "checkout"),),
    )
    assert scope.enrolled_ecs_clusters == ("prod",)


@pytest.mark.parametrize("bad", ["", "a" * 300])
def test_invalid_alarm_name_is_rejected(bad):
    with pytest.raises(AwsConfigError):
        validate_alarm_name(bad)


def test_valid_alarm_name_passes():
    assert validate_alarm_name("checkout-high-error-rate") == "checkout-high-error-rate"


# ---------------------------------------------------------------------
# Explicit enrollment / scope -- never ambiguous configuration
# ---------------------------------------------------------------------


def test_scope_rejects_malformed_enrolled_instance_id():
    with pytest.raises(AwsConfigError):
        AwsObserverScope(account_id="123456789012", region="us-east-1", enrolled_instance_ids=("not-an-instance-id",))


def test_scope_accepts_a_well_formed_enrollment():
    scope = AwsObserverScope(
        account_id="123456789012", region="us-east-1",
        enrolled_instance_ids=("i-0123456789abcdef0",), enrolled_alarm_names=("my-alarm",),
    )
    assert scope.account_id == "123456789012"
    assert scope.enrolled_instance_ids == ("i-0123456789abcdef0",)


def test_empty_scope_is_valid_but_observes_nothing():
    scope = AwsObserverScope(account_id="123456789012", region="us-east-1")
    assert scope.enrolled_alarm_names == ()
    assert scope.enrolled_instance_ids == ()


# ---------------------------------------------------------------------
# Error classification -- AccessDenied, throttling, not-found, and the
# conservative UNAVAILABLE fallback for anything unrecognized
# ---------------------------------------------------------------------


@pytest.mark.parametrize("code", ["AccessDenied", "AccessDeniedException", "UnauthorizedOperation", "AuthFailure"])
def test_forbidden_codes_classify_as_forbidden(code):
    assert isinstance(_classify_client_error(_FakeClientError(code)), AwsForbiddenError)


@pytest.mark.parametrize(
    "code", ["Throttling", "ThrottlingException", "RequestLimitExceeded", "TooManyRequestsException", "SlowDown"]
)
def test_throttling_codes_classify_as_throttled(code):
    assert isinstance(_classify_client_error(_FakeClientError(code)), AwsThrottledError)


@pytest.mark.parametrize("code", ["ResourceNotFoundException", "InvalidInstanceID.NotFound", "ClusterNotFoundException"])
def test_not_found_codes_classify_as_not_found(code):
    assert isinstance(_classify_client_error(_FakeClientError(code)), AwsNotFoundError)


def test_an_unrecognized_error_code_is_conservatively_unavailable_never_healthy():
    assert isinstance(_classify_client_error(_FakeClientError("SomeBrandNewErrorCodeAWSInventsLater")), AwsUnavailableError)


def test_an_exception_with_no_response_attribute_is_conservatively_unavailable():
    assert isinstance(_classify_client_error(RuntimeError("no .response attribute at all")), AwsUnavailableError)


# ---------------------------------------------------------------------
# Gate 1 structural guarantees: exactly the 8 read-only methods, no
# mutating AWS operation reachable from anywhere in this module, no
# credential value ever in a hardcoded string.
# ---------------------------------------------------------------------


def test_protocol_exposes_exactly_the_8_read_only_methods():
    methods = {
        name for name, member in inspect.getmembers(AwsClientProtocol) if inspect.isfunction(member) and not name.startswith("_")
    }
    assert methods == {
        "verify_identity", "describe_alarms", "get_metric_data", "lookup_events",
        "describe_instances", "describe_instance_status", "list_services", "describe_services",
    }


def test_no_mutating_aws_operation_name_appears_anywhere_in_this_module():
    import pathlib

    text = pathlib.Path(__file__).resolve().parents[1].joinpath("clients", "aws_client.py").read_text()
    forbidden_operations = (
        "start_instances", "stop_instances", "reboot_instances", "terminate_instances",
        "update_service", "run_task", "create_service", "delete_service",
        "put_metric_alarm", "delete_alarms", "create_trail", "delete_trail",
        "put_log_events", "create_log_group",
    )
    for op in forbidden_operations:
        assert op not in text, f"unexpected mutating AWS operation name {op!r} found in aws_client.py"


def test_no_hardcoded_credential_shaped_string_in_aws_client_module():
    import pathlib

    text = pathlib.Path(__file__).resolve().parents[1].joinpath("clients", "aws_client.py").read_text()
    for forbidden in ("aws_access_key_id=", "aws_secret_access_key=", "aws_session_token="):
        assert forbidden not in text
