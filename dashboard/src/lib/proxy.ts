const SEGMENT = /^[A-Za-z0-9_-]+$/;

// Builds the backend URL for a proxied request, or null if the path is not safe.
// The browser can only ever reach /api/<simple-words> on the configured backend.
export function backendUrl(base: string, segments: string[], search: string): URL | null {
  if (segments.length === 0 || !segments.every((segment) => SEGMENT.test(segment))) return null;
  const url = new URL(`${base.replace(/\/+$/, "")}/api/${segments.join("/")}`);
  url.search = search;
  return url;
}