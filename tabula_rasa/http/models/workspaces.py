from datetime import datetime
from typing import Literal

from pydantic import Field, SecretStr

from .common import DTO

Role = Literal['owner', 'admin', 'editor', 'accountant', 'read_only']


class BootstrapRequest(DTO):
    request_id: str = Field(min_length=16, max_length=128)
    workspace_name: str = Field(min_length=1, max_length=160)
    business_name: str = Field(min_length=1, max_length=160)


class BootstrapResult(DTO):
    state: Literal['not_started', 'ready']
    organization_id: str | None = None
    entity_id: str | None = None


class Member(DTO):
    user_id: str
    display_name: str
    role: Role
    state: Literal['active', 'inactive']
    authorization_version: int


class MemberList(DTO):
    items: list[Member]


class MemberChange(DTO):
    role: Role
    active: bool
    authorization_version: int = Field(ge=1)


class OwnershipGrant(DTO):
    authorization_version: int = Field(ge=1)


class InviteRequest(DTO):
    email: str = Field(min_length=3, max_length=320)
    role: Literal['admin', 'editor', 'accountant', 'read_only']


class InviteIssued(DTO):
    id: str
    credential: str = Field(repr=False)


class Invitation(DTO):
    id: str
    recipient_email: str = Field(repr=False)
    role: Role
    state: Literal['pending', 'accepted', 'declined', 'expired', 'revoked']
    expires_at: datetime


class InvitationList(DTO):
    items: list[Invitation]


class InvitationResponse(DTO):
    credential: SecretStr = Field(min_length=32, max_length=256)
    accept: bool


class InvitationOutcome(DTO):
    state: Literal['accepted', 'declined']
