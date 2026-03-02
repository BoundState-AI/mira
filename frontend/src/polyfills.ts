// Browser shims for legacy deps (e.g. amazon-cognito-identity-js -> buffer)
const g = globalThis as typeof globalThis & {
  global?: typeof globalThis;
  process?: { env: Record<string, string | undefined> };
};

if (!g.global) {
  g.global = globalThis;
}

if (!g.process) {
  g.process = { env: {} };
}
