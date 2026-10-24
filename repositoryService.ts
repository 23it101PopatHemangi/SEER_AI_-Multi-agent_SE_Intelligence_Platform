export interface Repository {
  id: string;
  project_id: string;
  github_url: string;
  owner: string;
  name: string;
  description?: string;
  default_branch: string;
  primary_language?: string;
  stars: number;
  forks: number;
  open_issues_count: number;
  created_at: string;
  updated_at: string;
  last_pushed_at: string;
  analysis_status?: string;
}

export interface CommitInfo {
  sha: string;
  message: string;
  author?: string;
  date: string;
}

export interface BranchInfo {
  name: string;
  protected: boolean;
  commit_sha: string;
}

export interface ContributorInfo {
  login: string;
  contributions: number;
  avatar_url?: string;
  html_url?: string;
}

export interface IssueInfo {
  number: number;
  title: string;
  state: string;
  author: string;
  created_at: string;
  updated_at: string;
  labels: string[];
}

export interface IssuesSummary {
  total: number;
  open: number;
  closed: number;
}

export interface PullRequestInfo {
  number: number;
  title: string;
  state: string;
  author: string;
  created_at: string;
  updated_at: string;
  merged_at?: string;
  is_merged: boolean;
}

export interface PullRequestsSummary {
  total: number;
  open: number;
  closed: number;
  merged: number;
}

export interface FileNode {
  path: string;
  type: 'blob' | 'tree';
}

export interface ReadmeInsights {
  has_readme: boolean;
  summary?: string;
  sections: string[];
}

export interface KeyComponentDetail {
  path: string;
  name: string;
  purpose: string;
  role: string;
  relationships: string[];
}

export interface ApiSurfaceDetail {
  method: string;
  endpoint: string;
  description: string;
  source_file: string;
  parameters: string[];
}

export interface CodePatternDetail {
  pattern_name: string;
  category: string;
  description: string;
  source_files: string[];
  reusable_approach: string;
}

export interface IntegrationPointDetail {
  service_name: string;
  integration_type: string;
  direction: string;
  file_config: string;
  purpose: string;
}

export interface DependencyDetail {
  package: string;
  version: string;
  ecosystem: string;
  purpose: string;
  relationships: string;
}

export interface AnalysisInfo {
  overview?: string;
  technologies: string[];
  architecture_overview?: string;
  key_components: string[];
  key_components_details?: KeyComponentDetail[];
  api_surface: string[];
  api_surface_details?: ApiSurfaceDetail[];
  code_patterns: string[];
  code_patterns_details?: CodePatternDetail[];
  integration_points: string[];
  integration_points_details?: IntegrationPointDetail[];
  dependencies: string[];
  dependencies_details?: DependencyDetail[];
  build_deployment_config?: string[];
  database_technologies?: string[];
  external_services?: string[];
  readme_insights?: ReadmeInsights;
}


export interface RepositoryDetail {
  metadata: Repository;
  languages: Record<string, number>;
  file_structure: FileNode[];
  commits: CommitInfo[];
  total_commits?: number;
  branches?: BranchInfo[];
  contributors?: ContributorInfo[];
  issues: IssueInfo[];
  issues_summary?: IssuesSummary;
  pull_requests: PullRequestInfo[];
  pull_requests_summary?: PullRequestsSummary;
  analysis?: AnalysisInfo;
  analysis_status?: string;
}

const API_BASE = (((import.meta as any).env?.VITE_API_URL) || 'http://localhost:8000') + '/api';


export const repositoryService = {
  // Get all repositories connected to a specific project
  async getRepositories(projectId: string): Promise<Repository[]> {
    const res = await fetch(`${API_BASE}/projects/${projectId}/repositories`);
    if (!res.ok) {
      throw new Error('Failed to fetch repositories for project');
    }
    return res.json();
  },

  // Connect a new repository to a project (passing X-User-Email to allow authenticated GitHub App/OAuth usage)
  async connectRepository(projectId: string, githubUrl: string, userEmail?: string): Promise<Repository> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    };
    if (userEmail) {
      headers['X-User-Email'] = userEmail;
    }

    const res = await fetch(`${API_BASE}/projects/${projectId}/repositories`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        repository_url: githubUrl.trim(),
      }),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Failed to connect repository. Make sure it is public and correct.');
    }
    return res.json();
  },

  // Fetch full details of a specific repository on-demand (passing X-User-Email to bypass rate limits using user token)
  async getRepositoryDetail(projectId: string, repositoryId: string, userEmail?: string): Promise<RepositoryDetail> {
    const headers: Record<string, string> = {};
    if (userEmail) {
      headers['X-User-Email'] = userEmail;
    }

    const res = await fetch(`${API_BASE}/projects/${projectId}/repositories/${repositoryId}`, {
      headers,
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Failed to retrieve repository details.');
    }
    return res.json();
  },

  // Force re-analysis of a repository
  async reanalyzeRepository(projectId: string, repositoryId: string, userEmail?: string): Promise<RepositoryDetail> {
    const headers: Record<string, string> = {};
    if (userEmail) {
      headers['X-User-Email'] = userEmail;
    }

    const res = await fetch(`${API_BASE}/projects/${projectId}/repositories/${repositoryId}/reanalyze`, {
      method: 'POST',
      headers,
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Failed to re-analyze repository.');
    }
    return res.json();
  },

  // Fetch paginated commits (passing X-User-Email to bypass rate limits using user token)
  async getCommits(projectId: string, repositoryId: string, page: number = 1, perPage: number = 10, userEmail?: string): Promise<CommitInfo[]> {
    const headers: Record<string, string> = {};
    if (userEmail) {
      headers['X-User-Email'] = userEmail;
    }
    const res = await fetch(
      `${API_BASE}/projects/${projectId}/repositories/${repositoryId}/commits?page=${page}&per_page=${perPage}`,
      { headers }
    );
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Failed to retrieve repository commits.');
    }
    return res.json();
  },
};
export default repositoryService;

