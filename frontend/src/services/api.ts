import type {
  AnalysisResponse,
  SiteVisionRequest,
  SiteVisionResponse,
  FloorPlanRequest,
  FloorPlanResponse,
  RemediationResponse,
  AdvisoryResponse,
  ReportRequestPayload,
  ExtractedClientConstraints,
} from './types';

export const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export async function downloadFloorplanDossier(
  payload: Record<string, any>
): Promise<void> {
  const resp = await fetch(`${API_BASE_URL}/api/generate-floorplan?format=pdf`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });

  if (!resp.ok) {
    let errorDetail = `PDF dossier export failed with status: ${resp.status}`;
    try {
      const errData = await resp.json();
      if (errData?.detail) errorDetail = errData.detail;
    } catch {
      // ignore
    }
    throw new Error(errorDetail);
  }

  const blob = await resp.blob();
  const downloadUrl = window.URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = downloadUrl;
  const typTag = payload.building_typology ? `_${payload.building_typology}` : '';
  const floorsTag = payload.floors ? `_${payload.floors}F` : '';
  link.download = `BuildWise_Architectural_Dossier${typTag}${floorsTag}.pdf`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => window.URL.revokeObjectURL(downloadUrl), 1000);
}

export async function submitSiteVision(
  request: SiteVisionRequest,
  signal?: AbortSignal
): Promise<SiteVisionResponse> {
  const resp = await fetch(`${API_BASE_URL}/api/site-vision`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
    signal,
  });

  if (!resp.ok) {
    const errorData = await resp.json().catch(() => ({}));
    throw new Error(errorData.detail || `Site vision request failed with status: ${resp.status}`);
  }

  return resp.json();
}

export async function generateFloorPlan(
  request: FloorPlanRequest,
  signal?: AbortSignal
): Promise<FloorPlanResponse> {
  const resp = await fetch(`${API_BASE_URL}/api/generate-floorplan`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
    signal,
  });

  if (!resp.ok) {
    const errorData = await resp.json().catch(() => ({}));
    throw new Error(errorData.detail || `Floor plan generation failed with status: ${resp.status}`);
  }

  return resp.json();
}

/**
 * Engine dry-runs for the plan's remediation options.
 *
 * The options' existence and every predicted number come from this response;
 * the advisor may word them, never change them.
 */
export async function fetchRemediationOptions(
  payload: {
    request: FloorPlanRequest;
    warnings: string[];
    plan_verdict?: string | null;
    placed_rooms?: string[];
    rotation_alternatives?: Array<Record<string, any>>;
    scheme_alternatives?: Array<Record<string, any>>;
    selected_scheme_id?: string | null;
    baseline?: { warning_count: number; failure_count: number; relaxation_count: number; plate_area_m2?: number | null };
    plan_hash?: string;
  },
  signal?: AbortSignal,
): Promise<RemediationResponse> {
  const resp = await fetch(`${API_BASE_URL}/api/floorplan/remediation`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal,
  });
  if (!resp.ok) {
    const errorData = await resp.json().catch(() => ({}));
    throw new Error(errorData.detail || `Remediation dry-run failed with status: ${resp.status}`);
  }
  return resp.json();
}

/** Advisory wording for the plan's blocking reasons and measured options. */
export async function fetchPlanAdvisory(
  payload: {
    plan_hash: string;
    plan_verdict: string;
    summary_line: string;
    blocking_reasons: string[];
    warning_counts: Record<string, number>;
    options: Array<{ id: string; title: string; effect_line: string }>;
    provider?: string;
  },
  signal?: AbortSignal,
): Promise<AdvisoryResponse> {
  const resp = await fetch(`${API_BASE_URL}/api/floorplan/advisory`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal,
  });
  if (!resp.ok) {
    const errorData = await resp.json().catch(() => ({}));
    throw new Error(errorData.detail || `Advisor unavailable (HTTP ${resp.status})`);
  }
  return resp.json();
}


export async function downloadPdfReport(
  payloadOrAnalysis: ReportRequestPayload | AnalysisResponse,
  floorplanData?: FloorPlanResponse | null
): Promise<void> {
  const isUnified = 'analysis_data' in payloadOrAnalysis;
  const analysisData = isUnified ? payloadOrAnalysis.analysis_data : payloadOrAnalysis;
  const siteVision = isUnified
    ? (payloadOrAnalysis.site_vision ?? null)
    : (payloadOrAnalysis.site_vision ?? null);
  const floorPlan = isUnified
    ? (payloadOrAnalysis.floor_plan ?? null)
    : (floorplanData ?? payloadOrAnalysis.floorplan ?? null);

  const requestBody = {
    analysis_data: analysisData,
    site_vision: siteVision,
    floor_plan: floorPlan,
  };

  const resp = await fetch(`${API_BASE_URL}/api/report`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(requestBody),
  });

  if (!resp.ok) {
    let errorDetail = `Report generation failed with status: ${resp.status}`;
    try {
      const errData = await resp.json();
      if (errData?.detail) errorDetail = errData.detail;
    } catch {
      // ignore json parse error
    }
    throw new Error(errorDetail);
  }

  const blob = await resp.blob();
  const downloadUrl = window.URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = downloadUrl;
  const lat = analysisData.coordinates?.latitude != null ? analysisData.coordinates.latitude.toFixed(2) : '0.00';
  const lon = analysisData.coordinates?.longitude != null ? analysisData.coordinates.longitude.toFixed(2) : '0.00';
  link.download = `BuildWise_Report_${lat}_${lon}.pdf`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(downloadUrl);
}

export async function parseRequirements(
  requirementsText: string,
  aiProvider: string = 'groq',
  signal?: AbortSignal
): Promise<ExtractedClientConstraints> {
  try {
    const resp = await fetch(`${API_BASE_URL}/api/parse-requirements`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        requirements_text: requirementsText,
        ai_provider: aiProvider,
      }),
      signal,
    });

    if (resp.ok) {
      return await resp.json();
    }
  } catch (err) {
    // Network or server error: fall through to client-side fallback
  }

  // Client-side fallback if backend unreachable
  return parseRequirementsClientFallback(requirementsText);
}

export function parseRequirementsClientFallback(text: string): ExtractedClientConstraints {
  const clean = text.toLowerCase();

  // Bedroom count
  const bedMatch = clean.match(/(\d+)\s*(?:bhk|bed|bedroom|br)/);
  let bedCount = bedMatch ? parseInt(bedMatch[1], 10) : 2;
  bedCount = Math.max(1, Math.min(6, bedCount));

  // Bathroom count
  const bathMatch = clean.match(/(\d+)\s*(?:bath|bathroom|toilet|wc)/);
  let bathCount = bathMatch ? parseInt(bathMatch[1], 10) : (bedCount >= 2 ? 2 : 1);
  if (clean.includes('powder room') || clean.includes('powder') || clean.includes('guest toilet')) {
    bathCount += 1;
  }
  bathCount = Math.max(1, Math.min(6, bathCount));

  // Specialized spaces
  const spaces: string[] = [];
  if (clean.includes('office') || clean.includes('wfh') || clean.includes('work from home')) spaces.push('home_office');
  if (clean.includes('study') || clean.includes('library')) spaces.push('study');
  if ((clean.includes('pooja') || clean.includes('puja') || clean.includes('mandir')) && !clean.includes('no puja') && !clean.includes('no pooja')) spaces.push('pooja_room');
  if (clean.includes('powder') || clean.includes('guest bath')) spaces.push('powder_room');
  if (clean.includes('utility') || clean.includes('laundry') || clean.includes('wash area')) spaces.push('utility_room');
  if (clean.includes('servant') || clean.includes('maid')) spaces.push('servant_room');
  if (clean.includes('gym') || clean.includes('fitness')) spaces.push('gym');
  if (clean.includes('theatre') || clean.includes('theater')) spaces.push('home_theatre');
  if ((clean.includes('balcony') || clean.includes('deck')) && !clean.includes('no balcony')) spaces.push('balcony');
  if (clean.includes('terrace')) spaces.push('terrace');
  if (clean.includes('open kitchen')) spaces.push('open_kitchen');

  const adjacencies: { room_a: string; room_b: string; relationship: 'connected' | 'adjacent' | 'separated' }[] = [];
  if (spaces.includes('open_kitchen') || clean.includes('open kitchen')) {
    adjacencies.push({ room_a: 'kitchen', room_b: 'dining', relationship: 'connected' });
  }

  const orientations: { space: string; preferred_facing: 'North' | 'East' | 'South' | 'West' | 'North-East' | 'South-East' | 'South-West' | 'North-West' }[] = [];
  if (clean.includes('north') && (clean.includes('study') || clean.includes('office'))) {
    orientations.push({ space: 'study', preferred_facing: 'North' });
  }
  if (clean.includes('east') && clean.includes('kitchen')) {
    orientations.push({ space: 'kitchen', preferred_facing: 'East' });
  }

  return {
    target_bedroom_count: bedCount,
    target_bathroom_count: bathCount,
    specialized_spaces: Array.from(new Set(spaces)),
    spatial_adjacencies: adjacencies,
    orientation_preferences: orientations,
    explicit_exclusions: clean.includes('no puja') ? ['no_pooja'] : [],
    raw_notes: text,
    extraction_source: 'regex_fallback',
  };
}
