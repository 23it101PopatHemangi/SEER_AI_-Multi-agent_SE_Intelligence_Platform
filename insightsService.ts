export interface InsightCitation {
  id: string;
  type: 'jira' | 'github' | 'srs' | 'architecture';
  title: string;
  url?: string;
}

export interface InsightResponse {
  answer: string;
  findings: string[];
  actions: string[];
  citations: InsightCitation[];
  sources: { type: string; available: boolean }[];
  unavailable: string[];
  mode: 'gemini' | 'rule-based';
}

export interface JiraGraphNode {
  id: string;
  label: string;
  title: string;
  status: string;
  priority: string;
  risk: boolean;
  blocked: boolean;
  url?: string;
}

export interface JiraGraphEdge {
  id: string;
  source: string;
  target: string;
  relationship: string;
}

export interface JiraDependencyGraph {
  nodes: JiraGraphNode[];
  edges: JiraGraphEdge[];
  unavailable: string[];
  impact: string;
}

const API_BASE = (import.meta.env.VITE_API_URL || 'http://localhost:8000') + '/api';

export const insightsService = {
  async ask(projectId: string, question: string, userEmail?: string): Promise<InsightResponse> {
    const headers: Record<string, string> = { 'Content-Type': 'application/json', Accept: 'application/json' };
    if (userEmail) headers['X-User-Email'] = userEmail;
    const response = await fetch(`${API_BASE}/projects/${encodeURIComponent(projectId)}/insights`, {
      method: 'POST', headers, body: JSON.stringify({ question }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || 'Unable to retrieve project evidence.');
    return payload;
  },

  async getJiraDependencyGraph(projectId: string, userEmail?: string): Promise<JiraDependencyGraph> {
    const headers: Record<string, string> = { Accept: 'application/json' };
    if (userEmail) headers['X-User-Email'] = userEmail;
    const response = await fetch(`${API_BASE}/projects/${encodeURIComponent(projectId)}/insights/jira-dependency-graph`, { headers });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || 'Unable to load Jira dependency graph.');
    return payload;
  },
};