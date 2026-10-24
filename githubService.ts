export interface GitHubRepoInfo {
  name: string;
  full_name: string;
  html_url: string;
  description?: string;
}

export interface GitHubStatusResponse {
  connected: boolean;
  github_username?: string;
  repositories?: GitHubRepoInfo[];
}

const API_BASE = (import.meta.env.VITE_API_URL || 'http://localhost:8000') + '/api';

export const githubService = {
  // Get redirect OAuth URL from backend
  async getAuthUrl(userEmail: string, projectId: string): Promise<string> {
    const res = await fetch(
      `${API_BASE}/github/auth-url?user_email=${encodeURIComponent(userEmail)}&project_id=${encodeURIComponent(projectId)}`
    );
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Failed to fetch GitHub authorization URL.');
    }
    const data = await res.json();
    return data.auth_url;
  },

  // Get current GitHub connection status and repository listing
  async getConnectionStatus(userEmail: string): Promise<GitHubStatusResponse> {
    const res = await fetch(`${API_BASE}/github/status`, {
      headers: {
        'X-User-Email': userEmail,
        'Accept': 'application/json',
      },
    });
    if (!res.ok) {
      throw new Error('Failed to fetch GitHub connection status.');
    }
    return res.json();
  },

  // Disconnect GitHub account integration
  async disconnectAccount(userEmail: string): Promise<void> {
    const res = await fetch(`${API_BASE}/github/disconnect`, {
      method: 'POST',
      headers: {
        'X-User-Email': userEmail,
        'Accept': 'application/json',
      },
    });
    if (!res.ok) {
      throw new Error('Failed to disconnect GitHub account.');
    }
  },
};
export default githubService;
