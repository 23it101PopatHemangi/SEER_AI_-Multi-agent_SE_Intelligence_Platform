import os
import uuid
from datetime import datetime
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, status, Query, Header
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pathlib import Path
from dotenv import load_dotenv

# Always load backend/.env (works even if uvicorn is started from the repo root)
_BACKEND_DIR = Path(__file__).resolve().parent
load_dotenv(_BACKEND_DIR / ".env")
load_dotenv(_BACKEND_DIR.parent / ".env")
load_dotenv()

# Import database module
from database import get_db, init_db, Project as DBProject, Repository as DBRepository, UserToken
import schemas
import github_service
import github_oauth
import jira_oauth
import jira_story_drafts
import repo_analyzer
import srs_documents
import risk_analysis
import insights

app = FastAPI(
    title="SEER AI API",
    description="Backend API for SEER AI Platform",
    version="1.3.0"
)

# CORS configuration to allow local frontend development server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_origin_regex=r"https?://.*"
)

# Register Routers
app.include_router(github_oauth.router)
app.include_router(jira_oauth.router)
app.include_router(jira_story_drafts.router)
app.include_router(srs_documents.router)
app.include_router(risk_analysis.router)
app.include_router(insights.router)

# Initialize database schemas on boot
@app.on_event("startup")
def startup_event():
    init_db()

# Dependency to retrieve the logged-in user's GitHub OAuth token
def get_user_github_token(
    x_user_email: Optional[str] = Header(None, alias="X-User-Email"),
    db: Session = Depends(get_db)
) -> Optional[str]:
    if not x_user_email:
        return None
    db_token = db.query(UserToken).filter(UserToken.user_email == x_user_email).first()
    if db_token:
        return db_token.github_access_token
    return None

# Helper to parse dates securely
def parse_github_date(date_str: str) -> datetime:
    if not date_str:
        return datetime.utcnow()
    try:
        return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        try:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except Exception:
            return datetime.utcnow()

# Root / Health endpoint
@app.get("/api/health")
async def health_check():
    return {
        "status": "ok",
        "message": "SEER AI backend is healthy",
        "version": "1.3.0",
        "database": "sqlite/postgresql setup active"
    }

# ----------------- PROJECTS ENDPOINTS -----------------

@app.get("/api/projects", response_model=List[schemas.ProjectResponse])
def list_projects(db: Session = Depends(get_db)):
    projects = db.query(DBProject).all()
    
    from repo_analyzer import CACHE_DIR
    import os
    
    for project in projects:
        repos = db.query(DBRepository).filter(DBRepository.project_id == project.id).all()
        latest_time = project.updated_at
        for r in repos:
            cache_path = os.path.join(CACHE_DIR, f"{r.id}.json")
            if os.path.exists(cache_path):
                mtime = datetime.utcfromtimestamp(os.path.getmtime(cache_path))
                if mtime > latest_time:
                    latest_time = mtime
        if latest_time > project.updated_at:
            project.updated_at = latest_time
            db.commit()
            db.refresh(project)
            
    return projects

@app.post("/api/projects", response_model=schemas.ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(project_in: schemas.ProjectCreate, db: Session = Depends(get_db)):
    if not project_in.name.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Project name cannot be empty"
        )
    
    new_project = DBProject(
        id=str(uuid.uuid4()),
        name=project_in.name.strip(),
        description=project_in.description.strip() if project_in.description else ""
    )
    db.add(new_project)
    db.commit()
    db.refresh(new_project)
    return new_project

@app.get("/api/projects/{projectId}", response_model=schemas.ProjectResponse)
def get_project(projectId: str, db: Session = Depends(get_db)):
    project = db.query(DBProject).filter(DBProject.id == projectId).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    # Sync with repository analysis cache modification times
    from repo_analyzer import CACHE_DIR
    import os
    
    repos = db.query(DBRepository).filter(DBRepository.project_id == projectId).all()
    latest_time = project.updated_at
    for r in repos:
        cache_path = os.path.join(CACHE_DIR, f"{r.id}.json")
        if os.path.exists(cache_path):
            mtime = datetime.utcfromtimestamp(os.path.getmtime(cache_path))
            if mtime > latest_time:
                latest_time = mtime
                
    if latest_time > project.updated_at:
        project.updated_at = latest_time
        db.commit()
        db.refresh(project)
        
    return project

# ----------------- REPOSITORIES ENDPOINTS -----------------

@app.get("/api/projects/{projectId}/repositories", response_model=List[schemas.RepositoryResponse])
def list_repositories(projectId: str, db: Session = Depends(get_db)):
    project = db.query(DBProject).filter(DBProject.id == projectId).first()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        
    repos = db.query(DBRepository).filter(DBRepository.project_id == projectId).all()
    
    import os
    import json
    from repo_analyzer import CACHE_DIR
    
    enriched = []
    for r in repos:
        cache_path = os.path.join(CACHE_DIR, f"{r.id}.json")
        status_val = "Not Analyzed"
        primary_lang = r.primary_language
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    cdata = json.load(f)
                    if cdata.get("analysis") and cdata["analysis"].get("overview"):
                        status_val = "Analyzed"
                    langs = cdata.get("languages", {})
                    if langs:
                        sorted_langs = [l for l, pct in sorted(langs.items(), key=lambda x: x[1], reverse=True) if pct >= 0.1]
                        if sorted_langs:
                            all_langs_str = ", ".join(sorted_langs)
                            primary_lang = all_langs_str
                            if r.primary_language != all_langs_str:
                                r.primary_language = all_langs_str
                                db.commit()
            except Exception as ex:
                print(f"Failed to auto-heal primary_language for {r.name}: {ex}")

        # Sync last_pushed_at directly from GitHub repository metadata (GET /repos/{owner}/{repo})
        pushed_date = r.last_pushed_at
        try:
            meta = github_service.fetch_repo_metadata(r.owner, r.name)
            if meta and meta.get("pushed_at"):
                gh_pushed = parse_github_date(meta.get("pushed_at"))
                if gh_pushed and r.last_pushed_at != gh_pushed:
                    r.last_pushed_at = gh_pushed
                    db.commit()
                    db.refresh(r)
                pushed_date = gh_pushed
        except Exception as ex:
            print(f"Failed sync pushed_at for {r.name}: {ex}")

        # Build dictionary matching schema parameters
        enriched.append({
            "id": r.id,
            "project_id": r.project_id,
            "github_url": r.github_url,
            "owner": r.owner,
            "name": r.name,
            "description": r.description,
            "default_branch": r.default_branch,
            "primary_language": primary_lang,
            "stars": r.stars,
            "forks": r.forks,
            "open_issues_count": r.open_issues_count,
            "created_at": r.created_at,
            "updated_at": r.updated_at,
            "last_pushed_at": pushed_date,
            "analysis_status": status_val
        })
    return enriched

@app.post("/api/projects/{projectId}/repositories", response_model=schemas.RepositoryResponse, status_code=status.HTTP_201_CREATED)
def connect_repository(
    projectId: str,
    repo_in: schemas.RepositoryConnect,
    db: Session = Depends(get_db),
    github_token: Optional[str] = Depends(get_user_github_token)
):
    project = db.query(DBProject).filter(DBProject.id == projectId).first()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    # 1. Parse repository URL
    owner, repo_name = github_service.parse_github_url(repo_in.repository_url)

    # 2. Duplicate repository protection
    existing = db.query(DBRepository).filter(
        DBRepository.project_id == projectId,
        DBRepository.owner.ilike(owner),
        DBRepository.name.ilike(repo_name)
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This repository is already connected to this project."
        )

    # 3. Call GitHub API to fetch metadata and complete language breakdown
    meta = github_service.fetch_repo_metadata(owner, repo_name, token=github_token)
    default_branch = meta.get("default_branch", "main")
    file_struct = github_service.fetch_repo_tree(owner, repo_name, default_branch, token=github_token)
    langs_dict = github_service.fetch_repo_languages(owner, repo_name, token=github_token, file_structure=file_struct)

    primary_lang_str = meta.get("language") or "Unknown"
    if langs_dict:
        sorted_langs = [l for l, _ in sorted(langs_dict.items(), key=lambda x: x[1], reverse=True)]
        if sorted_langs:
            primary_lang_str = ", ".join(sorted_langs)

    # 4. Save metadata to Database
    new_repo = DBRepository(
        id=str(uuid.uuid4()),
        project_id=projectId,
        github_url=f"https://github.com/{owner}/{repo_name}",
        owner=owner,
        name=repo_name,
        description=meta.get("description") or "",
        default_branch=default_branch,
        primary_language=primary_lang_str,
        stars=meta.get("stargazers_count", 0),
        forks=meta.get("forks_count", 0),
        open_issues_count=meta.get("open_issues_count", 0),
        created_at=parse_github_date(meta.get("created_at")),
        updated_at=parse_github_date(meta.get("updated_at")),
        last_pushed_at=parse_github_date(meta.get("pushed_at"))
    )
    db.add(new_repo)
    
    # Update project updated_at date
    project.updated_at = datetime.utcnow()
    
    db.commit()
    db.refresh(new_repo)
    return new_repo

@app.get("/api/projects/{projectId}/repositories/{repositoryId}", response_model=schemas.RepositoryDetailResponse)
def get_repository_detail(
    projectId: str,
    repositoryId: str,
    db: Session = Depends(get_db),
    github_token: Optional[str] = Depends(get_user_github_token),
    force_reanalyze: bool = False
):
    project = db.query(DBProject).filter(DBProject.id == projectId).first()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    # Fetch repository metadata from Database
    repo = db.query(DBRepository).filter(
        DBRepository.id == repositoryId,
        DBRepository.project_id == projectId
    ).first()
    if not repo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found in this project")

    # Update parent project updated_at date to match this action
    project.updated_at = datetime.utcnow()
    db.commit()

    # Sync last_pushed_at directly from actual GitHub repository pushed_at timestamp
    try:
        meta = github_service.fetch_repo_metadata(repo.owner, repo.name, token=github_token)
        if meta and meta.get("pushed_at"):
            gh_pushed = parse_github_date(meta.get("pushed_at"))
            if gh_pushed and repo.last_pushed_at != gh_pushed:
                repo.last_pushed_at = gh_pushed
                db.commit()
    except Exception as ex:
        print(f"Failed sync pushed_at for {repo.name}: {ex}")

    db.refresh(repo)

    # Fetch live GitHub data on-demand safely with per-item fallbacks
    languages, file_structure, commits, branches, contributors, issues, pull_requests = {}, [], [], [], [], [], []
    total_commits = 0
    live_fetch_success = True

    # 1. File Structure
    try:
        file_structure = github_service.fetch_repo_tree(repo.owner, repo.name, repo.default_branch, token=github_token)
    except Exception as e:
        print(f"Safe fetch tree fallback for {repo.name}: {e}")
        live_fetch_success = False

    # 2. Languages
    try:
        languages = github_service.fetch_repo_languages(repo.owner, repo.name, token=github_token, file_structure=file_structure)
    except Exception as e:
        print(f"Safe fetch languages fallback for {repo.name}: {e}")
        live_fetch_success = False

    # 3. Commits & Total Commits
    try:
        commits = github_service.fetch_repo_commits(repo.owner, repo.name, token=github_token)
        total_commits = github_service.fetch_total_commit_count(repo.owner, repo.name, token=github_token)
    except Exception as e:
        print(f"Safe fetch commits fallback for {repo.name}: {e}")
        live_fetch_success = False
        commits = github_service.fetch_repo_commits_fallback(repo.owner, repo.name, repo.default_branch)
        total_commits = len(commits)

    # 4. Branches
    try:
        branches = github_service.fetch_repo_branches(repo.owner, repo.name, token=github_token)
    except Exception as e:
        print(f"Safe fetch branches fallback for {repo.name}: {e}")
        live_fetch_success = False
        branches = [{"name": repo.default_branch or "main", "protected": False}]

    # 5. Contributors
    try:
        contributors = github_service.fetch_repo_contributors(repo.owner, repo.name, token=github_token)
    except Exception as e:
        print(f"Safe fetch contributors fallback for {repo.name}: {e}")
        live_fetch_success = False
        contributors = [{"login": repo.owner, "contributions": 1, "avatar_url": f"https://github.com/{repo.owner}.png"}]

    # 6. Issues
    try:
        issues = github_service.fetch_repo_issues(repo.owner, repo.name, state="all", token=github_token)
    except Exception as e:
        print(f"Safe fetch issues fallback for {repo.name}: {e}")
        live_fetch_success = False

    # 7. Pull Requests
    try:
        pull_requests = github_service.fetch_repo_pulls(repo.owner, repo.name, state="all", token=github_token)
    except Exception as e:
        print(f"Safe fetch PRs fallback for {repo.name}: {e}")
        live_fetch_success = False

    # Merge cached telemetry if present
    cache_data = repo_analyzer.load_raw_cache(repo.id)
    if cache_data:
        if not file_structure:
            file_structure = cache_data.get("file_structure", file_structure)
        if not languages:
            languages = cache_data.get("languages", languages)
        if not commits:
            commits = cache_data.get("commits", commits)
            total_commits = cache_data.get("total_commits", total_commits or len(commits))
        if not branches:
            branches = cache_data.get("branches", branches)
        if not contributors:
            contributors = cache_data.get("contributors", contributors)
        if not issues:
            issues = cache_data.get("issues", issues)
    # Permanently resolve and self-heal real total commit count
    if not total_commits or total_commits <= 20:
        try:
            real_total = github_service.fetch_total_commit_count(repo.owner, repo.name, token=github_token, branch=repo.default_branch)
            if total_commits is None or (isinstance(real_total, int) and real_total > total_commits):
                total_commits = real_total
                if cache_data:
                    cache_data["total_commits"] = real_total
                    repo_analyzer.save_analysis_cache(repo.id, repo.last_pushed_at.isoformat(), cache_data.get("analysis", {}), extra_data=cache_data)
        except Exception as ex:
            print(f"Failed to auto-heal total commits for {repo.name}: {ex}")



    # Sync DB primary_language to canonical GitHub Languages API result
    if languages:
        sorted_langs = [l for l, _ in sorted(languages.items(), key=lambda x: x[1], reverse=True)]
        if sorted_langs:
            all_langs_str = ", ".join(sorted_langs)
            if repo.primary_language != all_langs_str:
                repo.primary_language = all_langs_str
                db.commit()
                db.refresh(repo)



    # Calculate Summaries
    open_issues_cnt = sum(1 for i in issues if i.get("state") == "open")
    closed_issues_cnt = sum(1 for i in issues if i.get("state") == "closed")
    issues_summary = {
        "total": len(issues),
        "open": open_issues_cnt,
        "closed": closed_issues_cnt
    }

    open_prs_cnt = sum(1 for pr in pull_requests if pr.get("state") == "open")
    merged_prs_cnt = sum(1 for pr in pull_requests if pr.get("is_merged"))
    closed_prs_cnt = sum(1 for pr in pull_requests if pr.get("state") == "closed" and not pr.get("is_merged"))

    last_pr_counts = getattr(github_service, "last_pr_counts", {})
    if last_pr_counts and last_pr_counts.get("owner_repo") == f"{repo.owner}/{repo.name}":
        open_prs_cnt = max(open_prs_cnt, last_pr_counts.get("open", open_prs_cnt))
        closed_prs_cnt = max(closed_prs_cnt, last_pr_counts.get("closed", closed_prs_cnt))
        merged_prs_cnt = max(merged_prs_cnt, last_pr_counts.get("merged", merged_prs_cnt))

    total_prs_cnt = open_prs_cnt + closed_prs_cnt + merged_prs_cnt

    pull_requests_summary = {
        "total": total_prs_cnt,
        "open": open_prs_cnt,
        "closed": closed_prs_cnt,
        "merged": merged_prs_cnt
    }

    # Statically analyze repository for all connected repositories
    existing_analysis = cache_data.get("analysis") if cache_data else None
    try:
        analysis = repo_analyzer.analyze_repo_pipeline(
            repo.id,
            repo.last_pushed_at.isoformat(),
            repo.owner,
            repo.name,
            file_structure,
            token=github_token,
            force_reanalyze=force_reanalyze,
            branch=repo.default_branch,
            commits=commits,
            branches=branches,
            contributors=contributors,
            issues=issues,
            pull_requests=pull_requests,
            languages=languages,
            total_commits=total_commits,
            repo_description=repo.description
        )
        repo_analyzer.save_analysis_cache(
            repo.id,
            repo.last_pushed_at.isoformat(),
            analysis,
            extra_data={
                "languages": languages,
                "file_structure": file_structure,
                "commits": commits,
                "total_commits": total_commits,
                "branches": branches,
                "contributors": contributors,
                "issues": issues,
                "pull_requests": pull_requests
            }
        )
        repo.analysis_status = "Analyzed"
        db.commit()
    except Exception as e:
        print(f"Failed to statically analyze repository {repo.owner}/{repo.name}: {e}")
        if existing_analysis:
            analysis = existing_analysis
            repo.analysis_status = "Analyzed"
        else:
            repo.analysis_status = "Failed"
            analysis = {
                "overview": None,
                "technologies": [],
                "architecture_overview": None,
                "key_components": [],
                "api_surface": [],
                "code_patterns": [],
                "integration_points": [],
                "dependencies": [],
                "build_deployment_config": [],
                "database_technologies": [],
                "external_services": [],
                "readme_insights": None
            }



    return {
        "metadata": repo,
        "languages": languages,
        "file_structure": file_structure,
        "commits": commits,
        "total_commits": total_commits,
        "branches": branches,
        "contributors": contributors,
        "issues": issues,
        "issues_summary": issues_summary,
        "pull_requests": pull_requests,
        "pull_requests_summary": pull_requests_summary,
        "analysis": analysis,
        "analysis_status": repo.analysis_status or "Completed"
    }

@app.post("/api/projects/{projectId}/repositories/{repositoryId}/reanalyze", response_model=schemas.RepositoryDetailResponse)
def reanalyze_repository(
    projectId: str,
    repositoryId: str,
    db: Session = Depends(get_db),
    github_token: Optional[str] = Depends(get_user_github_token)
):
    """
    Forces a complete fresh re-analysis of the repository telemetry by invalidating disk cache.
    """
    return get_repository_detail(projectId, repositoryId, db, github_token, force_reanalyze=True)


@app.get("/api/projects/{projectId}/repositories/{repositoryId}/commits", response_model=List[schemas.CommitInfo])
def get_repository_commits(
    projectId: str,
    repositoryId: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    github_token: Optional[str] = Depends(get_user_github_token)
):
    """
    Fetches paginated commit history for a specific repository.
    Supports lazy loading / pagination on the frontend.
    """
    repo = db.query(DBRepository).filter(
        DBRepository.id == repositoryId,
        DBRepository.project_id == projectId
    ).first()
    if not repo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found")
        
    try:
        commits = github_service.fetch_repo_commits_paginated(
            repo.owner, repo.name, page=page, per_page=per_page, token=github_token
        )
        # Self-healing: save commits to cache if page == 1 to populate missing cache data
        if page == 1 and commits:
            from repo_analyzer import load_raw_cache, save_analysis_cache
            cache_data = load_raw_cache(repo.id)
            if cache_data:
                total = github_service.fetch_total_commit_count(repo.owner, repo.name, token=github_token)
                # Keep full commits list in cache, only initialize if missing
                if "commits" not in cache_data or not cache_data["commits"]:
                    cache_data["commits"] = commits
                if total > 0:
                    cache_data["total_commits"] = total
                elif "total_commits" not in cache_data or cache_data["total_commits"] in (0, 20):
                    cache_data["total_commits"] = max(20, len(commits))
                save_analysis_cache(repo.id, repo.last_pushed_at.isoformat(), cache_data.get("analysis", {}), extra_data=cache_data)
        return commits
    except Exception as e:
        print(f"Error fetching paginated commits: {e}")
        # Fallback to local cache commits
        from repo_analyzer import load_raw_cache
        cache_data = load_raw_cache(repo.id)
        if cache_data and "commits" in cache_data:
            all_cached_commits = cache_data["commits"]
            start_idx = (page - 1) * per_page
            end_idx = start_idx + per_page
            return all_cached_commits[start_idx:end_idx]
        return []


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
