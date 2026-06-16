const rawBase = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ?? "";

/** API origin without trailing slash. Empty string uses same-origin proxy paths. */
export function getApiBase(): string {
  return rawBase;
}

export function apiUrl(path: string): string {
  const base = getApiBase();
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return base ? `${base}${normalized}` : `/api${normalized}`;
}

export function wsUrl(path: string): string {
  const base = getApiBase();
  const normalized = path.startsWith("/") ? path : `/${path}`;

  if (base) {
    const url = new URL(base);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    url.pathname = normalized;
    url.search = "";
    url.hash = "";
    return url.toString();
  }

  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}${normalized}`;
}
