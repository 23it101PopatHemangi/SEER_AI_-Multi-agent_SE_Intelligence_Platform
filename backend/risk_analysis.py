import re
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

import jira_service
import repo_analyzer
import schemas
from database import (
    JiraConnection,
    JiraRepositoryConnection,
    JiraUserToken,
    JiraStoryDraft,
    SRSDocument,
    Project,
    Repository,
    get_db,
)

router = APIRouter(prefix="/api/projects", tags=["Risk Analysis"])


def _destination(project_id: str, key: Optional[str], db: Session):
    connections = []
    project_connection = db.query(JiraConnection).filter(JiraConnection.project_id == project_id).first()
    if project_connection:
        connections.append(project_connection)
    connections.extend(db.query(JiraRepositoryConnection).filter(JiraRepositoryConnection.project_id == project_id).all())
    if key:
        wanted = key.strip().upper()
        return next((item for item in connections if item.jira_project_key.strip().upper() == wanted), None)
    return project_connection


def _unfinished(status_name: Optional[str]) -> bool:
    return (status_name or "").strip().lower() not in {"done", "closed", "resolved", "complete", "completed"}


def _date(value: Optional[str]):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d").date()
        except Exception:
            return None


def _dt(value: Optional[str]):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@router.get("/{projectId}/risk", response_model=schemas.RiskAnalysisResponse)
def get_risk_analysis(
    projectId: str,
    jiraProjectKey: Optional[str] = Query(None),
    x_user_email: Optional[str] = Header(None, alias="X-User-Email"),
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == projectId).first()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    destination = _destination(projectId, jiraProjectKey, db)
    token = db.query(JiraUserToken).filter(JiraUserToken.user_email == x_user_email).first() if x_user_email else None
    jira_issues = []
    jira_message = None
    site_url = destination.site_url if destination else (token.site_url if token else None)

    if destination and token:
        cloud_id = destination.jira_cloud_id or token.cloud_id
        if cloud_id:
            try:
                jira_issues = jira_service.fetch_jira_timeline_issues(
                    token.access_token, cloud_id, destination.jira_project_key, destination.site_url or token.site_url
                )["issues"]
            except HTTPException as exc:
                if exc.status_code == status.HTTP_401_UNAUTHORIZED and token.refresh_token:
                    refreshed = jira_service.refresh_access_token(token.refresh_token)
                    token.access_token = refreshed.get("access_token", token.access_token)
                    if refreshed.get("refresh_token"):
                        token.refresh_token = refreshed["refresh_token"]
                    db.commit()
                    try:
                        jira_issues = jira_service.fetch_jira_timeline_issues(
                            token.access_token, cloud_id, destination.jira_project_key, destination.site_url or token.site_url
                        )["issues"]
                    except Exception as e2:
                        jira_message = str(getattr(e2, "detail", e2))
                else:
                    jira_message = str(exc.detail)
            except Exception as exc:
                jira_message = str(getattr(exc, "detail", exc))
        else:
            jira_message = "The selected Jira destination has no cloud site configured. Reconnect Jira."
    elif destination and not token:
        jira_message = "Authenticate Jira to load project risk data."

    now_utc = datetime.now(timezone.utc)
    today = now_utc.date()
    indicators: List[schemas.RiskIndicator] = []

    # Helper to construct Jira browse URL
    def _jira_url(key: str) -> Optional[str]:
        if site_url:
            return f"{site_url.rstrip('/')}/browse/{key}"
        return None

    def _is_missing_priority(p: Optional[str]) -> bool:
        if not p:
            return True
        return str(p).strip().lower() in {"", "unassigned", "none", "null", "not set", "priority not set"}

    def _is_high_priority(p: Optional[str]) -> bool:
        if not p:
            return False
        return str(p).strip().lower() in {"high", "highest", "critical", "blocker"}

    def _make_affected(issue_list: List[dict]) -> List[schemas.RiskAffectedIssue]:
        return [
            schemas.RiskAffectedIssue(
                key=iss.get("key", ""),
                summary=iss.get("summary"),
                # Fetch actual Jira priority: Highest, High, Medium, Low, Lowest. Never default missing priority to High.
                priority=None if _is_missing_priority(iss.get("priority")) else str(iss.get("priority")).strip(),
                status=iss.get("status"),
                jira_url=iss.get("jira_url") or _jira_url(iss.get("key", ""))
            )
            for iss in issue_list
        ]

    # 1. Jira Issue Metrics & Rule-Based Risk Evaluation
    unfinished = [issue for issue in jira_issues if _unfinished(issue.get("status"))]

    # Overdue issues: Unfinished issues with a due date strictly prior to today
    overdue = [issue for issue in unfinished if issue.get("due_date") and (_date(issue.get("due_date")) or today) < today]
    if overdue:
        ev_items = [
            schemas.RiskEvidenceItem(
                label=f"{issue['key']}: {issue.get('summary', '')} (due {issue['due_date']}, status: {issue.get('status') or 'Open'})",
                url=issue.get("jira_url") or _jira_url(issue["key"]),
                source_type="jira"
            )
            for issue in overdue[:10]
        ]
        indicators.append(schemas.RiskIndicator(
            severity="high",
            category="schedule",
            title="Overdue Jira work",
            evidence=[item.label for item in ev_items],
            evidence_items=ev_items,
            reason=f"{len(overdue)} unfinished issue(s) have passed their scheduled Jira due date.",
            suggested_action="Review ownership and scope for overdue issues, then update due dates or re-prioritize in Jira.",
            affected_issue_keys=[issue["key"] for issue in overdue[:15]],
            affected_issues=_make_affected(overdue[:15]),
            source_origin="Jira",
            source_api="GET /rest/api/3/search (JQL: project = KEY AND statusCategory != Done)",
            calculation_logic=f"due_date < {today.isoformat()} AND status != Done/Closed/Resolved",
        ))

    # Explicitly Blocked Jira work (status contains 'block')
    blocked = [issue for issue in unfinished if "block" in (issue.get("status") or "").lower()]
    if blocked:
        ev_items = [
            schemas.RiskEvidenceItem(
                label=f"{issue['key']}: {issue.get('summary', '')} [{issue.get('status')}]",
                url=issue.get("jira_url") or _jira_url(issue["key"]),
                source_type="jira"
            )
            for issue in blocked[:10]
        ]
        indicators.append(schemas.RiskIndicator(
            severity="high",
            category="delivery",
            title="Blocked Jira work",
            evidence=[item.label for item in ev_items],
            evidence_items=ev_items,
            reason="Jira reports active unfinished issues in an explicit blocked state.",
            suggested_action="Assign an owner to clear the impediment and record blocking dependencies in Jira.",
            affected_issue_keys=[issue["key"] for issue in blocked[:15]],
            affected_issues=_make_affected(blocked[:15]),
            source_origin="Jira",
            source_api="GET /rest/api/3/search",
            calculation_logic="LOWER(status.name) CONTAINS 'block'",
        ))

    # Timeline Dependency Blocks: Unfinished issue depends on another unfinished issue
    unfinished_keys = {issue["key"] for issue in unfinished}
    dependency_blocked = []
    dep_blocked_issues = []
    for issue in unfinished:
        deps = issue.get("dependencies") or []
        for d in deps:
            rel = (d.get("relationship") or "").lower()
            dep_key = d.get("issue_key")
            if any(term in rel for term in ["blocked", "depends", "is blocked by"]) and dep_key in unfinished_keys:
                dependency_blocked.append((issue["key"], dep_key, rel, issue.get("summary", "")))
                dep_blocked_issues.append(issue)
                break

    if dependency_blocked:
        ev_items = [
            schemas.RiskEvidenceItem(
                label=f"{child} ({sm}) is blocked by incomplete {parent} ({rel})",
                url=_jira_url(child),
                source_type="jira"
            )
            for child, parent, rel, sm in dependency_blocked[:10]
        ]
        indicators.append(schemas.RiskIndicator(
            severity="high",
            category="dependency",
            title="Timeline dependency bottlenecks",
            evidence=[item.label for item in ev_items],
            evidence_items=ev_items,
            reason=f"{len(dependency_blocked)} issue(s) have unresolved predecessor dependencies in this timeline.",
            suggested_action="Prioritize unblocking predecessor issues first to prevent cascading schedule slips.",
            affected_issue_keys=[child for child, _, _, _ in dependency_blocked[:15]],
            affected_issues=_make_affected(dep_blocked_issues[:15]),
            source_origin="Jira",
            source_api="GET /rest/api/3/search (issuelinks field)",
            calculation_logic="issue.issuelinks links to unfinished predecessor issue",
        ))

    # High-Priority Unfinished Jira Work
    # Strictly separates Jira Priority (Highest, High, Medium, Low, Lowest, Unassigned) from SEER AI Risk Severity.
    # Missing/Unassigned priority is NEVER defaulted to High and NEVER included in high-priority counts.
    high_priority_unfinished = [
        issue for issue in unfinished
        if _is_high_priority(issue.get("priority"))
    ]
    if high_priority_unfinished:
        ev_items = [
            schemas.RiskEvidenceItem(
                label=f"{issue['key']} [{issue.get('priority')}]: {issue.get('summary', '')}",
                url=issue.get("jira_url") or _jira_url(issue["key"]),
                source_type="jira"
            )
            for issue in high_priority_unfinished[:10]
        ]
        indicators.append(schemas.RiskIndicator(
            severity="high" if len(high_priority_unfinished) >= 3 else "medium",
            category="priority",
            title="High-priority unfinished Jira issues",
            evidence=[item.label for item in ev_items],
            evidence_items=ev_items,
            reason=(
                f"{len(high_priority_unfinished)} unfinished issue(s) have an active Jira priority of "
                "Highest, High, Critical, or Blocker. Issues with lower priority (Medium, Low, Lowest) or "
                "unassigned priority are excluded and evaluated separately."
            ),
            suggested_action=(
                "Ensure active Jira issues with High or Highest priority have assigned owners and realistic sprint target dates."
            ),
            affected_issue_keys=[issue["key"] for issue in high_priority_unfinished[:15]],
            affected_issues=_make_affected(high_priority_unfinished[:15]),
            source_origin="Jira",
            source_api="GET /rest/api/3/search (fields: priority)",
            calculation_logic="priority.name IN ('Highest', 'High', 'Critical', 'Blocker') AND status NOT IN ('Done', 'Closed', 'Resolved')",
        ))

    # Data-Quality Warning: Unfinished issues with missing or unassigned Jira priority.
    # Never assumed to be High risk; classified as a low-severity hygiene finding.
    priority_not_set = [
        issue for issue in unfinished
        if _is_missing_priority(issue.get("priority"))
    ]
    if priority_not_set:
        ev_items_pns = [
            schemas.RiskEvidenceItem(
                label=f"{issue['key']} [Priority not set]: {issue.get('summary', '')}",
                url=issue.get("jira_url") or _jira_url(issue["key"]),
                source_type="jira"
            )
            for issue in priority_not_set[:10]
        ]
        indicators.append(schemas.RiskIndicator(
            severity="low",
            category="hygiene",
            title="Unfinished issues missing Jira priority",
            evidence=[item.label for item in ev_items_pns],
            evidence_items=ev_items_pns,
            reason=(
                f"{len(priority_not_set)} unfinished issue(s) have no Jira priority set (or are unassigned). "
                "This is a data-quality gap, not an urgent delivery risk. These issues are excluded from "
                "high-priority risk counts and are never assumed to be high risk."
            ),
            suggested_action=(
                "Open each issue in Jira and assign an explicit priority "
                "(Highest / High / Medium / Low / Lowest) "
                "so that delivery risk analysis, sprint planning, and backlog triage accurately reflect team priorities."
            ),
            affected_issue_keys=[issue["key"] for issue in priority_not_set[:15]],
            affected_issues=_make_affected(priority_not_set[:15]),
            source_origin="Jira",
            source_api="GET /rest/api/3/search (fields: priority)",
            calculation_logic="priority IS NULL OR priority IN ('Unassigned', 'None', '') AND status != Done",
        ))

    # Stale Unfinished Tasks: No updates for 14+ days
    stale_tasks = []
    for issue in unfinished:
        up_str = issue.get("updated_at")
        if up_str:
            d = _dt(up_str)
            if d and (now_utc - d).days >= 14:
                stale_tasks.append((issue, (now_utc - d).days))
    if stale_tasks:
        stale_tasks.sort(key=lambda x: x[1], reverse=True)
        ev_items = [
            schemas.RiskEvidenceItem(
                label=f"{iss['key']}: {iss.get('summary', '')} (inactive for {days} days, updated {iss.get('updated_at', '')[:10]})",
                url=iss.get("jira_url") or _jira_url(iss["key"]),
                source_type="jira"
            )
            for iss, days in stale_tasks[:10]
        ]
        indicators.append(schemas.RiskIndicator(
            severity="medium",
            category="hygiene",
            title="Stale in-progress work (inactive >14 days)",
            evidence=[item.label for item in ev_items],
            evidence_items=ev_items,
            reason=f"{len(stale_tasks)} unfinished issue(s) have not had any activity or status updates in over two weeks.",
            suggested_action="Verify if these items are abandoned, blocked, or already completed without Jira status sync.",
            affected_issue_keys=[iss["key"] for iss, _ in stale_tasks[:15]],
            affected_issues=_make_affected([iss for iss, _ in stale_tasks[:15]]),
            source_origin="Jira",
            source_api="GET /rest/api/3/search (updated field)",
            calculation_logic="now_utc - datetime.fromisoformat(issue.updated) >= 14 days",
        ))

    # Missing Dates: In active/future sprint or in progress, but missing start or due date
    missing_schedule = [
        issue for issue in unfinished
        if (issue.get("sprint") or "progress" in (issue.get("status") or "").lower())
        and (not issue.get("due_date") or not issue.get("start_date"))
    ]
    if missing_schedule:
        ev_items = [
            schemas.RiskEvidenceItem(
                label=f"{issue['key']}: {issue.get('summary', '')} (Sprint: {issue.get('sprint') or 'In-progress'})",
                url=issue.get("jira_url") or _jira_url(issue["key"]),
                source_type="jira"
            )
            for issue in missing_schedule[:10]
        ]
        indicators.append(schemas.RiskIndicator(
            severity="low",
            category="planning",
            title="Committed sprint work missing start or due dates",
            evidence=[item.label for item in ev_items],
            evidence_items=ev_items,
            reason="Issues committed to sprints or in development lack explicit start/due dates for timeline projection.",
            suggested_action="Set target start and completion dates in Jira so the Gantt calendar can plan capacity.",
            affected_issue_keys=[issue["key"] for issue in missing_schedule[:15]],
            affected_issues=_make_affected(missing_schedule[:15]),
            source_origin="Jira",
            source_api="GET /rest/api/3/search (customfield_10015, duedate)",
            calculation_logic="issue.sprint != null AND (due_date == null OR start_date == null)",
        ))

    # 2. GitHub Telemetry & CI / Risky PR Metrics
    repositories = db.query(Repository).filter(Repository.project_id == projectId).all()
    open_github = 0
    recent_commits = 0
    stale_open_prs = []
    failed_ci_evidence = []
    github_bug_issues = []

    for repository in repositories:
        cache = repo_analyzer.load_raw_cache(repository.id) or {}
        repo_issues = cache.get("issues") or []
        for gi in repo_issues:
            if str(gi.get("state", "")).lower() == "open":
                open_github += 1
                labels = [str(l).lower() for l in gi.get("labels") or []]
                title = gi.get("title", "")
                if any("bug" in l or "error" in l or "defect" in l for l in labels) or any(k in title.lower() for k in ["bug", "fail", "broken", "crash"]):
                    url = f"https://github.com/{repository.owner}/{repository.name}/issues/{gi.get('number')}"
                    github_bug_issues.append(schemas.RiskEvidenceItem(
                        label=f"{repository.name} #{gi.get('number')}: {title}",
                        url=url,
                        source_type="github"
                    ))

        commits = cache.get("commits") or []
        recent_commits += len(commits)
        
        # Check commits for CI failure / reverts / breakages
        for cm in commits:
            msg = (cm.get("message") or "").strip()
            if any(k in msg.lower() for k in ["ci failed", "build broken", "revert \"", "broken build", "fix(ci):"]):
                sha = str(cm.get("sha") or "")[:7]
                url = f"https://github.com/{repository.owner}/{repository.name}/commit/{cm.get('sha')}" if cm.get("sha") else None
                failed_ci_evidence.append(schemas.RiskEvidenceItem(
                    label=f"{repository.name} commit {sha}: {msg.splitlines()[0][:100]}",
                    url=url,
                    source_type="github"
                ))

        # Check PRs for stale open PRs
        prs = cache.get("pull_requests") or []
        for pr in prs:
            if str(pr.get("state", "")).lower() == "open":
                created_str = pr.get("created_at")
                if created_str:
                    c_dt = _dt(created_str)
                    if c_dt and (now_utc - c_dt).days >= 14:
                        url = pr.get("html_url") or f"https://github.com/{repository.owner}/{repository.name}/pull/{pr.get('number')}"
                        stale_open_prs.append(schemas.RiskEvidenceItem(
                            label=f"{repository.name} PR #{pr.get('number')}: {pr.get('title', '')} (open for {(now_utc - c_dt).days} days)",
                            url=url,
                            source_type="github"
                        ))

    github_activity = schemas.RiskGitHubActivity(
        connected=bool(repositories),
        repositories=len(repositories),
        open_issues=open_github,
        recent_commits=recent_commits,
        message=None if repositories else "No GitHub repositories are connected to this SEER AI project.",
    )

    if github_bug_issues:
        indicators.append(schemas.RiskIndicator(
            severity="high" if len(github_bug_issues) >= 3 else "medium",
            category="github",
            title="Open GitHub bug reports and defects",
            evidence=[item.label for item in github_bug_issues[:8]],
            evidence_items=github_bug_issues[:8],
            reason=f"{len(github_bug_issues)} open defect/bug issue(s) detected in connected code repositories.",
            suggested_action="Review and link GitHub defect reports to Jira stories to trace bug fixes in sprint planning.",
            affected_issue_keys=[],
            source_origin="GitHub",
            source_api="GET /repos/{owner}/{repo}/issues (state=open)",
            calculation_logic="issue.state == 'open' AND (labels match bug/error/defect OR title contains bug/fail)",
        ))

    if stale_open_prs:
        indicators.append(schemas.RiskIndicator(
            severity="medium",
            category="github",
            title="Stale open Pull Requests (>14 days)",
            evidence=[item.label for item in stale_open_prs[:8]],
            evidence_items=stale_open_prs[:8],
            reason=f"{len(stale_open_prs)} open pull request(s) have remained unmerged for over two weeks.",
            suggested_action="Review pull requests for merge conflicts, review blockers, or abandoned code.",
            affected_issue_keys=[],
            source_origin="GitHub",
            source_api="GET /repos/{owner}/{repo}/pulls (state=open)",
            calculation_logic="pr.state == 'open' AND (now_utc - pr.created_at) >= 14 days",
        ))

    if failed_ci_evidence:
        indicators.append(schemas.RiskIndicator(
            severity="high",
            category="ci_cd",
            title="CI/CD workflow & build breakages detected",
            evidence=[item.label for item in failed_ci_evidence[:6]],
            evidence_items=failed_ci_evidence[:6],
            reason="Recent commit history contains explicit CI fixes, build failure resolutions, or reverts.",
            suggested_action="Verify pipeline health and run automated test suites before deploying current branch.",
            affected_issue_keys=[],
            source_origin="GitHub",
            source_api="GET /repos/{owner}/{repo}/commits",
            calculation_logic="commit.message matches CI failure, build broken, or revert patterns",
        ))

    # 3. SRS Requirements Coverage Risks
    srs_docs = db.query(SRSDocument).filter(SRSDocument.project_id == projectId).all()
    if srs_docs:
        srs_drafts = db.query(JiraStoryDraft).filter(
            JiraStoryDraft.project_id == projectId,
            JiraStoryDraft.source_type.in_(["srs_epic", "srs_story"]),
        ).all()
        unapproved_srs = [d for d in srs_drafts if d.status in ["draft", "rejected", "failed"]]
        
        if unapproved_srs:
            ev_items = [
                schemas.RiskEvidenceItem(
                    label=f"{d.title} [Status: {d.status}, Priority: {d.priority or 'Medium'}]",
                    url=None,
                    source_type="srs"
                )
                for d in unapproved_srs[:8]
            ]
            indicators.append(schemas.RiskIndicator(
                severity="medium",
                category="srs_coverage",
                title="SRS requirements pending Jira approval",
                evidence=[item.label for item in ev_items],
                evidence_items=ev_items,
                reason=f"{len(unapproved_srs)} requirement stories generated from uploaded SRS documents have not been approved to Jira.",
                suggested_action="Review and approve pending SRS requirements in the Story Drafts view to ensure full specification coverage.",
                affected_issue_keys=[],
                source_origin="SRS Documents",
                source_api="DB Table: srs_documents & jira_story_drafts (source_type=srs_epic/srs_story)",
                calculation_logic="srs_story_draft.status IN ('draft', 'failed', 'rejected')",
            ))
        elif not srs_drafts:
            ev_items = [
                schemas.RiskEvidenceItem(
                    label=f"{doc.filename} ({len(doc.extracted_text or '')} chars extracted)",
                    url=None,
                    source_type="srs"
                )
                for doc in srs_docs[:4]
            ]
            indicators.append(schemas.RiskIndicator(
                severity="low",
                category="srs_coverage",
                title="SRS documents uploaded but no Jira stories generated",
                evidence=[item.label for item in ev_items],
                evidence_items=ev_items,
                reason="Project SRS documents exist, but requirement extraction to Jira epics/stories has not been triggered.",
                suggested_action="Generate Jira stories or Epics from the uploaded SRS to track requirement delivery.",
                affected_issue_keys=[],
                source_origin="SRS Documents",
                source_api="DB Table: srs_documents (COUNT > 0) vs jira_story_drafts (COUNT == 0)",
                calculation_logic="srs_documents.count > 0 AND srs_story_drafts.count == 0",
            ))

    # 4. Architecture & Security Risks from Static Analysis
    arch_drafts = db.query(JiraStoryDraft).filter(
        JiraStoryDraft.project_id == projectId,
        JiraStoryDraft.status == "draft",
        JiraStoryDraft.source_type.in_(["key_component", "api_surface", "integration", "repository_analysis"]),
    ).all()
    
    auth_sec_unapproved = [
        d for d in arch_drafts
        if any(term in d.title.lower() for term in ["auth", "security", "token", "login", "encrypt", "payment", "middleware"])
    ]
    if auth_sec_unapproved:
        ev_items = [
            schemas.RiskEvidenceItem(
                label=f"{d.title} (Source: {d.source_type}, Component: {d.source_ref or 'code'})",
                url=None,
                source_type="architecture"
            )
            for d in auth_sec_unapproved[:8]
        ]
        indicators.append(schemas.RiskIndicator(
            severity="high",
            category="architecture",
            title="Uncovered authentication & security architecture components",
            evidence=[item.label for item in ev_items],
            evidence_items=ev_items,
            reason="Core authentication, security middleware, or token verification components discovered in code analysis are not yet tracked in Jira.",
            suggested_action="Approve these architecture stories into Jira to schedule implementation and security audit.",
            affected_issue_keys=[],
            source_origin="Architecture Analysis",
            source_api="AST / AST Telemetry Pipeline (repo_analyzer.py -> jira_story_drafts)",
            calculation_logic="draft.source_type IN ('key_component', 'api_surface') AND draft.status == 'draft' AND title MATCHES security keywords",
        ))

    failed_drafts = db.query(JiraStoryDraft).filter(
        JiraStoryDraft.project_id == projectId,
        JiraStoryDraft.status == "failed",
    ).all()
    if failed_drafts:
        ev_items = [
            schemas.RiskEvidenceItem(
                label=f"{d.title}: {d.creation_error or 'Unknown error'}",
                url=None,
                source_type="jira"
            )
            for d in failed_drafts[:6]
        ]
        indicators.append(schemas.RiskIndicator(
            severity="high",
            category="synchronization",
            title="Jira story synchronization failures",
            evidence=[item.label for item in ev_items],
            evidence_items=ev_items,
            reason=f"{len(failed_drafts)} story draft(s) failed during creation in Jira.",
            suggested_action="Check Jira project permissions and required fields, then retry approving failed drafts.",
            affected_issue_keys=[],
            source_origin="Jira Integration",
            source_api="POST /rest/api/3/issue",
            calculation_logic="jira_story_drafts.status == 'failed'",
        ))

    # Overall Health
    high_count = sum(1 for ind in indicators if ind.severity == "high")
    med_count = sum(1 for ind in indicators if ind.severity == "medium")
    
    if high_count > 0:
        health = "At risk"
    elif med_count > 0 or len(indicators) > 0:
        health = "Needs attention"
    else:
        health = "No risks detected"

    if not jira_issues and not repositories and not srs_docs:
        health = "Insufficient data"

    basis = (
        f"Rule-based assessment across {len(jira_issues)} Jira issues, {len(repositories)} repositories "
        f"({recent_commits} commits, {open_github} open issues), {len(srs_docs)} SRS documents, "
        f"and {len(indicators)} verified telemetry signals. Zero fabricated or mock data."
    )

    return schemas.RiskAnalysisResponse(
        project_id=projectId,
        jira_project_key=destination.jira_project_key if destination else None,
        jira_project_name=destination.jira_project_name if destination else None,
        jira_base_url=site_url,
        health=health,
        health_basis=basis,
        indicators=indicators,
        jira_issue_count=len(jira_issues),
        unfinished_issue_count=len(unfinished),
        overdue_issue_count=len(overdue),
        blocked_issue_count=len(blocked),
        github_activity=github_activity,
        prediction_status="Rule-based only. ML predictive scoring is disabled until sufficient validated historical delivery telemetry is acquired.",
        last_updated=now_utc.isoformat(),
        message=jira_message or ("Connect a Jira destination to load Jira risk indicators." if not destination else None),
    )
