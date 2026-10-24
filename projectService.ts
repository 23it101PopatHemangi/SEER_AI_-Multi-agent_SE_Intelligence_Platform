export interface Project {
  id: string;
  name: string;
  description?: string;
  status: 'Active' | 'Archived' | 'Draft';
  createdAt: string;
  updatedAt: string;
}

const API_BASE = (import.meta.env.VITE_API_URL || 'http://localhost:8000') + '/api';

export const projectService = {
  // Get all projects from the backend database
  async getProjects(): Promise<Project[]> {
    const res = await fetch(`${API_BASE}/projects`);
    if (!res.ok) {
      throw new Error('Failed to fetch projects');
    }
    const data = await res.json();
    return data.map((p: any) => ({
      id: p.id,
      name: p.name,
      description: p.description,
      status: p.status,
      createdAt: p.created_at,
      updatedAt: p.updated_at
    }));
  },

  // Get a project by ID from the backend database
  async getProjectById(id: string): Promise<Project | undefined> {
    const res = await fetch(`${API_BASE}/projects/${id}`);
    if (res.status === 404) {
      return undefined;
    }
    if (!res.ok) {
      throw new Error('Failed to fetch project');
    }
    const p = await res.json();
    return {
      id: p.id,
      name: p.name,
      description: p.description,
      status: p.status,
      createdAt: p.created_at,
      updatedAt: p.updated_at
    };
  },

  // Create a new project in the backend database
  async createProject(name: string, description?: string): Promise<Project> {
    const res = await fetch(`${API_BASE}/projects`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        name: name.trim(),
        description: description?.trim() || '',
      }),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Failed to create project');
    }
    const p = await res.json();
    return {
      id: p.id,
      name: p.name,
      description: p.description,
      status: p.status,
      createdAt: p.created_at,
      updatedAt: p.updated_at
    };
  },
};
