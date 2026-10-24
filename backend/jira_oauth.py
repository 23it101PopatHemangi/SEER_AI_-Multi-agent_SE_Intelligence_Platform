import os
import re
import urllib.parse
import secrets
import uuid
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Query, Header
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from database import get_db, Project as DBProject, Repository as DBRepository, JiraConnection, JiraRepositoryConnection, JiraUserToken
import schemas
import jira_service

router = APIRouter(prefix="/api/jira", tags=["Jira OAuth"])


def _repository_for_project(project_id: str, repository_id: str, db: Session) -> DBRepository:
    repository = db.query(DBRepository).filter(
        DBRepository.id == repository_id,
        DBRepository.project_id == project_id,
    ).first()
    if not repository:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found in this project.")
    return repository


def _jira_connection_response(connection, repository_id: Optional[str] = None):
    data = {
        "id": connection.id,
        "project_id": connection.project_id,
        "jira_project_key": connection.jira_project_key,
        "jira_project_name": connection.jira_project_name,
        "jira_project_id": connection.jira_project_id,
        "jira_cloud_id": connection.jira_cloud_id,
        "site_url": connection.site_url,
        "connected_at": getattr(connection, "connected_at", None) or getattr(connection, "created_at", None),
        "created_at": getattr(connection, "created_at", None),
        "updated_at": getattr(connection, "updated_at", None),
    }
    if repository_id is not None:
        data["repository_id"] = repository_id
    return data


@router.get("/auth-url")
def get_auth_url(
    user_email: str = Query(...),
    project_id: str = Query(...)
):
    """
    Generates the Atlassian OAuth 2.0 (3LO) authorization redirect URL.
    Encodes user_email, project_id, and nonce in the state parameter.
    """
    jira_service.check_oauth_credentials()
    client_id, _, redirect_uri = jira_service.get_oauth_credentials()

    nonce = secrets.token_hex(8)
    state = f"{user_email}:{project_id}:{nonce}"
    encoded_state = urllib.parse.quote(state)
    encoded_redirect = urllib.parse.quote(redirect_uri)

    # Scopes required for Jira project tracking and approved issue creation
    scopes = "read:jira-work write:jira-work read:jira-user offline_access read:me"
    encoded_scopes = urllib.parse.quote(scopes)

    auth_url = (
        f"https://auth.atlassian.com/authorize"
        f"?audience=api.atlassian.com"
        f"&client_id={client_id}"
        f"&scope={encoded_scopes}"
        f"&redirect_uri={encoded_redirect}"
        f"&state={encoded_state}"
        f"&response_type=code"
        f"&prompt=consent"
    )
    return {"auth_url": auth_url}


@router.get("/callback")
def oauth_callback(
    code: str = Query(None),
    state: str = Query(None),
    error: str = Query(None),
    error_description: str = Query(None),
    db: Session = Depends(get_db)
):
    """
    Callback endpoint that Atlassian redirects to after authorization.
    Exchanges code for tokens, resolves user cloud sites, stores JiraUserToken,
    and redirects the browser back to the project overview page.
    """
    # 1. Handle Atlassian authorization errors
    if error:
        err_msg = error_description or error
        # Try extracting project_id from state if possible to redirect back with error param
        target_project_id = ""
        if state:
            try:
                target_project_id = state.split(":")[1]
            except Exception:
                pass
        if target_project_id:
            return RedirectResponse(
                url=f"http://localhost:5173/projects/{target_project_id}/overview?jira_error={urllib.parse.quote(err_msg)}"
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Atlassian OAuth error: {err_msg}"
        )

    if not code or not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authorization code or state parameter is missing."
        )

    # 2. Parse state parameter (format: user_email:project_id:nonce)
    try:
        parts = state.split(":")
        if len(parts) < 2:
            raise ValueError("Too few parts")
        user_email = parts[0]
        project_id = parts[1]
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid state parameter structure."
        )

    jira_service.check_oauth_credentials()
    _, _, redirect_uri = jira_service.get_oauth_credentials()

    # 3. Exchange code for access & refresh tokens
    token_data = jira_service.exchange_code_for_token(code, redirect_uri)
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")

    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No access token returned by Atlassian."
        )

    # 4. Fetch accessible Cloud resources (sites)
    resources = jira_service.get_accessible_resources(access_token)
    cloud_id = None
    site_url = None
    if resources and len(resources) > 0:
        cloud_id = resources[0].get("id")
        site_url = resources[0].get("url")

    # 5. Fetch user profile from /me
    user_info = jira_service.fetch_jira_user(access_token)
    jira_user_id = user_info.get("account_id")
    jira_display_name = user_info.get("name") or user_info.get("email")

    # 6. Save or update Jira user token in DB
    db_token = db.query(JiraUserToken).filter(JiraUserToken.user_email == user_email).first()
    if db_token:
        db_token.access_token = access_token
        if refresh_token:
            db_token.refresh_token = refresh_token
        db_token.cloud_id = cloud_id
        db_token.site_url = site_url
        db_token.jira_user_id = jira_user_id
        db_token.jira_display_name = jira_display_name
    else:
        db_token = JiraUserToken(
            user_email=user_email,
            access_token=access_token,
            refresh_token=refresh_token,
            cloud_id=cloud_id,
            site_url=site_url,
            jira_user_id=jira_user_id,
            jira_display_name=jira_display_name
        )
        db.add(db_token)

    db.commit()

    # 7. Redirect back to frontend Project Overview with success parameter
    frontend_url = f"http://localhost:5173/projects/{project_id}/overview?jira_auth=success"
    return RedirectResponse(url=frontend_url)


@router.get("/projects/{projectId}/status", response_model=schemas.JiraStatusResponse)
def get_jira_status(
    projectId: str,
    user_email: Optional[str] = Query(None),
    x_user_email: Optional[str] = Header(None, alias="X-User-Email"),
    db: Session = Depends(get_db)
):
    """
    Checks the Jira connection status for a project and the authenticated user.
    Returns:
    - authenticated: whether the user has connected their Atlassian account
    - connected: whether this project is linked to a Jira project
    - connection: active JiraConnection details if connected
    - available_projects: Jira projects available to select from
    """
    email = user_email or x_user_email

    # 1. Check project connection in DB
    conn = db.query(JiraConnection).filter(JiraConnection.project_id == projectId).first()
    is_connected = conn is not None

    # 2. Check user Atlassian token
    user_token = None
    if email:
        user_token = db.query(JiraUserToken).filter(JiraUserToken.user_email == email).first()

    is_authenticated = user_token is not None

    available_projects: List[schemas.JiraProjectOption] = []
    jira_user = None

    if user_token:
        jira_user = user_token.jira_display_name or user_token.jira_user_id
        # Attempt to fetch available Jira projects for the user
        if user_token.cloud_id:
            try:
                raw_projects = jira_service.fetch_jira_projects(user_token.access_token, user_token.cloud_id)
                available_projects = [schemas.JiraProjectOption(**p) for p in raw_projects]
            except HTTPException as e:
                # If token expired and refresh_token exists, attempt refresh
                if e.status_code == 401 and user_token.refresh_token:
                    try:
                        refreshed = jira_service.refresh_access_token(user_token.refresh_token)
                        user_token.access_token = refreshed.get("access_token")
                        if refreshed.get("refresh_token"):
                            user_token.refresh_token = refreshed.get("refresh_token")
                        db.commit()
                        raw_projects = jira_service.fetch_jira_projects(user_token.access_token, user_token.cloud_id)
                        available_projects = [schemas.JiraProjectOption(**p) for p in raw_projects]
                    except Exception as refresh_err:
                        print(f"Failed to refresh Atlassian token: {refresh_err}")
                else:
                    print(f"Could not load Jira projects with user token: {e.detail}")
            except Exception as e:
                print(f"Error fetching Jira projects for status: {e}")

    # Fallback to env-configured basic auth projects if available and none loaded yet
    if not available_projects:
        basic_projects = jira_service.fetch_jira_projects_basic_fallback()
        if basic_projects:
            available_projects = [schemas.JiraProjectOption(**p) for p in basic_projects]
            if not is_authenticated:
                is_authenticated = True
                jira_user = os.getenv("JIRA_USER_EMAIL", "Jira Service")

    connection_response = None
    if conn:
        connection_response = schemas.JiraConnectionResponse(
            id=conn.id,
            project_id=conn.project_id,
            jira_project_key=conn.jira_project_key,
            jira_project_name=conn.jira_project_name,
            jira_project_id=conn.jira_project_id,
            jira_cloud_id=conn.jira_cloud_id,
            site_url=conn.site_url,
            connected_at=getattr(conn, "connected_at", None) or getattr(conn, "created_at", None),
            created_at=getattr(conn, "created_at", None),
            updated_at=getattr(conn, "updated_at", None)
        )

    return schemas.JiraStatusResponse(
        authenticated=is_authenticated,
        connected=is_connected,
        jira_user=jira_user,
        connection=connection_response,
        available_projects=available_projects
    )


@router.get("/projects/{projectId}/timeline", response_model=schemas.JiraTimelineResponse)
def get_jira_timeline(
    projectId: str,
    jiraProjectKey: Optional[str] = Query(None),
    x_user_email: Optional[str] = Header(None, alias="X-User-Email"),
    db: Session = Depends(get_db),
):
    conn = db.query(JiraConnection).filter(JiraConnection.project_id == projectId).first()
    if jiraProjectKey:
        wanted = jiraProjectKey.strip().upper()
        conn = next(
            (candidate for candidate in [conn] + db.query(JiraRepositoryConnection).filter(
                JiraRepositoryConnection.project_id == projectId
            ).all() if candidate and candidate.jira_project_key.strip().upper() == wanted),
            None,
        )
    if not conn:
        return schemas.JiraTimelineResponse(
            connected=False,
            message="Connect a Jira project in Overview to load the timeline.",
        )
    user_token = db.query(JiraUserToken).filter(JiraUserToken.user_email == x_user_email).first() if x_user_email else None
    if not user_token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Authenticate Jira before loading the timeline.")
    cloud_id = conn.jira_cloud_id or user_token.cloud_id
    if not cloud_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The Jira connection is missing its cloud site. Reconnect Jira.")
    try:
        result = jira_service.fetch_jira_timeline_issues(
            user_token.access_token,
            cloud_id,
            conn.jira_project_key,
            conn.site_url or user_token.site_url,
        )
    except HTTPException as exc:
        if exc.status_code == 401 and user_token.refresh_token:
            refreshed = jira_service.refresh_access_token(user_token.refresh_token)
            user_token.access_token = refreshed.get("access_token", user_token.access_token)
            if refreshed.get("refresh_token"):
                user_token.refresh_token = refreshed.get("refresh_token")
            db.commit()
            result = jira_service.fetch_jira_timeline_issues(
                user_token.access_token,
                cloud_id,
                conn.jira_project_key,
                conn.site_url or user_token.site_url,
            )
        else:
            raise
    message = None
    if "due dates" in result.get("missing_fields", []):
        message = "Due dates are not set for some issues in Jira. The timeline displays real Jira dates without inventing missing dates."
    return schemas.JiraTimelineResponse(
        connected=True,
        jira_project_key=conn.jira_project_key,
        jira_project_name=conn.jira_project_name,
        jira_project_id=conn.jira_project_id,
        issues=result["issues"],
        missing_fields=result["missing_fields"],
        message=message,
    )



@router.get("/projects/{projectId}/github-correlation")
def get_github_correlation(
    projectId: str,
    jiraProjectKey: Optional[str] = Query(None),
    x_user_email: Optional[str] = Header(None, alias="X-User-Email"),
    db: Session = Depends(get_db),
):
    """
    Returns GitHub evidence (commits, PRs, issues) correlated to Jira keys found
    in cached GitHub telemetry for all project repositories.
    Never invents data — only returns real items from the existing analysis cache.
    """
    import repo_analyzer as _ra

    repos = db.query(DBRepository).filter(DBRepository.project_id == projectId).all()
    correlation: dict = {}
    repos_scanned: list = []
    jira_key_re = re.compile(r'\b([A-Z][A-Z0-9]{1,9}-\d+)\b')

    for repo in repos:
        cache = _ra.load_raw_cache(repo.id)
        if not cache:
            continue
        repos_scanned.append(repo.name)

        # Commits
        for commit in cache.get("commits", []) or []:
            msg = (commit.get("message") or "").strip()
            if not msg:
                continue
            for key in set(jira_key_re.findall(msg)):
                correlation.setdefault(key, [])
                if len(correlation[key]) < 15:
                    sha = str(commit.get("sha") or "")
                    correlation[key].append({
                        "type": "commit",
                        "repo": repo.name,
                        "title": msg.split("\n")[0][:120],
                        "author": commit.get("author"),
                        "date": commit.get("date"),
                        "url": f"https://github.com/{repo.owner}/{repo.name}/commit/{sha}" if sha else None,
                        "sha": sha[:7] if sha else None,
                    })

        # Pull Requests
        for pr in cache.get("pull_requests", []) or []:
            title = (pr.get("title") or "").strip()
            if not title:
                continue
            for key in set(jira_key_re.findall(title)):
                correlation.setdefault(key, [])
                if len(correlation[key]) < 15:
                    correlation[key].append({
                        "type": "pr",
                        "repo": repo.name,
                        "title": title[:120],
                        "author": pr.get("author"),
                        "date": pr.get("created_at"),
                        "url": pr.get("html_url") or pr.get("url"),
                        "state": pr.get("state"),
                        "is_merged": bool(pr.get("is_merged", False)),
                    })

        # GitHub Issues
        for gh_issue in cache.get("issues", []) or []:
            title = (gh_issue.get("title") or "").strip()
            if not title:
                continue
            labels = gh_issue.get("labels") or []
            is_bug = any("bug" in str(lbl).lower() for lbl in labels)
            for key in set(jira_key_re.findall(title)):
                correlation.setdefault(key, [])
                if len(correlation[key]) < 15:
                    correlation[key].append({
                        "type": "github_issue",
                        "repo": repo.name,
                        "title": title[:120],
                        "state": gh_issue.get("state"),
                        "is_bug": is_bug,
                        "labels": [str(l) for l in labels[:5]],
                    })

    return {"correlation": correlation, "repos_scanned": repos_scanned}


@router.get("/projects", response_model=List[schemas.JiraProjectOption])
def list_available_jira_projects(
    user_email: Optional[str] = Query(None),
    x_user_email: Optional[str] = Header(None, alias="X-User-Email"),
    db: Session = Depends(get_db)
):
    """
    Returns available Jira projects for the authenticated user.
    """
    email = user_email or x_user_email
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User email is required to fetch Jira projects."
        )

    user_token = db.query(JiraUserToken).filter(JiraUserToken.user_email == email).first()
    if not user_token or not user_token.cloud_id:
        # Check basic auth fallback
        basic_projects = jira_service.fetch_jira_projects_basic_fallback()
        if basic_projects:
            return [schemas.JiraProjectOption(**p) for p in basic_projects]
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No connected Jira account found for this user. Please authenticate Jira first."
        )

    try:
        raw_projects = jira_service.fetch_jira_projects(user_token.access_token, user_token.cloud_id)
        return [schemas.JiraProjectOption(**p) for p in raw_projects]
    except HTTPException as e:
        if e.status_code == 401 and user_token.refresh_token:
            refreshed = jira_service.refresh_access_token(user_token.refresh_token)
            user_token.access_token = refreshed.get("access_token")
            if refreshed.get("refresh_token"):
                user_token.refresh_token = refreshed.get("refresh_token")
            db.commit()
            raw_projects = jira_service.fetch_jira_projects(user_token.access_token, user_token.cloud_id)
            return [schemas.JiraProjectOption(**p) for p in raw_projects]
        raise


@router.post("/projects/{projectId}/connect", response_model=schemas.JiraConnectionResponse)
def connect_jira_project(
    projectId: str,
    connect_in: schemas.JiraConnectRequest,
    x_user_email: Optional[str] = Header(None, alias="X-User-Email"),
    db: Session = Depends(get_db)
):
    """
    Saves the selected Jira project connection to the SEER project.
    """
    project = db.query(DBProject).filter(DBProject.id == projectId).first()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    # Resolve site_url and cloud_id from user token if not supplied
    site_url = connect_in.site_url
    cloud_id = connect_in.jira_cloud_id
    user_token = None
    if x_user_email:
        user_token = db.query(JiraUserToken).filter(JiraUserToken.user_email == x_user_email).first()
        if user_token:
            if not site_url and user_token.site_url:
                site_url = user_token.site_url
            if not cloud_id and user_token.cloud_id:
                cloud_id = user_token.cloud_id

    if user_token and cloud_id:
        available_projects = jira_service.fetch_jira_projects(user_token.access_token, cloud_id)
        selected_project = next(
            (
                project for project in available_projects
                if str(project.get("id") or "") == str(connect_in.jira_project_id or "")
                or str(project.get("key") or "").upper() == connect_in.jira_project_key.strip().upper()
            ),
            None,
        )
        if not selected_project:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Jira project '{connect_in.jira_project_key}' is not accessible to the connected Jira account. "
                    "Select a project from the available Jira project list or grant this account access."
                ),
            )
        connect_in.jira_project_key = selected_project["key"]
        connect_in.jira_project_name = selected_project["name"]
        connect_in.jira_project_id = selected_project["id"]

    # Check if a connection already exists for this project
    existing = db.query(JiraConnection).filter(JiraConnection.project_id == projectId).first()
    if existing:
        existing.jira_project_key = connect_in.jira_project_key.strip()
        existing.jira_project_name = connect_in.jira_project_name.strip()
        existing.jira_project_id = connect_in.jira_project_id
        existing.jira_cloud_id = cloud_id
        existing.site_url = site_url
        existing.connected_by_email = x_user_email
        db_conn = existing
    else:
        import uuid
        db_conn = JiraConnection(
            id=str(uuid.uuid4()),
            project_id=projectId,
            jira_project_key=connect_in.jira_project_key.strip(),
            jira_project_name=connect_in.jira_project_name.strip(),
            jira_project_id=connect_in.jira_project_id,
            jira_cloud_id=cloud_id,
            site_url=site_url,
            connected_by_email=x_user_email
        )
        db.add(db_conn)

    from datetime import datetime
    now = datetime.utcnow()
    project.updated_at = now
    if not existing:
        db_conn.connected_at = now
        db_conn.created_at = now
    db_conn.updated_at = now

    db.commit()
    db.refresh(db_conn)

    return schemas.JiraConnectionResponse(
        id=db_conn.id,
        project_id=db_conn.project_id,
        jira_project_key=db_conn.jira_project_key,
        jira_project_name=db_conn.jira_project_name,
        jira_project_id=db_conn.jira_project_id,
        jira_cloud_id=db_conn.jira_cloud_id,
        site_url=db_conn.site_url,
        connected_at=getattr(db_conn, "connected_at", None) or getattr(db_conn, "created_at", None),
        created_at=getattr(db_conn, "created_at", None),
        updated_at=getattr(db_conn, "updated_at", None)
    )


@router.post("/projects/{projectId}/disconnect")
def disconnect_jira_project(
    projectId: str,
    db: Session = Depends(get_db)
):
    """
    Disconnects the Jira project from the SEER project.
    """
    conn = db.query(JiraConnection).filter(JiraConnection.project_id == projectId).first()
    if conn:
        db.delete(conn)
        db.commit()

    return {"status": "disconnected"}


@router.get("/projects/{projectId}/repositories/{repositoryId}/status", response_model=schemas.JiraRepositoryConnectionStatus)
def get_repository_jira_status(
    projectId: str,
    repositoryId: str,
    db: Session = Depends(get_db),
):
    repository = _repository_for_project(projectId, repositoryId, db)
    mapping = db.query(JiraRepositoryConnection).filter(
        JiraRepositoryConnection.repository_id == repositoryId,
    ).first()
    project_connection = db.query(JiraConnection).filter(JiraConnection.project_id == projectId).first()
    effective = mapping or project_connection
    return schemas.JiraRepositoryConnectionStatus(
        repository_id=repositoryId,
        repository_name=repository.name,
        connection=_jira_connection_response(mapping, repositoryId) if mapping else None,
        effective_connection=_jira_connection_response(effective) if effective else None,
        uses_project_fallback=bool(project_connection and not mapping),
    )


@router.post("/projects/{projectId}/repositories/{repositoryId}/connect", response_model=schemas.JiraRepositoryConnectionResponse)
def connect_repository_jira_project(
    projectId: str,
    repositoryId: str,
    connect_in: schemas.JiraConnectRequest,
    x_user_email: Optional[str] = Header(None, alias="X-User-Email"),
    db: Session = Depends(get_db),
):
    _repository_for_project(projectId, repositoryId, db)
    site_url = connect_in.site_url
    cloud_id = connect_in.jira_cloud_id
    if x_user_email:
        user_token = db.query(JiraUserToken).filter(JiraUserToken.user_email == x_user_email).first()
        if user_token:
            site_url = site_url or user_token.site_url
            cloud_id = cloud_id or user_token.cloud_id

            available_projects = jira_service.fetch_jira_projects(user_token.access_token, cloud_id)
            selected_project = next(
                (
                    project for project in available_projects
                    if str(project.get("id") or "") == str(connect_in.jira_project_id or "")
                    or str(project.get("key") or "").upper() == connect_in.jira_project_key.strip().upper()
                ),
                None,
            )
            if not selected_project:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Jira project '{connect_in.jira_project_key}' is not accessible to the connected Jira account. "
                        "Select an available Jira project or create it in Jira first."
                    ),
                )
            connect_in.jira_project_key = selected_project["key"]
            connect_in.jira_project_name = selected_project["name"]
            connect_in.jira_project_id = selected_project["id"]

    mapping = db.query(JiraRepositoryConnection).filter(
        JiraRepositoryConnection.repository_id == repositoryId,
    ).first()
    if mapping:
        mapping.jira_project_key = connect_in.jira_project_key.strip()
        mapping.jira_project_name = connect_in.jira_project_name.strip()
        mapping.jira_project_id = connect_in.jira_project_id
        mapping.jira_cloud_id = cloud_id
        mapping.site_url = site_url
        mapping.connected_by_email = x_user_email
        mapping.updated_at = datetime.utcnow()
    else:
        mapping = JiraRepositoryConnection(
            id=str(uuid.uuid4()),
            project_id=projectId,
            repository_id=repositoryId,
            jira_project_key=connect_in.jira_project_key.strip(),
            jira_project_name=connect_in.jira_project_name.strip(),
            jira_project_id=connect_in.jira_project_id,
            jira_cloud_id=cloud_id,
            site_url=site_url,
            connected_by_email=x_user_email,
        )
        db.add(mapping)
    db.commit()
    db.refresh(mapping)
    return _jira_connection_response(mapping, repositoryId)


@router.post("/projects/{projectId}/repositories/{repositoryId}/disconnect")
def disconnect_repository_jira_project(
    projectId: str,
    repositoryId: str,
    db: Session = Depends(get_db),
):
    _repository_for_project(projectId, repositoryId, db)
    mapping = db.query(JiraRepositoryConnection).filter(
        JiraRepositoryConnection.repository_id == repositoryId,
    ).first()
    if mapping:
        db.delete(mapping)
        db.commit()
    return {"status": "disconnected"}


@router.post("/disconnect")
def disconnect_user_jira_token(
    user_email: Optional[str] = Query(None),
    x_user_email: Optional[str] = Header(None, alias="X-User-Email"),
    db: Session = Depends(get_db)
):
    """
    Clears the user's Atlassian OAuth token from the database.
    """
    email = user_email or x_user_email
    if not email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User email required.")

    user_token = db.query(JiraUserToken).filter(JiraUserToken.user_email == email).first()
    if user_token:
        db.delete(user_token)
        db.commit()

    return {"status": "user_disconnected"}
