const RAW_API_BASE = String(import.meta.env.VITE_API_URL ?? "").trim().replace(/\/$/, "");

export function apiUrl(path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  if (!RAW_API_BASE) {
    return normalizedPath;
  }
  if (RAW_API_BASE.endsWith("/api") && normalizedPath.startsWith("/api/")) {
    return `${RAW_API_BASE}${normalizedPath.slice(4)}`;
  }
  return `${RAW_API_BASE}${normalizedPath}`;
}
