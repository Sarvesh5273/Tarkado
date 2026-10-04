"""Company-owned accounts and configuration, never provider credentials."""

import uuid

from django.conf import settings
from django.db import models


class Company(models.Model):
    # The first supported installation has one company, not public tenant signup.
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    company_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    deployment_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    name = models.CharField(max_length=128)
    revision = models.PositiveIntegerField(default=1)
    policy = models.JSONField()
    repository_refs = models.JSONField()
    collection_fields = models.JSONField()
    company_api_attested = models.BooleanField(default=True)
    retention_policy = models.CharField(max_length=16, default="manual")

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(id=1), name="company_single_installation")]


class Membership(models.Model):
    ROLES = (("junior", "Junior"), ("developer", "Developer"), ("senior", "Senior"), ("admin", "Administrator"))

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    developer_id = models.CharField(max_length=64, unique=True)
    role = models.CharField(max_length=16, choices=ROLES)
    active = models.BooleanField(default=True)
    participating = models.BooleanField(default=True)
    can_manage_company = models.BooleanField(default=False)
    can_approve_pilots = models.BooleanField(default=False)


class Invitation(models.Model):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    invitation_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    username = models.CharField(max_length=64)
    role = models.CharField(max_length=16, choices=Membership.ROLES)
    participating = models.BooleanField()
    can_manage_company = models.BooleanField()
    can_approve_pilots = models.BooleanField()
    # Only a digest of the random invitation is stored, never the usable value.
    digest = models.CharField(max_length=64, unique=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="company_invitations")
    created_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True)
    revoked_at = models.DateTimeField(null=True)


class CompanyEvent(models.Model):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    revision = models.PositiveIntegerField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    actor_username = models.CharField(max_length=64)
    timestamp = models.DateTimeField()
    action = models.CharField(max_length=32)
    details = models.JSONField()

    class Meta:
        ordering = ("revision",)
        constraints = [models.UniqueConstraint(fields=("company", "revision"), name="company_event_revision")]


class LoginAttempt(models.Model):
    account_ref = models.CharField(max_length=64, db_index=True)
    timestamp = models.DateTimeField()
    result = models.CharField(max_length=16)


class CompanyTask(models.Model):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    task_id = models.CharField(max_length=128)
    session_id = models.CharField(max_length=128)
    repository_ref = models.CharField(max_length=1024)
    source_kind = models.CharField(max_length=16)
    request = models.JSONField()
    policy_snapshot = models.JSONField()
    revision = models.PositiveIntegerField(default=1)
    learning_snapshot = models.JSONField(null=True)
    suggestion_context = models.JSONField(default=dict)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("company", "owner", "session_id", "task_id"), name="company_owned_task_identity")]


class TaskEvent(models.Model):
    task = models.ForeignKey(CompanyTask, on_delete=models.PROTECT, related_name="events")
    sequence = models.PositiveIntegerField()
    kind = models.CharField(max_length=16)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    actor_snapshot = models.JSONField()
    company_revision = models.PositiveIntegerField()
    timestamp = models.DateTimeField()
    payload = models.JSONField()

    class Meta:
        ordering = ("sequence",)
        constraints = [models.UniqueConstraint(fields=("task", "sequence"), name="company_task_event_sequence")]


class MFAState(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    generation = models.PositiveIntegerField(default=0)
    pending_since = models.DateTimeField(null=True)


class SecurityEvent(models.Model):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    timestamp = models.DateTimeField()
    action = models.CharField(max_length=32)
    details = models.JSONField()

    class Meta:
        ordering = ("timestamp", "id")


class RecoveryGrant(models.Model):
    reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="recovery_grants")
    issuer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="issued_recovery_grants")
    kind = models.CharField(max_length=16)
    digest = models.CharField(max_length=64, unique=True)
    password_ref = models.CharField(max_length=64)
    issued_at = models.DateTimeField()
    expires_at = models.DateTimeField(null=True)
    consumed_at = models.DateTimeField(null=True)
    revoked_at = models.DateTimeField(null=True)


class EvidenceReview(models.Model):
    reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    creator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField()
    data = models.JSONField()


class PilotAuthorization(models.Model):
    reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    review = models.ForeignKey(EvidenceReview, on_delete=models.PROTECT)
    approver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    pilot_id = models.CharField(max_length=128)
    data = models.JSONField()
    revoked_at = models.DateTimeField(null=True)
    authorization_revision = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("company", "pilot_id"), name="company_unique_authorized_pilot")]


class AuthorizedPilot(models.Model):
    authorization = models.OneToOneField(PilotAuthorization, on_delete=models.PROTECT)
    journal = models.JSONField()
    activation_actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    activation_reason = models.CharField(max_length=1024)


class AuthorizationEvent(models.Model):
    authorization = models.ForeignKey(PilotAuthorization, on_delete=models.PROTECT, related_name="authority_events")
    sequence = models.PositiveIntegerField()
    action = models.CharField(max_length=16)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    timestamp = models.DateTimeField()
    payload = models.JSONField()

    class Meta:
        ordering = ("sequence",)
        constraints = [models.UniqueConstraint(fields=("authorization", "sequence"), name="company_live_authority_event_sequence")]


class ConnectorCredential(models.Model):
    reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    digest = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=128)
    scope = models.JSONField()
    issued_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True)


class ConnectorTask(models.Model):
    reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    credential = models.ForeignKey(ConnectorCredential, on_delete=models.PROTECT)
    task = models.OneToOneField(CompanyTask, on_delete=models.PROTECT, related_name="connector_link")
    client_task_id = models.UUIDField()
    session_ref = models.CharField(max_length=64)
    closed_at = models.DateTimeField(null=True)
    sequence = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("credential", "client_task_id"), name="connector_task_retry_identity")]


class ConnectorObservation(models.Model):
    task = models.ForeignKey(ConnectorTask, on_delete=models.PROTECT, related_name="observations")
    event_id = models.UUIDField()
    sequence = models.PositiveIntegerField()
    received_at = models.DateTimeField()
    actor_snapshot = models.JSONField()
    payload = models.JSONField()
    missing_before = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("sequence",)
        constraints = [models.UniqueConstraint(fields=("task", "event_id"), name="connector_event_retry_identity"),
                       models.UniqueConstraint(fields=("task", "sequence"), name="connector_event_sequence")]


class LearningPublication(models.Model):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    review = models.ForeignKey(EvidenceReview, on_delete=models.PROTECT, null=True)
    source_kind = models.CharField(max_length=16)
    sequence = models.PositiveIntegerField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField()
    data = models.JSONField()

    class Meta:
        ordering = ("sequence",)
        constraints = [models.UniqueConstraint(fields=("company", "source_kind", "sequence"), name="company_learner_publication_sequence")]


class ScopedSelectionRuntime(models.Model):
    authorization = models.OneToOneField(PilotAuthorization, on_delete=models.PROTECT)
    journal = models.JSONField()


class GatewayCredential(models.Model):
    reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    issuer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    gateway_id = models.CharField(max_length=128)
    digest = models.CharField(max_length=64, unique=True)
    scope = models.JSONField()
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True)


class DeliveryBinding(models.Model):
    reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    connector_task = models.OneToOneField(ConnectorTask, on_delete=models.PROTECT, related_name="delivery")
    runtime = models.ForeignKey(ScopedSelectionRuntime, on_delete=models.PROTECT)
    gateway = models.ForeignKey(GatewayCredential, on_delete=models.PROTECT)
    selection_id = models.CharField(max_length=128)
    digest = models.CharField(max_length=64, unique=True)
    data = models.JSONField()
    journal = models.JSONField(default=list)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("runtime", "selection_id"), name="delivery_one_selection_binding")]


class OperationalControl(models.Model):
    company = models.OneToOneField(Company, on_delete=models.PROTECT)
    journal = models.JSONField(default=list)


class ToolObservation(models.Model):
    binding = models.ForeignKey(DeliveryBinding, on_delete=models.PROTECT, related_name="tool_observations")
    event_id = models.UUIDField()
    sequence = models.PositiveIntegerField()
    received_at = models.DateTimeField()
    actor_snapshot = models.JSONField()
    payload = models.JSONField()
    missing_before = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("sequence",)
        constraints = [models.UniqueConstraint(fields=("binding", "event_id"), name="tool_observation_event_identity"),
                       models.UniqueConstraint(fields=("binding", "sequence"), name="tool_observation_sequence")]
