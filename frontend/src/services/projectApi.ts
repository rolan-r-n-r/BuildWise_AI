/**
 * projectApi.ts — Client services for BuildWise project feasibility persistence (SQLite).
 */
import { API_BASE_URL } from './api';

export interface ProjectSummary {
  id: string;
  name: string;
  description?: string | null;
  latitude: number;
  longitude: number;
  formatted_address?: string | null;
  building_typology?: string | null;
  floors?: number | null;
  built_up_area_sqft?: number | null;
  composite_score?: number | null;
  total_cost_inr?: number | null;
  is_bookmarked: boolean;
  created_at: string;
  updated_at: string;
}

export interface ProjectDetail extends ProjectSummary {
  boundary?: any | null;
  parameters: Record<string, any>;
  analysis_summary?: any | null;
  analysis_data?: any | null;
  floor_plan_data?: any | null;
  site_vision_data?: any | null;
}

export interface ProjectCreatePayload {
  name: string;
  description?: string;
  latitude: number;
  longitude: number;
  formatted_address?: string;
  building_typology?: string;
  floors?: number;
  built_up_area_sqft?: number;
  composite_score?: number;
  total_cost_inr?: number;
  is_bookmarked?: boolean;
  boundary?: any;
  parameters: Record<string, any>;
  analysis_summary?: any;
  analysis_data?: any;
  floor_plan_data?: any;
  site_vision_data?: any;
}

export interface ProjectUpdatePayload {
  name?: string;
  description?: string;
  is_bookmarked?: boolean;
}

export interface ProjectListResult {
  items: ProjectSummary[];
  total: number;
}

export async function fetchProjects(params?: {
  bookmarked?: boolean;
  search?: string;
  limit?: number;
  offset?: number;
}): Promise<ProjectListResult> {
  const query = new URLSearchParams();
  if (params?.bookmarked) query.set('bookmarked', 'true');
  if (params?.search && params.search.trim()) query.set('search', params.search.trim());
  if (params?.limit) query.set('limit', String(params.limit));
  if (params?.offset) query.set('offset', String(params.offset));

  const qs = query.toString();
  const url = `${API_BASE_URL}/api/projects${qs ? `?${qs}` : ''}`;
  const resp = await fetch(url);
  if (!resp.ok) {
    throw new Error(`Failed to list projects (HTTP ${resp.status})`);
  }
  return resp.json();
}

export async function fetchProjectById(projectId: string): Promise<ProjectDetail> {
  const resp = await fetch(`${API_BASE_URL}/api/projects/${encodeURIComponent(projectId)}`);
  if (!resp.ok) {
    throw new Error(`Failed to load project ${projectId} (HTTP ${resp.status})`);
  }
  return resp.json();
}

export interface ProjectApiError extends Error {
  status?: number;
  code?: string;
  existingId?: string;
}

export async function saveProject(
  payload: ProjectCreatePayload,
  options?: { overwrite?: boolean },
): Promise<ProjectDetail> {
  const qs = options?.overwrite ? '?overwrite=true' : '';
  const resp = await fetch(`${API_BASE_URL}/api/projects${qs}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    const errorBody = await resp.json().catch(() => ({}));
    const message =
      (typeof errorBody.detail === 'object' && errorBody.detail?.message) ||
      errorBody.detail ||
      `Failed to save project (HTTP ${resp.status})`;
    const err: ProjectApiError = new Error(message);
    err.status = resp.status;
    if (typeof errorBody.detail === 'object' && errorBody.detail) {
      err.code = errorBody.detail.code;
      err.existingId = errorBody.detail.existing_id;
    }
    throw err;
  }
  return resp.json();
}

export async function overwriteProject(
  projectId: string,
  payload: ProjectCreatePayload,
): Promise<ProjectDetail> {
  const resp = await fetch(`${API_BASE_URL}/api/projects/${encodeURIComponent(projectId)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    const errorBody = await resp.json().catch(() => ({}));
    throw new Error(errorBody.detail || `Failed to update study (HTTP ${resp.status})`);
  }
  return resp.json();
}

export async function updateProject(
  projectId: string,
  patch: ProjectUpdatePayload,
): Promise<ProjectDetail> {
  const resp = await fetch(`${API_BASE_URL}/api/projects/${encodeURIComponent(projectId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  });
  if (!resp.ok) {
    throw new Error(`Failed to update project ${projectId} (HTTP ${resp.status})`);
  }
  return resp.json();
}

export async function deleteProject(projectId: string): Promise<void> {
  const resp = await fetch(`${API_BASE_URL}/api/projects/${encodeURIComponent(projectId)}`, {
    method: 'DELETE',
  });
  if (!resp.ok) {
    throw new Error(`Failed to delete project ${projectId} (HTTP ${resp.status})`);
  }
}
