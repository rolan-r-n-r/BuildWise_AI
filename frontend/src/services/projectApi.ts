/**
 * projectApi.ts — Client services for BuildWise project feasibility persistence (SQLite).
 * Enforces authenticated multi-user isolation by including session credentials in all requests.
 */
import { API_BASE_URL } from './api';

export interface ProjectSummary {
  id: string;
  user_id?: string | null;
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

export interface ProjectApiError extends Error {
  status?: number;
  code?: string;
  existingId?: string;
}

async function handleApiError(resp: Response, fallbackMessage: string): Promise<never> {
  const errorBody = await resp.json().catch(() => ({}));
  const message =
    (typeof errorBody.detail === 'object' && errorBody.detail?.message) ||
    errorBody.detail ||
    fallbackMessage;
  const err: ProjectApiError = new Error(message);
  err.status = resp.status;
  if (typeof errorBody.detail === 'object' && errorBody.detail) {
    err.code = errorBody.detail.code;
    err.existingId = errorBody.detail.existing_id;
  }
  throw err;
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
  const resp = await fetch(url, {
    credentials: 'include',
  });
  if (!resp.ok) {
    await handleApiError(resp, `Failed to list projects (HTTP ${resp.status})`);
  }
  return resp.json();
}

export async function fetchProjectById(projectId: string): Promise<ProjectDetail> {
  const resp = await fetch(`${API_BASE_URL}/api/projects/${encodeURIComponent(projectId)}`, {
    credentials: 'include',
  });
  if (!resp.ok) {
    await handleApiError(resp, `Failed to load project ${projectId} (HTTP ${resp.status})`);
  }
  return resp.json();
}

export async function saveProject(
  payload: ProjectCreatePayload,
  options?: { overwrite?: boolean },
): Promise<ProjectDetail> {
  const qs = options?.overwrite ? '?overwrite=true' : '';
  const resp = await fetch(`${API_BASE_URL}/api/projects${qs}`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    await handleApiError(resp, `Failed to save project (HTTP ${resp.status})`);
  }
  return resp.json();
}

export async function overwriteProject(
  projectId: string,
  payload: ProjectCreatePayload,
): Promise<ProjectDetail> {
  const resp = await fetch(`${API_BASE_URL}/api/projects/${encodeURIComponent(projectId)}`, {
    method: 'PUT',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    await handleApiError(resp, `Failed to update study (HTTP ${resp.status})`);
  }
  return resp.json();
}

export async function updateProject(
  projectId: string,
  patch: ProjectUpdatePayload,
): Promise<ProjectDetail> {
  const resp = await fetch(`${API_BASE_URL}/api/projects/${encodeURIComponent(projectId)}`, {
    method: 'PATCH',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  });
  if (!resp.ok) {
    await handleApiError(resp, `Failed to update project ${projectId} (HTTP ${resp.status})`);
  }
  return resp.json();
}

export async function deleteProject(projectId: string): Promise<void> {
  const resp = await fetch(`${API_BASE_URL}/api/projects/${encodeURIComponent(projectId)}`, {
    method: 'DELETE',
    credentials: 'include',
  });
  if (!resp.ok) {
    await handleApiError(resp, `Failed to delete project ${projectId} (HTTP ${resp.status})`);
  }
}

export async function downloadProjectPdfReport(projectId: string, projectName?: string): Promise<void> {
  const resp = await fetch(`${API_BASE_URL}/api/projects/${encodeURIComponent(projectId)}/report`, {
    credentials: 'include',
  });
  if (!resp.ok) {
    await handleApiError(resp, `Failed to download project report (HTTP ${resp.status})`);
  }
  const blob = await resp.blob();
  const downloadUrl = window.URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = downloadUrl;
  const safeName = (projectName || 'Report').replace(/[^a-zA-Z0-9_-]/g, '_');
  link.download = `BuildWise_${safeName}.pdf`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => window.URL.revokeObjectURL(downloadUrl), 1000);
}
