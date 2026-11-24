from __future__ import annotations

import secrets
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse, Response
from neatsprint_lib.auth import Principal, require_permission
from neatsprint_lib.db import bind_tenant, get_session, get_tenant_session
from neatsprint_lib.errors import ApiError
from neatsprint_lib.events import enqueue
from neatsprint_lib.ids import new_id
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from neatsprint_team.api.schemas import MemberAdd, TeamCreate, TeamUpdate
from neatsprint_team.db.models import Team, TeamMember

router = APIRouter(prefix="/teams", tags=["teams"])
internal_router = APIRouter(prefix="/internal", tags=["internal"])

SessionDep = Annotated[AsyncSession, Depends(get_tenant_session)]
AdminSessionDep = Annotated[AsyncSession, Depends(get_session)]
ViewPrincipal = Annotated[Principal, Depends(require_permission("team:team:view"))]
ManagePrincipal = Annotated[Principal, Depends(require_permission("team:team:manage"))]
MemberPrincipal = Annotated[Principal, Depends(require_permission("team:member:manage"))]


def envelope(request: Request, data: object, **meta: object) -> dict[str, object]:
    return {
        "data": data,
        "meta": {"request_id": getattr(request.state, "request_id", None), **meta},
    }


def team_payload(team: Team) -> dict[str, object]:
    return {
        "id": str(team.id),
        "name": team.name,
        "description": team.description,
        "lead_id": str(team.lead_id) if team.lead_id else None,
        "is_archived": team.is_archived,
    }


async def _team(session: AsyncSession, tenant_id: UUID, team_id: UUID) -> Team:
    team = await session.get(Team, team_id)
    if team is None or team.tenant_id != tenant_id:
        raise ApiError(404, "not_found", "Team not found.")
    return team


async def _can_manage(principal: Principal, team: Team, code: str) -> None:
    if principal.can(code) or team.lead_id == principal.user_id:
        return
    raise ApiError(403, "permission_denied", "You cannot manage this team.")


@router.get("", summary="List teams")
async def list_teams(
    principal: ViewPrincipal, request: Request, session: SessionDep
) -> JSONResponse:
    rows = (
        await session.execute(
            select(Team).where(Team.tenant_id == principal.tenant_id).order_by(Team.name)
        )
    ).scalars()
    return JSONResponse(envelope(request, [team_payload(team) for team in rows]))


@router.post("", status_code=201, summary="Create a team")
async def create_team(
    payload: TeamCreate, principal: ManagePrincipal, request: Request, session: SessionDep
) -> JSONResponse:
    team = Team(
        id=new_id(),
        tenant_id=principal.tenant_id,
        name=payload.name.strip(),
        description=payload.description,
        lead_id=payload.lead_id or principal.user_id,
    )
    session.add(team)
    await session.flush()
    session.add(
        TeamMember(
            tenant_id=principal.tenant_id,
            team_id=team.id,
            user_id=team.lead_id,
            role_in_team="LEAD",
        )
    )
    enqueue(
        session,
        event_type="team.created",
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        payload={"team_id": str(team.id), "name": team.name},
    )
    await session.commit()
    return JSONResponse(envelope(request, team_payload(team)), status_code=201)


@router.get("/{team_id}", summary="Read a team")
async def read_team(
    team_id: UUID, principal: ViewPrincipal, request: Request, session: SessionDep
) -> JSONResponse:
    team = await _team(session, principal.tenant_id, team_id)
    return JSONResponse(envelope(request, team_payload(team)))


@router.patch("/{team_id}", summary="Update a team")
async def update_team(
    team_id: UUID,
    payload: TeamUpdate,
    principal: ManagePrincipal,
    request: Request,
    session: SessionDep,
) -> JSONResponse:
    team = await _team(session, principal.tenant_id, team_id)
    await _can_manage(principal, team, "team:team:manage")
    if payload.name is not None:
        team.name = payload.name.strip()
    if payload.description is not None:
        team.description = payload.description
    if payload.lead_id is not None:
        team.lead_id = payload.lead_id
    if payload.is_archived is not None:
        team.is_archived = payload.is_archived
    await session.commit()
    return JSONResponse(envelope(request, team_payload(team)))


@router.get("/{team_id}/members", summary="List team members")
async def list_members(
    team_id: UUID, principal: ViewPrincipal, request: Request, session: SessionDep
) -> JSONResponse:
    await _team(session, principal.tenant_id, team_id)
    rows = (
        await session.execute(
            select(TeamMember).where(
                TeamMember.team_id == team_id, TeamMember.tenant_id == principal.tenant_id
            )
        )
    ).scalars()
    return JSONResponse(
        envelope(
            request,
            [
                {
                    "user_id": str(member.user_id),
                    "role_in_team": member.role_in_team,
                    "joined_at": member.joined_at.isoformat(),
                }
                for member in rows
            ],
        )
    )


@router.post("/{team_id}/members", status_code=201, summary="Add a team member")
async def add_member(
    team_id: UUID,
    payload: MemberAdd,
    principal: MemberPrincipal,
    request: Request,
    session: SessionDep,
) -> JSONResponse:
    team = await _team(session, principal.tenant_id, team_id)
    await _can_manage(principal, team, "team:member:manage")
    existing = await session.get(
        TeamMember, {"team_id": team_id, "user_id": payload.user_id}
    )
    if existing is None:
        session.add(
            TeamMember(
                tenant_id=principal.tenant_id,
                team_id=team_id,
                user_id=payload.user_id,
                role_in_team=payload.role_in_team,
            )
        )
        enqueue(
            session,
            event_type="team.member_added",
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
            payload={"team_id": str(team_id), "user_id": str(payload.user_id)},
        )
        await session.commit()
    return JSONResponse(
        envelope(request, {"team_id": str(team_id), "user_id": str(payload.user_id)}),
        status_code=201,
    )


@router.delete("/{team_id}/members/{user_id}", status_code=204, summary="Remove a member")
async def remove_member(
    team_id: UUID,
    user_id: UUID,
    principal: MemberPrincipal,
    request: Request,
    session: SessionDep,
) -> Response:
    team = await _team(session, principal.tenant_id, team_id)
    await _can_manage(principal, team, "team:member:manage")
    member = await session.get(TeamMember, {"team_id": team_id, "user_id": user_id})
    if member is not None and member.tenant_id == principal.tenant_id:
        await session.delete(member)
        enqueue(
            session,
            event_type="team.member_removed",
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
            payload={"team_id": str(team_id), "user_id": str(user_id)},
        )
        await session.commit()
    return Response(status_code=204)


async def _service_guard(
    request: Request, x_service_token: Annotated[str | None, Header()] = None
) -> None:
    expected = request.app.state.settings.bootstrap_token
    if not expected or not x_service_token or not secrets.compare_digest(
        x_service_token, expected
    ):
        raise ApiError(403, "permission_denied", "Invalid service token.")


ServiceDep = Annotated[None, Depends(_service_guard)]


@internal_router.get("/teams/{team_id}/members", summary="Internal membership lookup")
async def internal_members(
    team_id: UUID,
    tenant_id: UUID,
    _: ServiceDep,
    request: Request,
    session: AdminSessionDep,
) -> JSONResponse:
    bind_tenant(session, tenant_id)
    team = await session.get(Team, team_id)
    if team is None or team.tenant_id != tenant_id:
        raise ApiError(404, "not_found", "Team not found.")
    rows = (
        await session.execute(select(TeamMember.user_id).where(TeamMember.team_id == team_id))
    ).scalars()
    return JSONResponse(envelope(request, {"user_ids": [str(item) for item in rows]}))


@internal_router.get(
    "/users/{user_id}/scope", summary="Internal team scope for a user"
)
async def internal_user_scope(
    user_id: UUID,
    tenant_id: UUID,
    _: ServiceDep,
    request: Request,
    session: AdminSessionDep,
) -> JSONResponse:
    bind_tenant(session, tenant_id)
    team_ids = set(
        (
            await session.execute(
                select(TeamMember.team_id).where(
                    TeamMember.tenant_id == tenant_id,
                    TeamMember.user_id == user_id,
                )
            )
        ).scalars()
    )
    user_ids = {user_id}
    if team_ids:
        user_ids.update(
            (
                await session.execute(
                    select(TeamMember.user_id).where(
                        TeamMember.tenant_id == tenant_id,
                        TeamMember.team_id.in_(team_ids),
                    )
                )
            ).scalars()
        )
    return JSONResponse(
        envelope(
            request,
            {
                "team_ids": [str(team_id) for team_id in sorted(team_ids, key=str)],
                "user_ids": [str(item) for item in sorted(user_ids, key=str)],
            },
        )
    )
