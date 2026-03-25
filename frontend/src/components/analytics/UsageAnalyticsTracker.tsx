import { useEffect, useMemo, useRef } from 'react';
import { useLocation, useNavigationType } from 'react-router-dom';

const SESSION_STORAGE_KEY = 'boundstate:mira-usage-session:v1';

type RouteDescriptor = {
  moduleId: string;
  pageLabel: string;
};

const ROUTE_DESCRIPTORS: Array<{ prefix: string; descriptor: RouteDescriptor }> = [
  { prefix: '/oca/system-builder', descriptor: { moduleId: 'oca-system-builder', pageLabel: 'OCA System Builder' } },
  { prefix: '/oca/workbench', descriptor: { moduleId: 'oca-workbench', pageLabel: 'OCA Workbench' } },
  { prefix: '/gas-compatibility', descriptor: { moduleId: 'gas-compatibility', pageLabel: 'Gas Compatibility' } },
  { prefix: '/galvanic-compatibility', descriptor: { moduleId: 'galvanic-compatibility', pageLabel: 'Galvanic Compatibility' } },
  { prefix: '/fracture-control', descriptor: { moduleId: 'fracture-control', pageLabel: 'Fracture Control' } },
  { prefix: '/mp-plan', descriptor: { moduleId: 'mp-plan', pageLabel: 'M&P Plan' } },
  { prefix: '/dt-editor', descriptor: { moduleId: 'dt-editor', pageLabel: 'DT Editor' } },
  { prefix: '/miul', descriptor: { moduleId: 'miul', pageLabel: 'MIUL Builder' } },
  { prefix: '/mua-v10', descriptor: { moduleId: 'mua-v10', pageLabel: 'MUA Writer' } },
  { prefix: '/query', descriptor: { moduleId: 'query', pageLabel: 'Query' } },
  { prefix: '/chat', descriptor: { moduleId: 'chat', pageLabel: 'MIRA Chat' } },
  { prefix: '/test-classes', descriptor: { moduleId: 'test-classes', pageLabel: 'MAPTIS Search' } },
  { prefix: '/tocr', descriptor: { moduleId: 'tocr', pageLabel: 'TOCR Review' } },
  { prefix: '/', descriptor: { moduleId: 'knowledge-twins', pageLabel: 'Knowledge Twins' } },
];

function createSessionId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `mira-${Math.random().toString(36).slice(2)}-${Date.now().toString(36)}`;
}

function getClientSessionId(): string {
  if (typeof window === 'undefined') {
    return 'server-render';
  }

  try {
    const existing = window.localStorage.getItem(SESSION_STORAGE_KEY);
    if (existing) {
      return existing;
    }
    const next = createSessionId();
    window.localStorage.setItem(SESSION_STORAGE_KEY, next);
    return next;
  } catch {
    return createSessionId();
  }
}

function resolveRouteDescriptor(pathname: string): RouteDescriptor {
  const match = ROUTE_DESCRIPTORS.find(({ prefix }) => (
    prefix === '/'
      ? pathname === '/'
      : pathname === prefix || pathname.startsWith(`${prefix}/`)
  ));
  return match?.descriptor ?? { moduleId: 'unknown', pageLabel: pathname };
}

export function UsageAnalyticsTracker() {
  const location = useLocation();
  const navigationType = useNavigationType();
  const lastSentKeyRef = useRef<string | null>(null);
  const clientSessionId = useMemo(() => getClientSessionId(), []);

  useEffect(() => {
    const path = location.pathname || '/';
    const eventKey = `${navigationType}:${path}`;
    if (lastSentKeyRef.current === eventKey) {
      return;
    }
    lastSentKeyRef.current = eventKey;

    const descriptor = resolveRouteDescriptor(path);
    const payload = {
      event_type: 'pageview',
      path,
      module_id: descriptor.moduleId,
      page_label: descriptor.pageLabel,
      navigation_type: navigationType || 'unknown',
      client_session_id: clientSessionId,
      referrer: typeof document !== 'undefined' ? document.referrer || null : null,
    };

    void window.fetch('/api/usage/events', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      keepalive: true,
    }).catch(() => {
      // Usage analytics should never block the UI.
    });
  }, [clientSessionId, location.pathname, navigationType]);

  return null;
}

