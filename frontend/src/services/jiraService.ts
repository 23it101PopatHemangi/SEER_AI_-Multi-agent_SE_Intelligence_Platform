export interface JiraProjectOption {
  id: string;
  key: string;
  name: string;
  project_type_key?: string;
  avatar_url?: string;
}

export interface JiraConnection {
  id: string;
  project_id: string;
  jira_project_key: string;
  jira_project_name: string;
  jira_project_id?: string;
  jira_cloud_id?: string;
  site_url?: string;
  connected_at: string;
  updated_at: string;
}

export interface JiraRepositoryConnectionStatus {
  repository_id: string;
  repository_name: string;
  connection?: JiraConnection & { repository_id: string };
  effective_connection?: JiraConnection;
  uses_project_fallback: boolean;
}

export interface JiraStatusResponse {
  authenticated: boolean;
  connected: boolean;
  jira_user?: string;
  connection?: JiraConnection;
  available_projects: JiraProjectOption[];
}

export interface JiraProjectDestination {
  key: string;
  name: string;
  id?: string;
}

export interface JiraConnectRequest {
  jira_project_key: string;
  jira_project_name: string;
  jira_project_id?: string;
  jira_cloud_id?: string;
  site_url?: string;
}

const API_BASE = (import.meta.env.VITE_API_URL || 'http://localhost:8000') + '/api';

export const jiraService = {
  // Get Atlassian OAuth redirect URL from backend
  async getAuthUrl(userEmail: string, projectId: string): Promise<string> {
    const res = await fetch(
      `${API_BASE}/jira/auth-url?user_email=${encodeURIComponent(userEmail)}&project_id=${encodeURIComponent(projectId)}`
    );
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to fetch Jira authorization URL.');
    }
    const data = await res.json();
    return data.auth_url;
  },

  // Get current Jira connection and authentication status
  async getConnectionStatus(projectId: string, userEmail?: string): Promise<JiraStatusResponse> {
    const headers: Record<string, string> = {
      Accept: 'application/json',
    };
    if (userEmail) {
      headers['X-User-Email'] = userEmail;
    }

    const res = await fetch(`${API_BASE}/jira/projects/${encodeURIComponent(projectId)}/status`, {
      headers,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to fetch Jira connection status.');
    }
    return res.json();
  },

  async getRepositoryConnection(projectId: string, repositoryId: string): Promise<JiraRepositoryConnectionStatus> {
    const res = await fetch(
      `${API_BASE}/jira/projects/${encodeURIComponent(projectId)}/repositories/${encodeURIComponent(repositoryId)}/status`
    );
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to fetch repository Jira mapping.');
    }
    return res.json();
  },

  async connectRepository(
    projectId: string,
    repositoryId: string,
    payload: JiraConnectRequest,
    userEmail?: string
  ): Promise<JiraConnection> {
    const headers: Record<string, string> = { 'Content-Type': 'application/json', Accept: 'application/json' };
    if (userEmail) headers['X-User-Email'] = userEmail;
    const res = await fetch(
      `${API_BASE}/jira/projects/${encodeURIComponent(projectId)}/repositories/${encodeURIComponent(repositoryId)}/connect`,
      { method: 'POST', headers, body: JSON.stringify(payload) }
    );
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to map repository to Jira project.');
    }
    return res.json();
  },

  async disconnectRepository(projectId: string, repositoryId: string): Promise<void> {
    const res = await fetch(
      `${API_BASE}/jira/projects/${encodeURIComponent(projectId)}/repositories/${encodeURIComponent(repositoryId)}/disconnect`,
      { method: 'POST', headers: { Accept: 'application/json' } }
    );
    if (!res.ok) throw new Error('Failed to remove repository Jira mapping.');
  },

  // Fetch available Jira projects for authenticated user
  async getAvailableProjects(userEmail: string): Promise<JiraProjectOption[]> {
    const res = await fetch(`${API_BASE}/jira/projects`, {
      headers: {
        'X-User-Email': userEmail,
        Accept: 'application/json',
      },
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to fetch available Jira projects.');
    }
    return res.json();
  },

  // Connect a selected Jira project to the SEER project
  async connectProject(
    projectId: string,
    payload: JiraConnectRequest,
    userEmail?: string
  ): Promise<JiraConnection> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    };
    if (userEmail) {
      headers['X-User-Email'] = userEmail;
    }

    const res = await fetch(`${API_BASE}/jira/projects/${encodeURIComponent(projectId)}/connect`, {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to connect Jira project.');
    }
    return res.json();
  },

  // Disconnect the Jira project from this SEER project
  async disconnectProject(projectId: string): Promise<void> {
    const res = await fetch(`${API_BASE}/jira/projects/${encodeURIComponent(projectId)}/disconnect`, {
      method: 'POST',
      headers: {
        Accept: 'application/json',
      },
    });
    if (!res.ok) {
      throw new Error('Failed to disconnect Jira project.');
    }
  },

  // Disconnect user's Atlassian account token completely
  async disconnectAccount(userEmail: string): Promise<void> {
    const res = await fetch(`${API_BASE}/jira/disconnect`, {
      method: 'POST',
      headers: {
        'X-User-Email': userEmail,
        Accept: 'application/json',
      },
    });
    if (!res.ok) {
      throw new Error('Failed to disconnect Jira account.');
    }
  },

  async getProjectDestinations(projectId: string): Promise<JiraProjectDestination[]> {
    const res = await fetch(`${API_BASE}/jira/projects/${encodeURIComponent(projectId)}/destinations`, {
      headers: { Accept: 'application/json' },
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to load mapped Jira projects.');
    }
    return res.json();
  },
};

export default jiraService;
