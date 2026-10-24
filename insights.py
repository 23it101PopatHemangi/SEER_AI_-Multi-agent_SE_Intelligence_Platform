import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import jira_service
import repo_analyzer
import risk_analysis
from database import JiraConnection, JiraUserToken, Project, Repository, SRSDocument, get_db

router = APIRouter(prefix="/api/projects", tags=["AI Insights"])


class InsightRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=2000)


def _source(source_id: str, source_type: str, title: str, url: Optional[str], text: str) -> Dict[str, Any]:
    return {"id": source_id, "type": source_type, "title": title, "url": url, "text": text[:3000]}


def _retrieve(project_id: str, user_email: Optional[str], db: Session) -> Tuple[List[Dict[str, Any]], List[str], List[Dict[str, Any]], List[Any], Optional[str]]:
    sources: List[Dict[str, Any]] = []
    unavailable: List[str] = []
    jira_issues: List[Dict[str, Any]] = []
    risk_indicators: List[Any] = []
    site_url: Optional[str] = None

    # 1. Repositories & GitHub Telemetry
    repositories = db.query(Repository).filter(Repository.project_id == project_id).all()
    for repo in repositories:
        cache = repo_analyzer.load_raw_cache(repo.id)
        if not cache:
            unavailable.append(f"GitHub: {repo.owner}/{repo.name} has no local analysis cache")
            continue
        analysis = cache.get("analysis") or {}
        components = analysis.get("key_components") or []
        apis = analysis.get("api_surface") or []
        summary_text = f"Repository: {repo.owner}/{repo.name}\n"
        if components:
            summary_text += f"Key Components: {', '.join(components[:10])}\n"
        if apis:
            summary_text += f"APIs: {', '.join(str(a) for a in apis[:8])}\n"
        sources.append(_source(f"github-repo-{repo.id}", "github", f"GitHub: {repo.owner}/{repo.name}", repo.github_url, summary_text))

        # Open Bugs/Issues
        open_issues = [i for i in (cache.get("issues") or []) if str(i.get("state", "")).lower() == "open"]
        for issue in open_issues[:10]:
            number = issue.get("number")
            if number is not None:
                url = issue.get("html_url") or (f"{repo.github_url.rstrip('/')}/issues/{number}" if repo.github_url else None)
                sources.append(_source(f"github-issue-{repo.id}-{number}", "github", f"GitHub Issue #{number}: {issue.get('title', '')}", url, issue.get("body") or issue.get("title", "")))

        # Pull Requests
        for pull in (cache.get("pull_requests") or [])[:8]:
            number = pull.get("number")
            if number is not None:
                url = pull.get("html_url") or (f"{repo.github_url.rstrip('/')}/pull/{number}" if repo.github_url else None)
                sources.append(_source(f"github-pr-{repo.id}-{number}", "github", f"GitHub PR #{number}: {pull.get('title', '')}", url, f"Status: {pull.get('state')}, Created: {pull.get('created_at')}"))

    # 2. SRS Documents
    documents = db.query(SRSDocument).filter(SRSDocument.project_id == project_id).all()
    if documents:
        for document in documents:
            preview = (document.extracted_text or "")[:1500]
            sources.append(_source(f"srs-{document.id}", "srs", f"SRS: {document.filename}", None, preview))
    else:
        unavailable.append("SRS: No project documents uploaded")

    # 3. Jira Issues & Dependencies
    connection = db.query(JiraConnection).filter(JiraConnection.project_id == project_id).first()
    token = db.query(JiraUserToken).filter(JiraUserToken.user_email == user_email).first() if user_email else None
    effective_user_email = user_email
    if connection and token is None and connection.connected_by_email:
        connected_token = db.query(JiraUserToken).filter(JiraUserToken.user_email == connection.connected_by_email).first()
        if connected_token:
            token = connected_token
            effective_user_email = connection.connected_by_email

    if connection:
        site_url = connection.site_url or (token.site_url if token else None)

    if connection and token and (connection.jira_cloud_id or token.cloud_id):
        try:
            jira_issues = jira_service.fetch_jira_timeline_issues(
                token.access_token,
                connection.jira_cloud_id or token.cloud_id,
                connection.jira_project_key,
                connection.site_url or token.site_url,
            ).get("issues", [])
            for issue in jira_issues[:60]:
                key = issue.get("key", "")
                url = issue.get("jira_url") or (f"{site_url.rstrip('/')}/browse/{key}" if site_url and key else None)
                desc = f"Key: {key} | Status: {issue.get('status')} | Priority: {issue.get('priority')} | Summary: {issue.get('summary')}"
                if issue.get("due_date"):
                    desc += f" | Due: {issue.get('due_date')}"
                if issue.get("sprint"):
                    desc += f" | Sprint: {issue.get('sprint')}"
                sources.append(_source(f"jira-{key}", "jira", f"Jira {key}: {issue.get('summary', '')}", url, desc))
        except Exception as exc:
            unavailable.append(f"Jira: {str(exc)[:120]}")
    elif not connection:
        unavailable.append("Jira: No connected project")
    else:
        unavailable.append("Jira: Authenticate Jira account to retrieve issues")

    # 4. Risk Analysis Indicators
    try:
        risk = risk_analysis.get_risk_analysis(project_id, None, effective_user_email, db)
        risk_indicators = risk.indicators
        for indicator in risk.indicators:
            evidence_items = indicator.evidence_items or []
            risk_url = next((item.url for item in evidence_items if item.url), None)
            sources.append(_source(
                f"risk-{indicator.category}-{indicator.title[:20]}",
                "jira" if "jira" in indicator.source_origin.lower() else "architecture",
                f"Risk: {indicator.title}",
                risk_url,
                f"Severity: {indicator.severity} | Category: {indicator.category} | Reason: {indicator.reason} | Action: {indicator.suggested_action}",
            ))
    except Exception as exc:
        unavailable.append(f"Risk Analysis: {str(exc)[:120]}")

    return sources, unavailable, jira_issues, risk_indicators, site_url


def _rule_based_answer(question: str, sources: List[Dict[str, Any]], jira_issues: List[Dict[str, Any]], risk_indicators: List[Any], site_url: Optional[str]) -> Dict[str, Any]:
    """Generates an intelligent, domain-rich answer strictly from verified telemetry."""
    q = question.lower()
    findings: List[str] = []
    actions: List[str] = []
    cited_ids: List[str] = []

    now = datetime.now(timezone.utc)
    today = now.date()

    unfinished = [i for i in jira_issues if (i.get("status") or "").lower() not in {"done", "closed", "resolved", "complete", "completed"}]
    blocked = [i for i in unfinished if "block" in (i.get("status") or "").lower()]
    dep_blocked = [i for i in unfinished if any("block" in (d.get("relationship") or "").lower() for d in i.get("dependencies") or [])]
    high_priority = [i for i in unfinished if (i.get("priority") or "").lower() in {"high", "highest", "critical", "blocker"}]
    overdue = []
    for i in unfinished:
        dd = i.get("due_date")
        if dd:
            try:
                p_date = datetime.fromisoformat(dd.replace("Z", "+00:00")).date()
                if p_date < today:
                    overdue.append(i)
            except Exception:
                pass

    # Question topic routing
    is_greeting = any(re.search(rf"\b{word}\b", q) for word in ["hello", "hi", "hii", "hiii", "hey", "heyy", "greetings", "good morning", "good afternoon", "good evening", "howdy", "who are you", "what can you do", "help", "start"])
    is_risk_query = any(k in q for k in ["risk", "delivery", "slip", "behind", "delay", "threat", "blocker", "overdue"])
    is_priority_query = any(k in q for k in ["priorit", "focus", "this week", "next", "triage", "work on"])
    is_arch_query = any(k in q for k in ["architect", "component", "code", "api", "service", "module"])
    is_dep_query = any(k in q for k in ["depend", "block", "chain", "predecessor", "linked"])
    is_srs_query = any(k in q for k in ["srs", "requirement", "specification", "document", "coverage"])

    answer_overview = ""

    if is_greeting:
        blocked_count = len(blocked) + len(dep_blocked)
        answer_overview = (
            "👋 **Hi! I'm SEER AI — your Engineering Copilot.**\n\n"
            f"How can I help you today? I am actively monitoring live telemetry across **{len(jira_issues)} Jira issues** "
            f"({len(unfinished)} active work items), repository code components, and requirement specifications.\n\n"
            "Select an interactive quick action below or ask me any question about delivery risks, sprint priorities, and system architecture."
        )
        findings.append(f"Project Pulse: Tracking {len(jira_issues)} Jira issues ({len(unfinished)} active work items).")
        if blocked_count > 0 or len(overdue) > 0:
            findings.append(f"Telemetry Alert: {blocked_count} blocked issue(s) and {len(overdue)} overdue task(s) currently flagged.")
        else:
            findings.append("Delivery Health: No critical blocker chains or overdue deadlines currently flagged.")
        findings.append(f"Connected Sources: {len(sources)} verified telemetry signals across Jira, GitHub, and SRS.")

        actions.append("Ask: What are the biggest delivery risks and what should we do next?")
        actions.append("Ask: Which Jira issues should the team prioritize this week?")
        actions.append("Ask: How does the current architecture support the requested work?")
        actions.append("Action: View Jira Dependency Graph")

        for i in unfinished[:4]:
            cited_ids.append(f"jira-{i['key']}")

    elif is_risk_query:
        # Risk & Delivery Focus
        crit_count = sum(1 for ind in risk_indicators if ind.severity in {"critical", "high"})
        answer_overview = f"Delivery telemetry analysis across {len(jira_issues)} Jira issues and connected codebases identified {crit_count} elevated risk area(s)."
        
        if overdue:
            findings.append(f"{len(overdue)} issue(s) are past their verified due date ({', '.join(i['key'] for i in overdue[:6])}).")
            actions.append("Reassess timeline commitments and adjust sprint capacity for overdue work.")
            for i in overdue[:5]:
                cited_ids.append(f"jira-{i['key']}")

        if blocked or dep_blocked:
            block_keys = [i['key'] for i in (blocked + dep_blocked)]
            findings.append(f"{len(block_keys)} issue(s) have verified delivery blockers or blocked dependency links: {', '.join(block_keys[:6])}.")
            actions.append("Conduct an immediate blocker triage with assignees to unblock downstream work.")
            for k in block_keys[:5]:
                cited_ids.append(f"jira-{k}")

        if high_priority:
            hp_keys = [i['key'] for i in high_priority[:8]]
            findings.append(f"{len(high_priority)} high/critical-priority issue(s) remain unfinished: {', '.join(hp_keys)}.")
            actions.append("Ensure high-priority issues have active owners assigned and are targeted in current sprint.")
            for k in hp_keys[:5]:
                cited_ids.append(f"jira-{k}")

        for ind in risk_indicators[:4]:
            findings.append(f"{ind.title}: {ind.reason}")
            if ind.suggested_action and ind.suggested_action not in actions:
                actions.append(ind.suggested_action)
            cited_ids.extend(s["id"] for s in sources if s["title"] == f"Risk: {ind.title}")

    elif is_priority_query:
        # Priority & Sprint Focus
        answer_overview = f"Backlog prioritization analysis based on {len(unfinished)} active, unfinished Jira work items:"
        if high_priority:
            keys = [i['key'] for i in high_priority[:8]]
            findings.append(f"High-impact work items needing focus: {', '.join(keys)}.")
            for i in high_priority[:6]:
                cited_ids.append(f"jira-{i['key']}")
            actions.append("Direct sprint execution towards these high-priority tickets first.")
        
        if blocked:
            findings.append(f"Blocked work items requiring intervention: {', '.join(i['key'] for i in blocked[:5])}.")
            actions.append("Resolve technical or resource bottlenecks before pulling new backlog stories.")
            for i in blocked[:4]:
                cited_ids.append(f"jira-{i['key']}")

        if not high_priority and not blocked:
            findings.append("No active tickets have explicit High/Highest priority tags. Backlog items are currently ranked as Medium or unassigned.")
            actions.append("Run backlog grooming to assign explicit priority levels to upcoming sprint stories.")

    elif is_dep_query:
        # Dependency Analysis
        with_deps = [i for i in jira_issues if i.get("dependencies") or i.get("parent_key")]
        answer_overview = f"Dependency graph analysis resolved {len(with_deps)} Jira issues with explicit links or parent-child hierarchy."
        if dep_blocked:
            findings.append(f"{len(dep_blocked)} issue(s) are waiting on linked predecessor issues.")
            actions.append("Review the dependency graph tab to trace predecessor issues before scheduling child tasks.")
            for i in dep_blocked[:6]:
                cited_ids.append(f"jira-{i['key']}")
        else:
            findings.append("No active circular or blocking dependency deadlocks were found among retrieved issue links.")
            actions.append("Verify link relationships (blocks/is blocked by) are kept up to date during daily standups.")

    elif is_arch_query:
        # Architecture & Code Focus
        repo_sources = [s for s in sources if s["type"] == "github"]
        answer_overview = f"Architecture assessment across {len(repo_sources)} connected repository models:"
        for s in repo_sources[:3]:
            findings.append(f"{s['title']}: {s['text'][:120]}...")
            cited_ids.append(s["id"])
        actions.append("Cross-reference open Jira stories with documented API surface and components.")

    elif is_srs_query:
        # Requirements & SRS
        srs_sources = [s for s in sources if s["type"] == "srs"]
        if srs_sources:
            answer_overview = f"SRS requirement coverage analysis based on {len(srs_sources)} uploaded specification document(s):"
            for s in srs_sources:
                findings.append(f"Document {s['title']} is indexed with extracted requirements.")
                cited_ids.append(s["id"])
            actions.append("Verify all functional requirements from the SRS are represented as Jira Epics and Stories.")
        else:
            answer_overview = "No SRS documents are currently connected to this project workspace."
            findings.append("Requirements coverage cannot be calculated without an uploaded SRS specification.")
            actions.append("Upload the software requirement specification (.pdf / .docx) in Project Overview.")

    if not findings:
        answer_overview = f"Retrieved {len(sources)} verified project telemetry signals across Jira and GitHub."
        findings.append("No critical delivery blockers or architectural alerts were matched to this query.")
        actions.append("Try asking about specific delivery risks, sprint priorities, or architecture components.")

    valid_ids = set(s["id"] for s in sources)
    unique_cited = [s for s in sources if s["id"] in valid_ids and s["id"] in set(cited_ids)]

    # Add relevant Jira citations if list is small
    if len(unique_cited) < 3 and jira_issues:
        for i in unfinished[:4]:
            cid = f"jira-{i.get('key')}"
            if cid in valid_ids and not any(c["id"] == cid for c in unique_cited):
                unique_cited.append(next(s for s in sources if s["id"] == cid))

    return {
        "answer": answer_overview,
        "findings": findings,
        "actions": list(dict.fromkeys(actions)),
        "citations": unique_cited[:12],
        "mode": "rule-based",
    }


def _ask_gemini(question: str, sources: List[Dict[str, Any]]) -> Dict[str, Any]:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="GEMINI_API_KEY not configured")

    # Build concise evidence (NOT 1.5MB raw dumps)
    compact_evidence = []
    for s in sources[:30]:
        compact_evidence.append({
            "id": s["id"],
            "type": s["type"],
            "title": s["title"],
            "summary": s["text"][:300]
        })

    prompt = (
        "You are SEER AI Engineering Copilot. Answer the question using ONLY the provided evidence. "
        "Be concise, analytical, and professional. Explain findings, then give actionable advice. "
        "Return ONLY a JSON object with keys: answer (string), findings (list of strings), "
        "actions (list of strings), citations (list of evidence IDs from the provided evidence).\n\n"
        f"Question: {question}\n\nEvidence:\n{json.dumps(compact_evidence, ensure_ascii=True)}"
    )

    # Use model with fast timeout (12s) to avoid freezing UI
    model_name = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    
    try:
        response = requests.post(
            url,
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"responseMimeType": "application/json"}
            },
            timeout=12,
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Gemini timeout: {str(exc)[:100]}")

    if not response.ok:
        err_msg = ""
        try:
            err_msg = response.json().get("error", {}).get("message", "")
        except Exception:
            pass
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Gemini error ({response.status_code}): {err_msg[:120]}")

    try:
        raw_text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        result = json.loads(raw_text)
    except Exception:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Gemini returned non-JSON content")

    valid_ids = {s["id"] for s in sources}
    cited = [s for s in sources if s["id"] in set(result.get("citations", [])) and s["id"] in valid_ids]
    if not cited and sources:
        cited = sources[:5]

    return {
        "answer": str(result.get("answer") or "Analysis completed."),
        "findings": [str(f) for f in result.get("findings", [])],
        "actions": [str(a) for a in result.get("actions", [])],
        "citations": cited,
        "mode": "gemini",
    }


@router.post("/{project_id}/insights")
def ask_insights(
    project_id: str,
    request: InsightRequest,
    x_user_email: Optional[str] = Header(None, alias="X-User-Email"),
    db: Session = Depends(get_db),
):
    if not db.query(Project).filter(Project.id == project_id).first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    sources, unavailable, jira_issues, risk_indicators, site_url = _retrieve(project_id, x_user_email, db)
    if not sources:
        raise HTTPException(status_code=status.HTTP_424_FAILED_DEPENDENCY, detail="No connected project evidence is available yet.")

    q_clean = request.question.strip().lower()
    is_greeting = any(re.search(rf"\b{word}\b", q_clean) for word in ["hello", "hi", "hii", "hiii", "hey", "heyy", "greetings", "good morning", "good afternoon", "good evening", "howdy", "who are you", "what can you do", "help", "start"])
    if is_greeting:
        greeting_res = _rule_based_answer(request.question.strip(), sources, jira_issues, risk_indicators, site_url)
        return {
            **greeting_res,
            "mode": "rule-based",
            "sources": [{"type": s["type"], "available": True} for s in sources],
            "unavailable": unavailable,
        }

    mode_used = "gemini"
    try:
        result = _ask_gemini(request.question.strip(), sources)
    except HTTPException as exc:
        # Graceful fallback to rich deterministic telemetry engine
        result = _rule_based_answer(request.question.strip(), sources, jira_issues, risk_indicators, site_url)
        mode_used = "rule-based"
        # Only record note, don't spam error
        unavailable.append(f"AI Engine: Running in high-reliability telemetry mode ({exc.detail[:60]})")

    return {
        **result,
        "mode": mode_used,
        "sources": [{"type": s["type"], "available": True} for s in sources],
        "unavailable": unavailable,
    }


@router.get("/{project_id}/insights/jira-dependency-graph")
def get_jira_dependency_graph(
    project_id: str,
    x_user_email: Optional[str] = Header(None, alias="X-User-Email"),
    db: Session = Depends(get_db),
):
    if not db.query(Project).filter(Project.id == project_id).first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    _, unavailable, jira_issues, risk_indicators, site_url = _retrieve(project_id, x_user_email, db)
    issue_map = {issue.get("key"): issue for issue in jira_issues if issue.get("key")}
    risk_keys = {key for ind in risk_indicators for key in (ind.affected_issue_keys or [])}
    
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    
    for key, issue in issue_map.items():
        status_name = issue.get("status") or "Unknown"
        priority = issue.get("priority") or "Unassigned"
        is_blocked = "block" in status_name.lower() or any(
            "block" in (dep.get("relationship") or "").lower() for dep in (issue.get("dependencies") or [])
        )
        url = issue.get("jira_url") or (f"{site_url.rstrip('/')}/browse/{key}" if site_url and key else None)
        
        nodes.append({
            "id": key,
            "label": key,
            "title": issue.get("summary") or key,
            "status": status_name,
            "priority": priority,
            "risk": key in risk_keys,
            "blocked": is_blocked,
            "url": url,
        })

        # Add dependency edges
        for dep in issue.get("dependencies") or []:
            related_key = dep.get("issue_key")
            if related_key in issue_map:
                rel = dep.get("relationship") or "depends on"
                edges.append({
                    "id": f"{related_key}-{key}-{rel}",
                    "source": related_key,
                    "target": key,
                    "relationship": rel,
                })

        # Add parent hierarchy edges
        parent_key = issue.get("parent_key")
        if parent_key and parent_key in issue_map:
            edges.append({
                "id": f"{parent_key}-{key}-parent",
                "source": parent_key,
                "target": key,
                "relationship": "parent of",
            })

    # Summary impact
    blocked_count = sum(1 for n in nodes if n["blocked"])
    risk_count = sum(1 for n in nodes if n["risk"])
    impact = f"{len(edges)} verified dependency edge(s) across {len(nodes)} Jira issues ({blocked_count} blocked, {risk_count} at risk). Strictly no inferred data."

    return {
        "nodes": nodes,
        "edges": edges,
        "unavailable": unavailable,
        "impact": impact,
    }
