import os
import requests
from typing import List, Dict, Optional, Tuple
from dotenv import load_dotenv
from fastapi import HTTPException, status

# Always load backend/.env first, then optional parent/.env
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_BACKEND_DIR, ".env"))
load_dotenv(os.path.join(_BACKEND_DIR, "..", ".env"))
load_dotenv()

ATLASSIAN_AUTH_URL = "https://auth.atlassian.com"
ATLASSIAN_API_URL = "https://api.atlassian.com"


def get_oauth_credentials() -> Tuple[str, str, str]:
    """
    Retrieves Jira OAuth credentials from environment variables.
    """
    client_id = os.getenv("JIRA_CLIENT_ID", "").strip()
    client_secret = os.getenv("JIRA_CLIENT_SECRET", "").strip()
    redirect_uri = os.getenv("JIRA_REDIRECT_URI", "http://localhost:8000/api/jira/callback").strip()
    return client_id, client_secret, redirect_uri


def check_oauth_credentials():
    """
    Validates that Jira OAuth client credentials are configured.
    """
    client_id, client_secret, _ = get_oauth_credentials()
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Jira Client credentials are not configured on the server. Please define JIRA_CLIENT_ID and JIRA_CLIENT_SECRET in backend/.env"
        )


def exchange_code_for_token(code: str, redirect_uri: str) -> dict:
    """
    Exchanges authorization code for Atlassian OAuth 2.0 access & refresh tokens.
    """
    client_id, client_secret, _ = get_oauth_credentials()
    token_url = f"{ATLASSIAN_AUTH_URL}/oauth/token"
    payload = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    try:
        res = requests.post(token_url, json=payload, headers=headers, timeout=12)
        res_data = res.json()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to communicate with Atlassian token service: {str(e)}"
        )

    if res.status_code != 200 or "access_token" not in res_data:
        error_msg = res_data.get("error_description") or res_data.get("error") or res_data.get("message") or "Unknown token exchange failure"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Atlassian token exchange failed: {error_msg}"
        )

    return res_data


def refresh_access_token(refresh_token: str) -> dict:
    """
    Refreshes an expired Atlassian OAuth access token using the refresh token.
    """
    client_id, client_secret, _ = get_oauth_credentials()
    token_url = f"{ATLASSIAN_AUTH_URL}/oauth/token"
    payload = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    res = requests.post(token_url, json=payload, headers=headers, timeout=12)
    if res.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Failed to refresh Jira access token. Please re-authenticate."
        )
    return res.json()


def get_accessible_resources(access_token: str) -> List[Dict]:
    """
    Retrieves the list of Atlassian cloud sites / resources accessible to the user token.
    """
    url = f"{ATLASSIAN_API_URL}/oauth/token/accessible-resources"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json"
    }

    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 401:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Atlassian access token has expired or is invalid."
            )
        if res.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to fetch accessible Jira sites (Status {res.status_code})"
            )
        return res.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Error connecting to Atlassian resources: {str(e)}"
        )


def fetch_jira_user(access_token: str) -> Dict:
    """
    Fetches the authenticated user profile from Atlassian /me endpoint.
    """
    url = f"{ATLASSIAN_API_URL}/me"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json"
    }

    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            return res.json()
        return {}
    except Exception as e:
        print(f"Warning: Failed to fetch Atlassian user profile: {e}")
        return {}


def fetch_jira_projects(access_token: str, cloud_id: str) -> List[Dict]:
    """
    Fetches projects for a specific Atlassian Cloud site using OAuth 2.0.
    """
    url = f"{ATLASSIAN_API_URL}/ex/jira/{cloud_id}/rest/api/3/project"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json"
    }

    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 401:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Jira access token expired. Reconnect Jira account."
            )
        if res.status_code != 200:
            # Try API v2 fallback if v3 fails
            v2_url = f"{ATLASSIAN_API_URL}/ex/jira/{cloud_id}/rest/api/2/project"
            res2 = requests.get(v2_url, headers=headers, timeout=10)
            if res2.status_code == 200:
                res = res2
            else:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Failed to fetch Jira projects (Status {res.status_code})"
                )

        raw_projects = res.json()
        projects = []
        for p in raw_projects:
            avatar_urls = p.get("avatarUrls", {})
            avatar_url = avatar_urls.get("48x48") or avatar_urls.get("32x32") or avatar_urls.get("16x16")
            projects.append({
                "id": str(p.get("id")),
                "key": p.get("key"),
                "name": p.get("name"),
                "project_type_key": p.get("projectTypeKey", "software"),
                "avatar_url": avatar_url
            })
        return projects
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Error fetching Jira projects: {str(e)}"
        )


def fetch_jira_projects_basic_fallback() -> List[Dict]:
    """
    Optional fallback: if JIRA_INSTANCE_URL and JIRA_API_TOKEN are configured in .env,
    fetches projects via Basic Auth directly.
    """
    instance_url = os.getenv("JIRA_INSTANCE_URL", "").strip().rstrip("/")
    api_token = os.getenv("JIRA_API_TOKEN", "").strip()
    user_email = os.getenv("JIRA_USER_EMAIL", "").strip()

    if not instance_url or not api_token or not user_email:
        return []

    try:
        url = f"{instance_url}/rest/api/3/project"
        res = requests.get(
            url,
            auth=(user_email, api_token),
            headers={"Accept": "application/json"},
            timeout=10
        )
        if res.status_code == 200:
            projects = []
            for p in res.json():
                avatar_urls = p.get("avatarUrls", {})
                avatar_url = avatar_urls.get("48x48") or avatar_urls.get("32x32")
                projects.append({
                    "id": str(p.get("id")),
                    "key": p.get("key"),
                    "name": p.get("name"),
                    "project_type_key": p.get("projectTypeKey", "software"),
                    "avatar_url": avatar_url
                })
            return projects
    except Exception as e:
        print(f"Basic Auth Jira project fetch fallback error: {e}")
    return []


def _text_to_adf(text: str) -> dict:
    paragraphs = [p.strip() for p in (text or "").split("\n") if p.strip()] or [""]
    content = []
    for para in paragraphs:
        content.append({
            "type": "paragraph",
            "content": [{"type": "text", "text": para}]
        })
    return {"type": "doc", "version": 1, "content": content}


def build_issue_description_adf(description: str, acceptance_criteria: List[str]) -> dict:
    content = _text_to_adf(description or "").get("content", [])
    if acceptance_criteria:
        content.append({
            "type": "heading",
            "attrs": {"level": 3},
            "content": [{"type": "text", "text": "Acceptance Criteria"}]
        })
        list_items = []
        for item in acceptance_criteria:
            list_items.append({
                "type": "listItem",
                "content": [{
                    "type": "paragraph",
                    "content": [{"type": "text", "text": item}]
                }]
            })
        content.append({"type": "bulletList", "content": list_items})
    return {"type": "doc", "version": 1, "content": content}


def search_issues_by_summary(
    access_token: str,
    cloud_id: str,
    project_key: str,
    summary: str,
    issue_type: Optional[str] = None,
) -> List[Dict]:
    """
    Returns matching Jira issues in the project with the same summary and issue type (duplicate check).
    Epic drafts are matched against existing Jira Epics, not confused with Stories.
    """
    safe_summary = summary.replace('"', " ")
    jql = f'project = "{project_key}" AND summary ~ "{safe_summary}" ORDER BY created DESC'
    url = f"{ATLASSIAN_API_URL}/ex/jira/{cloud_id}/rest/api/3/search/jql"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    try:
        res = requests.post(
            url,
            headers=headers,
            json={"jql": jql, "maxResults": 15, "fields": ["summary", "issuetype", "status"]},
            timeout=12,
        )
        if res.status_code != 200:
            print(f"Jira duplicate search failed ({res.status_code}): {res.text[:500]}")
            return []
        issues = res.json().get("issues", [])
        normalized = summary.strip().lower()
        matches = []
        for issue in issues:
            fields = issue.get("fields") or {}
            if issue_type:
                found_type = (fields.get("issuetype") or {}).get("name", "")
                if found_type and found_type.strip().lower() != issue_type.strip().lower():
                    continue
            if str(fields.get("summary") or "").strip().lower() == normalized:
                matches.append(issue)
        return matches
    except Exception as e:
        print(f"Jira duplicate search failed: {e}")
        return []


def batch_fetch_issue_statuses(
    access_token: str,
    cloud_id: str,
    issue_keys: List[str],
) -> Dict[str, str]:
    """
    Batch fetches the real Jira status name for a list of issue keys.
    """
    clean_keys = [k.strip() for k in issue_keys if k and k.strip()]
    if not clean_keys:
        return {}
    keys_clause = ", ".join(clean_keys[:50])
    jql = f"key in ({keys_clause})"
    url = f"{ATLASSIAN_API_URL}/ex/jira/{cloud_id}/rest/api/3/search/jql"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    try:
        res = requests.post(
            url,
            headers=headers,
            json={"jql": jql, "maxResults": 50, "fields": ["status"]},
            timeout=10,
        )
        if res.status_code != 200:
            return {}
        result = {}
        for issue in res.json().get("issues", []):
            k = issue.get("key")
            st = (issue.get("fields") or {}).get("status", {}).get("name")
            if k and st:
                result[k] = st
        return result
    except Exception as e:
        print(f"Batch Jira status fetch failed: {e}")
        return {}


def fetch_jira_timeline_issues(
    access_token: str,
    cloud_id: str,
    project_key: str,
    site_url: Optional[str] = None,
) -> Dict:
    """Fetch real Jira scheduling fields without inventing dates for incomplete issues."""
    base_url = f"{ATLASSIAN_API_URL}/ex/jira/{cloud_id}/rest/api/3"
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    try:
        field_response = requests.get(f"{base_url}/field", headers=headers, timeout=12)
        if field_response.status_code == 401:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Jira access token expired. Reconnect Jira account.")
        sprint_field = next(
            (field.get("id") for field in field_response.json() if str(field.get("name", "")).lower() == "sprint"),
            None,
        ) if field_response.ok else None

        fields = ["summary", "status", "issuetype", "priority", "created", "updated", "duedate", "startdate", "parent", "issuelinks", "assignee"]
        if sprint_field:
            fields.append(sprint_field)
        response = requests.post(
            f"{base_url}/search/jql",
            headers={**headers, "Content-Type": "application/json"},
            json={
                "jql": f'project = "{project_key}" ORDER BY created ASC',
                "fields": fields,
                "maxResults": 200,
            },
            timeout=15,
        )
        if response.status_code == 401:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Jira access token expired. Reconnect Jira account.")
        if not response.ok:
            try:
                body = response.json()
                detail = body.get("errorMessages") or body.get("message") or body.get("errors")
            except ValueError:
                detail = response.text[:500]
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Jira Timeline search failed ({response.status_code}): {detail or 'No response details returned.'}",
            )

        issues = []
        missing_due = 0
        missing_sprint = 0
        missing_dependencies = 0
        for raw_issue in response.json().get("issues", []):
            issue_fields = raw_issue.get("fields") or {}
            links = []
            for link in issue_fields.get("issuelinks") or []:
                linked = link.get("outwardIssue") or link.get("inwardIssue") or {}
                link_type = link.get("type") or {}
                relationship = link_type.get("outward") if link.get("outwardIssue") else link_type.get("inward")
                if linked.get("key"):
                    links.append({"issue_key": linked["key"], "relationship": relationship or "linked to"})

            raw_sprint = issue_fields.get(sprint_field) if sprint_field else None
            if isinstance(raw_sprint, list):
                raw_sprint = raw_sprint[-1] if raw_sprint else None
            sprint_name = None
            sprint_start_date = None
            sprint_end_date = None
            sprint_state = None
            if isinstance(raw_sprint, dict):
                sprint_name = raw_sprint.get("name")
                sprint_start_date = raw_sprint.get("startDate")
                sprint_end_date = raw_sprint.get("endDate")
                sprint_state = raw_sprint.get("state")
            elif raw_sprint and isinstance(raw_sprint, str):
                sprint_name = raw_sprint
            if sprint_name and str(sprint_name).startswith("com.atlassian.greenhopper.service.sprint.Sprint@"):
                sprint_name = None

            assignee_data = issue_fields.get("assignee") or {}
            assignee_name = assignee_data.get("displayName") or assignee_data.get("name")
            assignee_avatar = (assignee_data.get("avatarUrls") or {}).get("24x24") or \
                              (assignee_data.get("avatarUrls") or {}).get("48x48")

            if not issue_fields.get("duedate"):
                missing_due += 1
            if not sprint_name:
                missing_sprint += 1
            if not links:
                missing_dependencies += 1

            issue_key = raw_issue.get("key")
            raw_p = issue_fields.get("priority")
            p_val = raw_p.get("name") if isinstance(raw_p, dict) else (raw_p if isinstance(raw_p, str) else None)
            if p_val and str(p_val).strip().lower() in {"unassigned", "none", "null", "not set", "priority not set", ""}:
                p_val = "Unassigned"

            issues.append({
                "key": issue_key,
                "summary": issue_fields.get("summary") or issue_key,
                "status": (issue_fields.get("status") or {}).get("name"),
                "issue_type": (issue_fields.get("issuetype") or {}).get("name"),
                "priority": p_val,
                "created_at": issue_fields.get("created"),
                "updated_at": issue_fields.get("updated"),
                "due_date": issue_fields.get("duedate"),
                "start_date": issue_fields.get("startdate"),
                "parent_key": (issue_fields.get("parent") or {}).get("key"),
                "sprint": sprint_name,
                "sprint_start_date": sprint_start_date,
                "sprint_end_date": sprint_end_date,
                "sprint_state": sprint_state,
                "assignee_name": assignee_name,
                "assignee_avatar": assignee_avatar,
                "dependencies": links,
                "jira_url": f"{site_url.rstrip('/')}/browse/{issue_key}" if site_url and issue_key else None,
            })

        missing_fields = []
        if not issues:
            missing_fields.append("issues")
        if missing_due:
            missing_fields.append("due dates")
        return {"issues": issues, "missing_fields": missing_fields}
    except HTTPException:
        raise
    except requests.RequestException as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Error connecting to Jira: {exc}")


def create_jira_issue(
    access_token: str,
    cloud_id: str,
    project_field: Dict[str, str],
    summary: str,
    description: str,
    acceptance_criteria: Optional[List[str]] = None,
    priority: str = "Medium",
    issue_type: str = "Story",
    site_url: Optional[str] = None,
    parent_key: Optional[str] = None,
) -> Dict:
    """
    Creates a Jira Issue (Epic, Story, or Task) using the user's OAuth token.
    Epic creation does not depend on Scrum boards, Sprints, or Stories.
    """
    url = f"{ATLASSIAN_API_URL}/ex/jira/{cloud_id}/rest/api/3/issue"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    adf = build_issue_description_adf(description or "", acceptance_criteria or [])
    issue_types = ["Epic"] if issue_type == "Epic" else ["Story", "Task"]
    last_error = "Unknown Jira create failure"

    epic_name_field = None
    if issue_type == "Epic":
        try:
            f_res = requests.get(
                f"{ATLASSIAN_API_URL}/ex/jira/{cloud_id}/rest/api/3/field",
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
                timeout=8,
            )
            if f_res.status_code == 200:
                for f in f_res.json():
                    if str(f.get("name", "")).strip().lower() == "epic name":
                        epic_name_field = f.get("id")
                        break
        except Exception:
            pass

    for itype in issue_types:
        payloads = []
        base_field_data = {
            "project": project_field,
            "summary": summary[:255],
            "description": adf,
            "issuetype": {"name": itype},
            **({"parent": {"key": parent_key}} if parent_key and itype in {"Story", "Task"} else {}),
        }
        has_explicit_priority = bool(priority and str(priority).strip().lower() not in {"unassigned", "none", "null", "not set", "priority not set", ""})
        if itype == "Epic" and epic_name_field:
            if has_explicit_priority:
                payloads.append({
                    "fields": {
                        **base_field_data,
                        "priority": {"name": priority},
                        epic_name_field: summary[:255],
                    }
                })
            payloads.append({
                "fields": {
                    **base_field_data,
                    epic_name_field: summary[:255],
                }
            })
        if has_explicit_priority:
            payloads.append({
                "fields": {
                    **base_field_data,
                    "priority": {"name": priority},
                }
            })
        payloads.append({
            "fields": {
                **base_field_data,
            }
        })

        for payload in payloads:
            try:
                res = requests.post(url, json=payload, headers=headers, timeout=15)
            except Exception as e:
                last_error = str(e)
                continue
            if res.status_code in (200, 201):
                data = res.json()
                key = data.get("key")
                issue_id = str(data.get("id")) if data.get("id") is not None else None
                browse = f"{site_url.rstrip('/')}/browse/{key}" if site_url and key else None
                return {
                    "id": issue_id,
                    "key": key,
                    "url": browse or data.get("self")
                }
            try:
                err_json = res.json()
                last_error = err_json.get("errorMessages") or err_json.get("errors") or err_json.get("message") or res.text
            except Exception:
                last_error = res.text or f"HTTP {res.status_code}"

    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=f"Failed to create Jira issue: {last_error}"
    )
