export interface RiskEvidenceItem {
  label: string;
  url?: string;
  source_type: 'jira' | 'github' | 'srs' | 'architecture';
}

export interface RiskAffectedIssue {
  key: string;
  summary?: string;
  priority?: string;
  status?: string;
  jira_url?: string;
}

export interface RiskIndicator {
  severity: 'low' | 'medium' | 'high' | 'critical';
  category: string;
  title: string;
  evidence: string[];
  evidence_items?: RiskEvidenceItem[];
  reason: string;
  suggested_action: string;
  affected_issue_keys?: string[];
  affected_issues?: RiskAffectedIssue[];
  source_origin?: string;
  source_api?: string;
  calculation_logic?: string;
}

export interface RiskAnalysisResponse {
  project_id: string;
  jira_project_key?: string;
  jira_project_name?: string;
  jira_base_url?: string;
  health: string;
  health_basis: string;
  indicators: RiskIndicator[];
  jira_issue_count: number;
  unfinished_issue_count: number;
  overdue_issue_count: number;
  blocked_issue_count: number;
  github_activity: {
    connected: boolean;
    repositories: number;
    open_issues: number;
    recent_commits: number;
    message?: string;
  };
  prediction_status: string;
  last_updated?: string;
  message?: string;
}

const API_BASE = (import.meta.env.VITE_API_URL || 'http://localhost:8000') + '/api';

export class ApiError extends Error {
  status?: number;
  constructor(message: string, status?: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

export const riskService = {
  async getAnalysis(projectId: string, userEmail?: string, jiraProjectKey?: string): Promise<RiskAnalysisResponse> {
    const headers: Record<string, string> = { Accept: 'application/json' };
    if (userEmail) headers['X-User-Email'] = userEmail;
    const query = jiraProjectKey ? `?jiraProjectKey=${encodeURIComponent(jiraProjectKey)}` : '';
    
    let response: Response;
    try {
      response = await fetch(`${API_BASE}/projects/${encodeURIComponent(projectId)}/risk${query}`, { headers });
    } catch (networkErr: any) {
      throw new ApiError('Network connection failure. Unable to reach SEER AI server.', 0);
    }

    if (!response.ok) {
      const errorJson = await response.json().catch(() => ({}));
      const detail = errorJson.detail;
      const status = response.status;
      
      if (status === 401 || status === 403) {
        throw new ApiError(detail || 'Authentication or permissions error: please verify your Jira credentials or login session.', status);
      } else if (status === 404) {
        throw new ApiError(detail || 'The requested project or Jira destination was not found.', status);
      } else if (status === 429) {
        throw new ApiError(detail || 'API rate limit exceeded. Please wait a moment before trying again.', status);
      } else if (status >= 500) {
        throw new ApiError(detail || 'Internal server error encountered while compiling risk telemetry.', status);
      }
      throw new ApiError(detail || 'Failed to load project risk analysis.', status);
    }
    return response.json();
  },
};

export default riskService;
