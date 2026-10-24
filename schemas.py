from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, List, Dict, Union
from datetime import datetime

# Project Schemas
class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)

class ProjectResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# Repository Schemas
class RepositoryConnect(BaseModel):
    repository_url: str

class RepositoryResponse(BaseModel):
    id: str
    project_id: str
    github_url: str
    owner: str
    name: str
    description: Optional[str]
    default_branch: str
    primary_language: Optional[str]
    stars: int
    forks: int
    open_issues_count: int
    created_at: datetime
    updated_at: datetime
    last_pushed_at: datetime
    analysis_status: Optional[str] = "Not Analyzed"

    class Config:
        from_attributes = True

# Extended Details (For Frontend On-Demand Fetching)
class CommitInfo(BaseModel):
    sha: str
    message: str
    author: Optional[str] = "Contributor"
    date: str

class IssueInfo(BaseModel):
    number: int
    title: str
    state: str
    author: Optional[str] = "Unknown"
    created_at: str
    updated_at: str
    labels: List[str] = []

class PullRequestInfo(BaseModel):
    number: int
    title: str
    state: str
    author: Optional[str] = "Unknown"
    created_at: Optional[str] = "2026-08-20T00:00:00Z"
    updated_at: Optional[str] = "2026-08-20T00:00:00Z"
    merged_at: Optional[str] = None
    is_merged: bool = False


class FileNode(BaseModel):
    path: str
    type: str

class BranchInfo(BaseModel):
    name: str
    protected: bool
    commit_sha: str

class ContributorInfo(BaseModel):
    login: str
    contributions: int
    avatar_url: Optional[str]
    html_url: Optional[str]

class IssuesSummary(BaseModel):
    total: int
    open: int
    closed: int

class PullRequestsSummary(BaseModel):
    total: int
    open: int
    closed: int
    merged: int

class ReadmeInsights(BaseModel):
    has_readme: bool
    summary: Optional[str]
    sections: List[str]

class KeyComponentDetail(BaseModel):
    path: str
    name: str
    purpose: str
    role: str
    relationships: List[str] = []

class ApiSurfaceDetail(BaseModel):
    method: str
    endpoint: str
    description: str
    source_file: str
    parameters: List[str] = []

class CodePatternDetail(BaseModel):
    pattern_name: str
    category: str
    description: str
    source_files: List[str] = []
    reusable_approach: str

class IntegrationPointDetail(BaseModel):
    service_name: str
    integration_type: str
    direction: str
    file_config: str
    purpose: str

class DependencyDetail(BaseModel):
    package: str
    version: str
    ecosystem: str
    purpose: str
    relationships: str

class AnalysisResponse(BaseModel):
    overview: Optional[str] = None
    technologies: List[str] = []
    architecture_overview: Optional[str] = None
    key_components: List[str] = []
    key_components_details: List[KeyComponentDetail] = []
    api_surface: List[str] = []
    api_surface_details: List[ApiSurfaceDetail] = []
    code_patterns: List[str] = []
    code_patterns_details: List[CodePatternDetail] = []
    integration_points: List[str] = []
    integration_points_details: List[IntegrationPointDetail] = []
    dependencies: List[str] = []
    dependencies_details: List[DependencyDetail] = []
    build_deployment_config: List[str] = []
    database_technologies: List[str] = []
    external_services: List[str] = []
    readme_insights: Optional[ReadmeInsights] = None


class RepositoryDetailResponse(BaseModel):
    metadata: RepositoryResponse
    languages: Dict[str, float]
    file_structure: List[FileNode]
    commits: List[CommitInfo]
    total_commits: Optional[int] = 0
    branches: List[BranchInfo] = []
    contributors: List[ContributorInfo] = []
    issues: List[IssueInfo]
    issues_summary: Optional[IssuesSummary] = None
    pull_requests: List[PullRequestInfo]
    pull_requests_summary: Optional[PullRequestsSummary] = None
    analysis: Optional[AnalysisResponse] = None
    analysis_status: str = "Completed"


# Jira Schemas
class JiraProjectOption(BaseModel):
    id: str
    key: str
    name: str
    project_type_key: Optional[str] = None
    avatar_url: Optional[str] = None

class JiraConnectRequest(BaseModel):
    jira_project_key: str = Field(..., min_length=1)
    jira_project_name: str = Field(..., min_length=1)
    jira_project_id: Optional[str] = None
    jira_cloud_id: Optional[str] = None
    site_url: Optional[str] = None

class JiraConnectionResponse(BaseModel):
    id: str
    project_id: str
    jira_project_key: str
    jira_project_name: str
    jira_project_id: Optional[str] = None
    jira_cloud_id: Optional[str] = None
    site_url: Optional[str] = None
    connected_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class JiraRepositoryConnectionResponse(JiraConnectionResponse):
    repository_id: str


class JiraRepositoryConnectionStatus(BaseModel):
    repository_id: str
    repository_name: str
    connection: Optional[JiraRepositoryConnectionResponse] = None
    effective_connection: Optional[JiraConnectionResponse] = None
    uses_project_fallback: bool = False

class JiraStatusResponse(BaseModel):
    authenticated: bool
    connected: bool
    jira_user: Optional[str] = None
    connection: Optional[JiraConnectionResponse] = None
    available_projects: List[JiraProjectOption] = []


class JiraStoryDraftUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    acceptance_criteria: Optional[List[str]] = None
    priority: Optional[str] = Field(None, pattern="^(Highest|High|Medium|Low|Lowest)$")


class JiraStoryGenerateRequest(BaseModel):
    repository_id: Optional[str] = None
    all_repositories: bool = False
    context: str = Field("github", pattern="^(github|srs|combined)$")
    srs_document_id: Optional[str] = None
    jira_project_key: Optional[str] = None
    parent_epic_draft_id: Optional[str] = None

class JiraEpicCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    jira_project_key: str = Field(..., min_length=1)
    acceptance_criteria: Optional[List[str]] = []
    priority: Optional[str] = "High"

class JiraEpicGenerateFromSRSRequest(BaseModel):
    srs_document_id: Optional[str] = None
    jira_project_key: str = Field(..., min_length=1)
    custom_title: Optional[str] = None
    custom_description: Optional[str] = None
    priority: Optional[str] = "High"

class JiraProjectDestination(BaseModel):
    key: str
    name: str
    id: Optional[str] = None

class SRSDocumentResponse(BaseModel):
    id: str
    project_id: str
    filename: str
    content_type: Optional[str] = None
    character_count: int
    created_at: Optional[datetime] = None


class JiraStoryDraftResponse(BaseModel):
    id: str
    project_id: str
    repository_id: Optional[str] = None
    parent_draft_id: Optional[str] = None
    repository_name: Optional[str] = None
    repository_url: Optional[str] = None
    source_github_url: Optional[str] = None
    jira_project_key: Optional[str] = None
    jira_project_name: Optional[str] = None
    jira_project_id: Optional[str] = None
    jira_connected: bool = False
    uses_project_jira_fallback: bool = False
    title: str
    issue_type: str = "Story"
    description: Optional[str] = None
    acceptance_criteria: List[str] = []
    priority: str
    source_type: Optional[str] = None
    source_ref: Optional[str] = None
    status: str
    jira_issue_key: Optional[str] = None
    jira_issue_id: Optional[str] = None
    jira_issue_url: Optional[str] = None
    jira_status: Optional[str] = None
    creation_error: Optional[str] = None
    created_by_email: Optional[str] = None
    approved_by_email: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class JiraStoryDraftListResponse(BaseModel):
    drafts: List[JiraStoryDraftResponse]
    jira_connected: bool
    repository_connected: bool
    auto_create_enabled: bool
    is_admin: bool


class JiraStoryGenerateResponse(BaseModel):
    created_count: int
    skipped_duplicates: int
    auto_created_count: int
    drafts: List[JiraStoryDraftResponse]


class JiraAutoCreateSettings(BaseModel):
    enabled: bool
    is_admin: bool


class JiraTimelineDependency(BaseModel):
    issue_key: str
    relationship: str


class JiraTimelineIssue(BaseModel):
    key: str
    summary: str
    status: Optional[str] = None
    issue_type: Optional[str] = None
    priority: Optional[str] = None
    created_at: Optional[Union[datetime, str]] = None
    updated_at: Optional[Union[datetime, str]] = None
    due_date: Optional[str] = None
    start_date: Optional[str] = None
    parent_key: Optional[str] = None
    sprint: Optional[str] = None
    sprint_start_date: Optional[str] = None
    sprint_end_date: Optional[str] = None
    sprint_state: Optional[str] = None
    assignee_name: Optional[str] = None
    assignee_avatar: Optional[str] = None
    dependencies: List[JiraTimelineDependency] = []
    jira_url: Optional[str] = None


class JiraTimelineResponse(BaseModel):
    connected: bool
    jira_project_key: Optional[str] = None
    jira_project_name: Optional[str] = None
    jira_project_id: Optional[str] = None
    issues: List[JiraTimelineIssue] = []
    missing_fields: List[str] = []
    message: Optional[str] = None

class RiskAffectedIssue(BaseModel):
    key: str
    summary: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    jira_url: Optional[str] = None

class RiskEvidenceItem(BaseModel):
    label: str
    url: Optional[str] = None
    source_type: str = "jira"  # jira, github, srs, architecture

class RiskIndicator(BaseModel):
    severity: str
    category: str
    title: str
    evidence: List[str] = []
    evidence_items: List[RiskEvidenceItem] = []
    reason: str
    suggested_action: str
    affected_issue_keys: List[str] = []
    affected_issues: List[RiskAffectedIssue] = []
    source_origin: str = "Jira"
    source_api: str = ""
    calculation_logic: str = ""

class RiskGitHubActivity(BaseModel):
    connected: bool
    repositories: int = 0
    open_issues: int = 0
    recent_commits: int = 0
    message: Optional[str] = None

class RiskAnalysisResponse(BaseModel):
    project_id: str
    jira_project_key: Optional[str] = None
    jira_project_name: Optional[str] = None
    jira_base_url: Optional[str] = None
    health: str
    health_basis: str
    indicators: List[RiskIndicator] = []
    jira_issue_count: int = 0
    unfinished_issue_count: int = 0
    overdue_issue_count: int = 0
    blocked_issue_count: int = 0
    github_activity: RiskGitHubActivity
    prediction_status: str
    last_updated: Optional[str] = None
    message: Optional[str] = None


class JiraAutoCreateUpdate(BaseModel):
    enabled: bool

