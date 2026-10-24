import hashlib
import os
import re
import uuid
from types import SimpleNamespace
from datetime import datetime
from typing import List, Optional, Tuple

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import case, or_
from sqlalchemy.orm import Session

import jira_service
import repo_analyzer
import schemas
from database import (
    JiraConnection,
    JiraRepositoryConnection,
    JiraStoryDraft,
    JiraUserToken,
    SRSDocument,
    Project as DBProject,
    Repository as DBRepository,
    get_db,
)

router = APIRouter(prefix="/api/jira/projects", tags=["Jira Story Drafts"])

DRAFT_STATUSES = {"draft", "approved", "rejected", "creating", "created", "failed"}


def _admin_emails() -> set:
    raw = os.getenv("SEER_ADMIN_EMAILS", "")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def is_admin_email(email: Optional[str]) -> bool:
    if not email:
        return False
    return email.strip().lower() in _admin_emails()


def _criteria_to_text(criteria: Optional[List[str]]) -> str:
    if not criteria:
        return ""
    return "\n".join(f"- {c}" for c in criteria if c and c.strip())


def _criteria_from_text(text: Optional[str]) -> List[str]:
    if not text:
        return []
    lines = []
    for line in text.splitlines():
        cleaned = line.strip()
        if cleaned.startswith("- "):
            cleaned = cleaned[2:].strip()
        elif cleaned.startswith("* "):
            cleaned = cleaned[2:].strip()
        if cleaned:
            lines.append(cleaned)
    return lines


def _fingerprint(project_id: str, source_type: str, source_ref: str, title: str) -> str:
    base = f"{project_id}|{source_type}|{source_ref}|{title.strip().lower()}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def draft_to_response(
    draft: JiraStoryDraft,
    repository: Optional[DBRepository] = None,
    jira_connection=None,
    uses_project_fallback: bool = False,
) -> schemas.JiraStoryDraftResponse:
    source_github_url = repository.github_url if repository else None
    source_ref = draft.source_ref or ""
    if repository and draft.source_type == "github_issue" and source_ref.startswith("github#"):
        issue_number = source_ref.removeprefix("github#")
        source_github_url = f"{repository.github_url.rstrip('/')}/issues/{issue_number}"
    return schemas.JiraStoryDraftResponse(
        id=draft.id,
        project_id=draft.project_id,
        repository_id=draft.repository_id,
        parent_draft_id=draft.parent_draft_id,
        repository_name=repository.name if repository else None,
        repository_url=repository.github_url if repository else None,
        title=draft.title,
        issue_type=draft.issue_type or "Story",
        description=draft.description,
        acceptance_criteria=_criteria_from_text(draft.acceptance_criteria),
        priority=draft.priority or "Medium",
        source_type=draft.source_type,
        source_ref=draft.source_ref,
        source_github_url=source_github_url,
        jira_project_key=draft.jira_project_key or getattr(jira_connection, "jira_project_key", None),
        jira_project_name=draft.jira_project_name or getattr(jira_connection, "jira_project_name", None),
        jira_project_id=draft.jira_project_id or getattr(jira_connection, "jira_project_id", None),
        jira_connected=bool(jira_connection),
        uses_project_jira_fallback=uses_project_fallback,
        status=draft.status,
        jira_issue_key=draft.jira_issue_key,
        jira_issue_id=draft.jira_issue_id,
        jira_issue_url=draft.jira_issue_url,
        jira_status=None,
        creation_error=draft.creation_error,
        created_by_email=draft.created_by_email,
        approved_by_email=draft.approved_by_email,
        created_at=draft.created_at,
        updated_at=draft.updated_at,
    )


def _get_project_context(project_id: str, db: Session) -> Tuple[DBProject, Optional[JiraConnection], List[DBRepository]]:
    project = db.query(DBProject).filter(DBProject.id == project_id).first()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    conn = db.query(JiraConnection).filter(JiraConnection.project_id == project_id).first()
    repos = db.query(DBRepository).filter(DBRepository.project_id == project_id).all()
    return project, conn, repos


def _repository_map(repositories: List[DBRepository]) -> dict:
    return {repository.id: repository for repository in repositories}


def _resolve_jira_connection(project_id: str, repository_id: Optional[str], db: Session):
    mapping = None
    if repository_id:
        mapping = db.query(JiraRepositoryConnection).filter(
            JiraRepositoryConnection.repository_id == repository_id,
            JiraRepositoryConnection.project_id == project_id,
        ).first()
    if mapping:
        return mapping, False
    project_connection = db.query(JiraConnection).filter(JiraConnection.project_id == project_id).first()
    return project_connection, bool(project_connection and repository_id)


def _project_destinations(project_id: str, db: Session) -> List[object]:
    destinations = []
    project_connection = db.query(JiraConnection).filter(JiraConnection.project_id == project_id).first()
    if project_connection:
        destinations.append(project_connection)
    destinations.extend(
        db.query(JiraRepositoryConnection)
        .filter(JiraRepositoryConnection.project_id == project_id)
        .order_by(JiraRepositoryConnection.jira_project_name.asc())
        .all()
    )
    unique = {}
    for destination in destinations:
        key = (destination.jira_project_key or "").strip().upper()
        if key and key not in unique:
            unique[key] = destination
    return list(unique.values())


def _destination_by_key(project_id: str, jira_project_key: str, db: Session):
    wanted = jira_project_key.strip().upper()
    return next(
        (destination for destination in _project_destinations(project_id, db)
         if destination.jira_project_key.strip().upper() == wanted),
        None,
    )


def _draft_connection(draft: JiraStoryDraft, db: Session):
    if draft.jira_project_key:
        return SimpleNamespace(
            jira_project_key=draft.jira_project_key,
            jira_project_name=draft.jira_project_name,
            jira_project_id=draft.jira_project_id,
            jira_cloud_id=draft.jira_cloud_id,
            site_url=draft.jira_site_url,
        ), False
    return _resolve_jira_connection(draft.project_id, draft.repository_id, db)


def _draft_to_response(
    draft: JiraStoryDraft,
    repository: Optional[DBRepository],
    db: Session,
    live_jira_status: Optional[str] = None,
):
    connection, uses_fallback = _draft_connection(draft, db)
    res = draft_to_response(draft, repository, connection, uses_fallback)
    if live_jira_status:
        res.jira_status = live_jira_status
    elif draft.status == "created":
        res.jira_status = "Created in Jira"
    elif draft.status == "approved":
        res.jira_status = "Approved"
    elif draft.status == "draft":
        res.jira_status = "Draft"
    elif draft.status == "rejected":
        res.jira_status = "Rejected"
    return res


def _resolve_user_token(email: Optional[str], db: Session) -> Optional[JiraUserToken]:
    if not email:
        return None
    return db.query(JiraUserToken).filter(JiraUserToken.user_email == email).first()


def _collect_story_candidates(project: DBProject, repos: List[DBRepository]) -> List[dict]:
    candidates: List[dict] = []
    project_desc = (project.description or "").strip()

    for repo in repos:
        cache = repo_analyzer.load_raw_cache(repo.id) or {}
        analysis = cache.get("analysis") or {}
        issues = cache.get("issues") or []

        if project_desc:
            candidates.append({
                "repository_id": repo.id,
                "source_type": "project_document",
                "source_ref": f"project:{project.id}",
                "title": f"Align {repo.name} with project goals",
                "description": f"Ensure the {repo.name} repository supports the project objective: {project_desc}",
                "acceptance_criteria": [
                    "Repository README documents the project goal",
                    "Core user flows map to the stated project objective",
                    "Missing capabilities are tracked as follow-up work",
                ],
                "priority": "Medium",
            })

        overview = (analysis.get("overview") or "").strip()
        if overview:
            candidates.append({
                "repository_id": repo.id,
                "source_type": "repository_analysis",
                "source_ref": f"{repo.owner}/{repo.name}:overview",
                "title": f"Document and validate architecture for {repo.name}",
                "description": overview[:1200],
                "acceptance_criteria": [
                    "Architecture overview is reviewed with the team",
                    "Key modules listed in analysis are mapped to owners",
                    "Gaps identified in the overview are prioritized",
                ],
                "priority": "Medium",
            })

        for comp in analysis.get("key_components_details") or []:
            name = comp.get("name") or comp.get("path") or "Component"
            candidates.append({
                "repository_id": repo.id,
                "source_type": "key_component",
                "source_ref": comp.get("path") or name,
                "title": f"Implement and test {name}",
                "description": comp.get("purpose") or f"Work on component {name} in {repo.name}.",
                "acceptance_criteria": [
                    f"Component `{name}` behavior matches documented purpose",
                    "Unit or integration coverage exists for primary paths",
                    "Component dependencies are documented",
                ],
                "priority": "High" if "auth" in name.lower() or "payment" in name.lower() else "Medium",
            })

        for api in analysis.get("api_surface_details") or []:
            endpoint = api.get("endpoint") or "endpoint"
            method = api.get("method") or "GET"
            candidates.append({
                "repository_id": repo.id,
                "source_type": "api_surface",
                "source_ref": f"{method} {endpoint}",
                "title": f"Verify API {method} {endpoint}",
                "description": api.get("description") or f"Validate API surface {method} {endpoint}.",
                "acceptance_criteria": [
                    f"{method} {endpoint} returns expected success responses",
                    "Validation and error responses are documented",
                    "Authentication/authorization rules are enforced if applicable",
                ],
                "priority": "High",
            })

        for integration in analysis.get("integration_points_details") or []:
            service = integration.get("service_name") or "External service"
            candidates.append({
                "repository_id": repo.id,
                "source_type": "integration",
                "source_ref": integration.get("file_config") or service,
                "title": f"Harden integration with {service}",
                "description": integration.get("purpose") or f"Integration work for {service}.",
                "acceptance_criteria": [
                    f"Integration with {service} handles success and failure paths",
                    "Configuration is documented for all environments",
                    "Monitoring or logging exists for integration failures",
                ],
                "priority": "Medium",
            })

        open_issues = [i for i in issues if str(i.get("state", "")).lower() == "open"]
        for gh_issue in open_issues[:8]:
            title = (gh_issue.get("title") or "").strip()
            if not title:
                continue
            candidates.append({
                "repository_id": repo.id,
                "source_type": "github_issue",
                "source_ref": f"github#{gh_issue.get('number')}",
                "title": f"Track GitHub issue: {title}",
                "description": f"GitHub issue #{gh_issue.get('number')} in {repo.name} may require Jira tracking.",
                "acceptance_criteria": [
                    "Scope from GitHub issue is captured in Jira",
                    "Owner and priority are assigned",
                    "Completion criteria match the GitHub issue intent",
                ],
                "priority": "High" if any(l.lower() in {"bug", "critical"} for l in gh_issue.get("labels") or []) else "Medium",
            })

    deduped = {}
    for item in candidates:
        fp = _fingerprint(project.id, item["source_type"], item["source_ref"], item["title"])
        deduped[fp] = item
    return list(deduped.values())


def _collect_srs_epic(
    project: DBProject,
    document: SRSDocument,
    custom_title: Optional[str] = None,
    custom_description: Optional[str] = None,
    priority: Optional[str] = "High",
) -> dict:
    """Extract an Epic draft from an SRS document without forcing Story creation."""
    raw_text = (document.extracted_text or "").strip()
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]

    # 1. Title extraction
    title = (custom_title or "").strip()
    if not title:
        for line in lines[:8]:
            clean_line = re.sub(r"^[#\s\-*]+", "", line).strip()
            clean_line = clean_line.replace("\ufffd", " - ").replace("", " - ")
            if len(clean_line) > 5 and not re.match(
                r"(?i)^(software\s+requirements|srs|document\s+control|version|date|status)",
                clean_line,
            ):
                title = clean_line[:250]
                break
        if not title:
            base_name = document.filename.rsplit(".", 1)[0]
            title = f"SRS: {base_name[:240]}"

    # 2. Description extraction
    description = (custom_description or "").strip()
    if not description:
        purpose_match = re.search(
            r"(?is)(?:1\.\d\s+)?(?:purpose|scope|overview|executive\s+summary)[\s:\-]+(.*?)(?=\n\s*(?:1\.\d|\d\.\d|[A-Z][a-z]+:|\n\n\n|$))",
            raw_text,
        )
        if purpose_match:
            extracted_purpose = " ".join(purpose_match.group(1).split())
            description = f"Epic derived from SRS: {document.filename}.\n\nScope & Objectives:\n{extracted_purpose[:1200]}"
        else:
            substantive = [
                l for l in lines[:15]
                if len(l) > 30 and not re.search(r"(?i)(version|date|author|table\s+of\s+contents)", l)
            ]
            summary_part = " ".join(substantive[:3]) if substantive else f"Implementation of requirements outlined in {document.filename}."
            description = f"Epic derived from SRS: {document.filename}.\n\nScope & Objectives:\n{summary_part[:1200]}"

    # 3. Acceptance criteria
    criteria = [
        "Core functional flows and module behaviors match SRS specifications",
        "User interface and interaction requirements are validated against SRS designs",
        "Integration endpoints and data models adhere to specification",
        "Acceptance testing criteria defined in SRS pass successfully",
    ]

    return {
        "repository_id": None,
        "source_type": "srs_epic",
        "source_ref": document.id,
        "issue_type": "Epic",
        "title": title[:255],
        "description": description,
        "acceptance_criteria": criteria,
        "priority": priority or "High",
    }


def _collect_srs_candidates(project: DBProject, document: SRSDocument) -> List[dict]:
    """Turn common SRS headings and user-story lines into reviewable Jira drafts."""
    lines = [line.strip() for line in (document.extracted_text or "").splitlines() if line.strip()]
    candidates: List[dict] = [_collect_srs_epic(project, document)]
    for index, line in enumerate(lines):
        normalized = line.lstrip("- *").strip()
        if not re.match(r"(?i)^(as\s+.+,\s+i\s+want|user\s+story\s*:|requirement\s*[:\-])", normalized):
            continue
        title = normalized.split(":", 1)[-1].strip() if ":" in normalized else normalized
        candidates.append({
            "repository_id": None,
            "source_type": "srs_story",
            "source_ref": f"{document.id}:line:{index + 1}",
            "parent_source_ref": document.id,
            "issue_type": "Story",
            "title": title[:255],
            "description": f"Requirement from {document.filename}: {normalized}",
            "acceptance_criteria": ["Requirement behavior is implemented", "Requirement is validated with acceptance tests"],
            "priority": "Medium",
        })
    return candidates


def _existing_fingerprints(db: Session, project_id: str) -> set:
    rows = db.query(JiraStoryDraft.fingerprint).filter(JiraStoryDraft.project_id == project_id).all()
    return {r[0] for r in rows}


def _create_draft_row(project_id: str, item: dict, created_by: Optional[str]) -> JiraStoryDraft:
    fp = _fingerprint(project_id, item["source_type"], item["source_ref"], item["title"])
    now = datetime.utcnow()
    return JiraStoryDraft(
        id=str(uuid.uuid4()),
        project_id=project_id,
        repository_id=item.get("repository_id"),
        parent_draft_id=item.get("parent_draft_id"),
        fingerprint=fp,
        title=item["title"][:255],
        description=item.get("description"),
        acceptance_criteria=_criteria_to_text(item.get("acceptance_criteria")),
        priority=item.get("priority") or "Medium",
        issue_type=item.get("issue_type") or "Story",
        source_type=item.get("source_type"),
        source_ref=item.get("source_ref"),
        status="draft",
        created_by_email=created_by,
        created_at=now,
        updated_at=now,
    )


def _snapshot_draft_destination(draft: JiraStoryDraft, db: Session) -> None:
    connection, _ = _resolve_jira_connection(draft.project_id, draft.repository_id, db)
    if not connection:
        return
    draft.jira_project_key = connection.jira_project_key
    draft.jira_project_name = connection.jira_project_name
    draft.jira_project_id = connection.jira_project_id
    draft.jira_cloud_id = connection.jira_cloud_id
    draft.jira_site_url = connection.site_url


def _snapshot_connection(draft: JiraStoryDraft, connection) -> None:
    draft.jira_project_key = connection.jira_project_key
    draft.jira_project_name = connection.jira_project_name
    draft.jira_project_id = connection.jira_project_id
    draft.jira_cloud_id = connection.jira_cloud_id
    draft.jira_site_url = connection.site_url


def _get_access_token(user_token: JiraUserToken, db: Session) -> str:
    return user_token.access_token


def _refresh_access_token(user_token: JiraUserToken, db: Session) -> str:
    if not user_token.refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Jira access token expired and no refresh token is available. Reconnect Jira account.",
        )
    refreshed = jira_service.refresh_access_token(user_token.refresh_token)
    new_access_token = refreshed.get("access_token")
    if not new_access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Jira token refresh returned no access token. Reconnect Jira account.",
        )
    user_token.access_token = new_access_token
    if refreshed.get("refresh_token"):
        user_token.refresh_token = refreshed["refresh_token"]
    db.commit()
    return new_access_token


def _jira_project_field(conn: JiraConnection) -> dict:
    """Use the Jira project id when available; it is unambiguous across project types."""
    project_id = (conn.jira_project_id or "").strip()
    project_key = (conn.jira_project_key or "").strip()
    if project_id:
        return {"id": project_id}
    if project_key:
        return {"key": project_key}
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="The connected Jira project is missing its project id and key. Reconnect the Jira project.",
    )


def _verify_jira_destination(conn, access_token: str, cloud_id: str) -> dict:
    """Resolve the configured project against the projects visible to this token."""
    configured_key = (conn.jira_project_key or "").strip().upper()
    configured_id = (conn.jira_project_id or "").strip()
    try:
        projects = jira_service.fetch_jira_projects(access_token, cloud_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not verify the connected Jira project: {exc}",
        )

    project = next(
        (
            item for item in projects
            if (configured_id and str(item.get("id") or "") == configured_id)
            or (configured_key and str(item.get("key") or "").upper() == configured_key)
        ),
        None,
    )
    if not project:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Jira project '{conn.jira_project_key}' is not accessible to the connected Jira account. "
                "Reconnect Jira and select one of the projects available to that account."
            ),
        )
    return {"id": str(project.get("id")), "key": project.get("key")}


def _create_issue_for_draft(
    draft: JiraStoryDraft,
    conn,
    user_token: JiraUserToken,
    db: Session,
    approved_by: Optional[str],
) -> JiraStoryDraft:
    if draft.status == "created" and draft.jira_issue_key:
        return draft

    draft_issue_type = draft.issue_type or "Story"
    existing = db.query(JiraStoryDraft).filter(
        JiraStoryDraft.project_id == draft.project_id,
        JiraStoryDraft.id != draft.id,
        JiraStoryDraft.title == draft.title,
        JiraStoryDraft.issue_type == draft_issue_type,
        JiraStoryDraft.jira_project_key == conn.jira_project_key,
        JiraStoryDraft.status == "created",
        JiraStoryDraft.jira_issue_key.isnot(None),
    ).first()
    if existing:
        # Prevent duplicate Jira creation and correctly synchronize draft status with the existing Jira issue key
        draft.status = "created"
        draft.jira_issue_key = existing.jira_issue_key
        draft.jira_issue_id = existing.jira_issue_id
        draft.jira_issue_url = existing.jira_issue_url
        draft.creation_error = None
        if approved_by and not draft.approved_by_email:
            draft.approved_by_email = approved_by
        draft.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(draft)
        return draft

    cloud_id = conn.jira_cloud_id or user_token.cloud_id
    if not cloud_id:
        draft.status = "failed"
        draft.creation_error = "Jira cloud site is not available for this connection."
        draft.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(draft)
        return draft

    access_token = _get_access_token(user_token, db)
    parent_key = None
    if draft.parent_draft_id:
        parent = db.query(JiraStoryDraft).filter(
            JiraStoryDraft.id == draft.parent_draft_id,
            JiraStoryDraft.project_id == draft.project_id,
        ).first()
        if not parent:
            draft.status = "failed"
            draft.creation_error = "The parent Epic draft could not be found in this SEER AI project."
            draft.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(draft)
            return draft
        if parent.status != "created" or not parent.jira_issue_key:
            parent_connection, _ = _draft_connection(parent, db)
            if not parent_connection:
                draft.status = "failed"
                draft.creation_error = "Select a Jira project for the parent Epic before creating this Story."
                draft.updated_at = datetime.utcnow()
                db.commit()
                db.refresh(draft)
                return draft
            parent = _create_issue_for_draft(parent, parent_connection, user_token, db, approved_by)
        if parent.status != "created" or not parent.jira_issue_key:
            draft.status = "failed"
            draft.creation_error = parent.creation_error or "The parent Epic could not be created in Jira."
            draft.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(draft)
            return draft
        parent_key = parent.jira_issue_key
    try:
        project_field = _verify_jira_destination(conn, access_token, cloud_id)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            try:
                access_token = _refresh_access_token(user_token, db)
                project_field = _verify_jira_destination(conn, access_token, cloud_id)
            except HTTPException as refresh_exc:
                exc = refresh_exc
            else:
                exc = None
        if exc is None:
            pass
        else:
            draft.status = "failed"
            draft.creation_error = exc.detail
            draft.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(draft)
            return draft

    try:
        dup_issues = jira_service.search_issues_by_summary(
            access_token, cloud_id, conn.jira_project_key or "", draft.title, issue_type=draft_issue_type
        )
    except HTTPException as exc:
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            try:
                access_token = _refresh_access_token(user_token, db)
                dup_issues = jira_service.search_issues_by_summary(
                    access_token, cloud_id, conn.jira_project_key or "", draft.title, issue_type=draft_issue_type
                )
            except Exception:
                dup_issues = []
        else:
            dup_issues = []
    except Exception:
        dup_issues = []

    if dup_issues:
        issue = dup_issues[0]
        key = issue.get("key")
        draft.status = "created"
        draft.jira_issue_key = key
        draft.jira_issue_id = str(issue.get("id")) if issue.get("id") else None
        site = conn.site_url or user_token.site_url
        draft.jira_issue_url = f"{site.rstrip('/')}/browse/{key}" if site and key else None
        draft.creation_error = None
        draft.approved_by_email = approved_by
        draft.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(draft)
        return draft

    draft.status = "creating"
    draft.creation_error = None
    draft.updated_at = datetime.utcnow()
    db.commit()

    try:
        created = jira_service.create_jira_issue(
            access_token=access_token,
            cloud_id=cloud_id,
            project_field=project_field,
            summary=draft.title,
            description=draft.description or "",
            acceptance_criteria=_criteria_from_text(draft.acceptance_criteria),
            priority=draft.priority or "Medium",
            issue_type=draft.issue_type or "Story",
            site_url=conn.site_url or user_token.site_url,
            parent_key=parent_key,
        )
        draft.status = "created"
        draft.jira_issue_key = created.get("key")
        draft.jira_issue_id = created.get("id")
        draft.jira_issue_url = created.get("url")
        draft.creation_error = None
        draft.approved_by_email = approved_by
    except HTTPException as exc:
        draft.status = "failed"
        draft.creation_error = str(exc.detail)
    except Exception as exc:
        draft.status = "failed"
        draft.creation_error = str(exc)

    draft.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(draft)
    return draft


@router.get("/{projectId}/story-drafts", response_model=schemas.JiraStoryDraftListResponse)
def list_story_drafts(
    projectId: str,
    repositoryId: Optional[str] = Query(None),
    jiraProjectKey: Optional[str] = Query(None),
    issueType: Optional[str] = Query(None),
    x_user_email: Optional[str] = Header(None, alias="X-User-Email"),
    db: Session = Depends(get_db),
):
    project, conn, repos = _get_project_context(projectId, db)
    draft_query = db.query(JiraStoryDraft).filter(JiraStoryDraft.project_id == projectId)
    if repositoryId:
        draft_query = draft_query.filter(JiraStoryDraft.repository_id == repositoryId)
    if jiraProjectKey:
        destination = _destination_by_key(projectId, jiraProjectKey, db)
        if not destination:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Select a Jira project mapped to this SEER AI project.")
        draft_query = draft_query.filter(JiraStoryDraft.jira_project_key == destination.jira_project_key)
    if issueType:
        draft_query = draft_query.filter(JiraStoryDraft.issue_type == issueType)
    drafts = draft_query.order_by(
        JiraStoryDraft.updated_at.desc()
    ).all()
    repositories_by_id = _repository_map(repos)
    return schemas.JiraStoryDraftListResponse(
        drafts=[_draft_to_response(d, repositories_by_id.get(d.repository_id), db) for d in drafts],
        jira_connected=conn is not None,
        repository_connected=len(repos) > 0,
        auto_create_enabled=bool(getattr(project, "jira_auto_create_enabled", False)),
        is_admin=is_admin_email(x_user_email),
    )


@router.get("/{projectId}/destinations", response_model=List[schemas.JiraProjectDestination])
def list_project_destinations(projectId: str, db: Session = Depends(get_db)):
    _get_project_context(projectId, db)
    return [
        schemas.JiraProjectDestination(
            key=destination.jira_project_key,
            name=destination.jira_project_name,
            id=destination.jira_project_id,
        )
        for destination in _project_destinations(projectId, db)
    ]


@router.post("/{projectId}/story-drafts/epics", response_model=schemas.JiraStoryDraftResponse)
def create_epic_draft(
    projectId: str,
    payload: schemas.JiraEpicCreateRequest,
    x_user_email: Optional[str] = Header(None, alias="X-User-Email"),
    db: Session = Depends(get_db),
):
    _get_project_context(projectId, db)
    connection = _destination_by_key(projectId, payload.jira_project_key, db)
    if not connection:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Select a Jira project mapped to this SEER AI project.")
    row = _create_draft_row(projectId, {
        "source_type": "manual_epic",
        "source_ref": str(uuid.uuid4()),
        "issue_type": "Epic",
        "title": payload.title.strip(),
        "description": payload.description,
        "acceptance_criteria": payload.acceptance_criteria or [],
        "priority": payload.priority or "High",
    }, x_user_email)
    _snapshot_connection(row, connection)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _draft_to_response(row, None, db)


@router.post("/{projectId}/story-drafts/epics/generate-from-srs", response_model=schemas.JiraStoryDraftResponse)
def generate_epic_draft_from_srs(
    projectId: str,
    payload: schemas.JiraEpicGenerateFromSRSRequest,
    x_user_email: Optional[str] = Header(None, alias="X-User-Email"),
    db: Session = Depends(get_db),
):
    """
    Generate an Epic draft directly from an uploaded SRS document.
    Does not require or automatically create Scrum boards, Sprints, or Stories.
    """
    project, conn, _ = _get_project_context(projectId, db)
    connection = _destination_by_key(projectId, payload.jira_project_key, db)
    if not connection:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Select a Jira project mapped to this SEER AI project.")

    document_query = db.query(SRSDocument).filter(SRSDocument.project_id == projectId)
    if payload.srs_document_id:
        document_query = document_query.filter(SRSDocument.id == payload.srs_document_id)
    document = document_query.order_by(SRSDocument.created_at.desc()).first()
    if not document:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Upload an SRS document before generating an Epic draft.")

    item = _collect_srs_epic(project, document, payload.custom_title, payload.custom_description, payload.priority)

    # Check if a draft Epic for this SRS document already exists in draft status
    existing = db.query(JiraStoryDraft).filter(
        JiraStoryDraft.project_id == projectId,
        JiraStoryDraft.source_type == "srs_epic",
        JiraStoryDraft.source_ref == document.id,
        JiraStoryDraft.jira_project_key == connection.jira_project_key,
    ).first()

    if existing and existing.status == "draft":
        existing.title = item["title"][:255]
        existing.description = item["description"]
        existing.acceptance_criteria = _criteria_to_text(item["acceptance_criteria"])
        existing.priority = item["priority"]
        existing.updated_at = datetime.utcnow()
        _snapshot_connection(existing, connection)
        db.commit()
        db.refresh(existing)
        return _draft_to_response(existing, None, db)

    row = _create_draft_row(projectId, item, x_user_email)
    _snapshot_connection(row, connection)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _draft_to_response(row, None, db)


@router.post("/{projectId}/story-drafts/generate", response_model=schemas.JiraStoryGenerateResponse)
def generate_story_drafts(
    projectId: str,
    payload: schemas.JiraStoryGenerateRequest,
    x_user_email: Optional[str] = Header(None, alias="X-User-Email"),
    db: Session = Depends(get_db),
):
    project, conn, repos = _get_project_context(projectId, db)
    selected_destination = None
    if payload.jira_project_key:
        selected_destination = _destination_by_key(projectId, payload.jira_project_key, db)
        if not selected_destination:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Select a Jira project mapped to this SEER AI project.")
    elif payload.context in {"srs", "combined"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Select a mapped Jira project before generating SRS drafts.")
    parent_epic = None
    if payload.parent_epic_draft_id:
        parent_epic = db.query(JiraStoryDraft).filter(
            JiraStoryDraft.id == payload.parent_epic_draft_id,
            JiraStoryDraft.project_id == projectId,
            JiraStoryDraft.issue_type == "Epic",
        ).first()
        if not parent_epic:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Selected parent Epic is not part of this SEER AI project.")
        if payload.jira_project_key and parent_epic.jira_project_key.strip().upper() != payload.jira_project_key.strip().upper():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Parent Epic must use the selected Jira project.")
    if not repos and payload.context in {"github", "combined"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Connect at least one GitHub repository before generating story drafts.",
        )

    if payload.context in {"github", "combined"} and not payload.repository_id and not payload.all_repositories:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Select a GitHub repository or intentionally choose All repositories before generating drafts.",
        )
    if payload.context in {"github", "combined"} and payload.repository_id and payload.all_repositories:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Choose either one GitHub repository or All repositories, not both.",
        )
    if payload.repository_id:
        selected_repository = next((r for r in repos if r.id == payload.repository_id), None)
        if not selected_repository:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Selected repository is not connected to this project.")
        repos = [selected_repository]

    unmapped_repositories = [
        repository.name
        for repository in repos
        if not db.query(JiraRepositoryConnection).filter(
            JiraRepositoryConnection.project_id == projectId,
            JiraRepositoryConnection.repository_id == repository.id,
        ).first()
    ]
    if unmapped_repositories and payload.context in {"github", "combined"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Map each selected repository to a Jira project before generating drafts: {', '.join(unmapped_repositories)}.",
        )

    candidates = []
    if payload.context in {"github", "combined"}:
        candidates.extend(_collect_story_candidates(project, repos))
    if payload.context in {"srs", "combined"}:
        document_query = db.query(SRSDocument).filter(SRSDocument.project_id == projectId)
        if payload.srs_document_id:
            document_query = document_query.filter(SRSDocument.id == payload.srs_document_id)
        document = document_query.order_by(SRSDocument.created_at.desc()).first()
        if not document:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Upload an SRS document before generating SRS drafts.")
        candidates.extend(_collect_srs_candidates(project, document))
    existing_fps = _existing_fingerprints(db, projectId)
    created_rows: List[JiraStoryDraft] = []
    created_items: List[Tuple[JiraStoryDraft, dict]] = []
    skipped = 0

    for item in candidates:
        if parent_epic and item.get("issue_type", "Story") != "Epic" and not item.get("parent_source_ref"):
            item["parent_draft_id"] = parent_epic.id
        fp = _fingerprint(projectId, item["source_type"], item["source_ref"], item["title"])
        if fp in existing_fps:
            skipped += 1
            continue
        row = _create_draft_row(projectId, item, x_user_email)
        if selected_destination:
            _snapshot_connection(row, selected_destination)
        else:
            _snapshot_draft_destination(row, db)
        db.add(row)
        created_rows.append(row)
        created_items.append((row, item))
        existing_fps.add(fp)

    db.flush()
    epic_by_source = {
        row.source_ref: row
        for row in created_rows
        if row.issue_type == "Epic" and row.source_ref
    }
    for row, item in created_items:
        parent_source_ref = item.get("parent_source_ref")
        if parent_source_ref:
            parent = epic_by_source.get(parent_source_ref) or db.query(JiraStoryDraft).filter(
                JiraStoryDraft.project_id == projectId,
                JiraStoryDraft.source_type == "srs_epic",
                JiraStoryDraft.source_ref == parent_source_ref,
            ).first()
            if parent:
                row.parent_draft_id = parent.id

    db.commit()
    for row in created_rows:
        db.refresh(row)

    auto_created_count = 0
    auto_enabled = bool(getattr(project, "jira_auto_create_enabled", False))
    user_token = _resolve_user_token(x_user_email, db)
    if auto_enabled and user_token:
        for row in created_rows:
            row_connection, _ = _draft_connection(row, db)
            if row_connection:
                _create_issue_for_draft(row, row_connection, user_token, db, x_user_email)
            if row.status == "created":
                auto_created_count += 1

    draft_query = db.query(JiraStoryDraft).filter(JiraStoryDraft.project_id == projectId)
    if payload.repository_id:
        draft_query = draft_query.filter(JiraStoryDraft.repository_id == payload.repository_id)
    if payload.jira_project_key:
        draft_query = draft_query.filter(JiraStoryDraft.jira_project_key == selected_destination.jira_project_key)
    all_drafts = draft_query.order_by(
        JiraStoryDraft.updated_at.desc()
    ).all()
    repositories_by_id = _repository_map(_get_project_context(projectId, db)[2])

    return schemas.JiraStoryGenerateResponse(
        created_count=len(created_rows),
        skipped_duplicates=skipped,
        auto_created_count=auto_created_count,
        drafts=[_draft_to_response(d, repositories_by_id.get(d.repository_id), db) for d in all_drafts],
    )


@router.patch("/{projectId}/story-drafts/{draftId}", response_model=schemas.JiraStoryDraftResponse)
def update_story_draft(
    projectId: str,
    draftId: str,
    payload: schemas.JiraStoryDraftUpdate,
    db: Session = Depends(get_db),
):
    draft = db.query(JiraStoryDraft).filter(
        JiraStoryDraft.id == draftId,
        JiraStoryDraft.project_id == projectId,
    ).first()
    if not draft:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Story draft not found")
    if draft.status == "created":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Created Jira issues cannot be edited.")

    if payload.title is not None:
        draft.title = payload.title.strip()[:255]
    if payload.description is not None:
        draft.description = payload.description
    if payload.acceptance_criteria is not None:
        draft.acceptance_criteria = _criteria_to_text(payload.acceptance_criteria)
    if payload.priority is not None:
        draft.priority = payload.priority

    draft.status = "draft"
    draft.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(draft)
    repository = db.query(DBRepository).filter(DBRepository.id == draft.repository_id).first()
    return _draft_to_response(draft, repository, db)


@router.post("/{projectId}/story-drafts/{draftId}/approve", response_model=schemas.JiraStoryDraftResponse)
def approve_story_draft(
    projectId: str,
    draftId: str,
    x_user_email: Optional[str] = Header(None, alias="X-User-Email"),
    db: Session = Depends(get_db),
):
    draft = db.query(JiraStoryDraft).filter(
        JiraStoryDraft.id == draftId,
        JiraStoryDraft.project_id == projectId,
    ).first()
    if not draft:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Story draft not found")
    if draft.status == "rejected":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Rejected drafts must be edited before approval.")
    if draft.status == "created":
        repository = db.query(DBRepository).filter(DBRepository.id == draft.repository_id).first()
        return _draft_to_response(draft, repository, db)

    conn, _ = _draft_connection(draft, db)
    if not conn:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Connect or select a Jira project before approving.")

    user_token = _resolve_user_token(x_user_email, db)
    if not user_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authenticate Jira (Connect Jira) before approving drafts.",
        )

    draft.status = "approved"
    draft.approved_by_email = x_user_email
    draft.updated_at = datetime.utcnow()
    db.commit()

    draft = _create_issue_for_draft(draft, conn, user_token, db, x_user_email)
    repository = db.query(DBRepository).filter(DBRepository.id == draft.repository_id).first()
    return _draft_to_response(draft, repository, db)


@router.post("/{projectId}/story-drafts/{draftId}/reject", response_model=schemas.JiraStoryDraftResponse)
def reject_story_draft(
    projectId: str,
    draftId: str,
    db: Session = Depends(get_db),
):
    draft = db.query(JiraStoryDraft).filter(
        JiraStoryDraft.id == draftId,
        JiraStoryDraft.project_id == projectId,
    ).first()
    if not draft:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Story draft not found")
    if draft.status == "created":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Created Jira issues cannot be rejected.")

    draft.status = "rejected"
    draft.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(draft)
    repository = db.query(DBRepository).filter(DBRepository.id == draft.repository_id).first()
    return _draft_to_response(draft, repository, db)


@router.get("/{projectId}/story-drafts/settings/auto-create", response_model=schemas.JiraAutoCreateSettings)
def get_auto_create_settings(
    projectId: str,
    x_user_email: Optional[str] = Header(None, alias="X-User-Email"),
    db: Session = Depends(get_db),
):
    project, _, _ = _get_project_context(projectId, db)
    return schemas.JiraAutoCreateSettings(
        enabled=bool(getattr(project, "jira_auto_create_enabled", False)),
        is_admin=is_admin_email(x_user_email),
    )


@router.put("/{projectId}/story-drafts/settings/auto-create", response_model=schemas.JiraAutoCreateSettings)
def update_auto_create_settings(
    projectId: str,
    payload: schemas.JiraAutoCreateUpdate,
    x_user_email: Optional[str] = Header(None, alias="X-User-Email"),
    db: Session = Depends(get_db),
):
    if not is_admin_email(x_user_email):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin permission required.")

    project, _, _ = _get_project_context(projectId, db)
    project.jira_auto_create_enabled = bool(payload.enabled)
    project.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(project)
    return schemas.JiraAutoCreateSettings(
        enabled=bool(project.jira_auto_create_enabled),
        is_admin=True,
    )
