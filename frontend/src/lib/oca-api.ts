export * from './api';

const API_BASE = '/api';

export interface OCAMaterialSuggestion {
  material_name: string;
  family: string;
  flammability_rating: string;
  source_ref: string;
}

export async function ocaSuggestMaterials(
  query: string,
  limit = 10,
): Promise<OCAMaterialSuggestion[]> {
  const params = new URLSearchParams({ q: query, limit: String(limit) });
  const response = await fetch(`${API_BASE}/oca/materials/suggest?${params.toString()}`);
  if (!response.ok) return [];
  return response.json();
}

