import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  AuthenticationDetails,
  CognitoUser,
  CognitoUserPool,
  CognitoUserSession,
} from "amazon-cognito-identity-js";
import { jwtDecode } from "jwt-decode";

type AuthStage =
  | "login"
  | "new-password"
  | "mfa-setup"
  | "mfa-verify"
  | "forgot-password-request"
  | "forgot-password-confirm";

type SessionMode = "none" | "local" | "user-pool" | "hosted-ui";

interface AuthUser {
  username: string;
  email: string;
  groups: string[];
  role: string;
  itarAccess: string;
  usPersonVerified: boolean | null;
  isItarCleared: boolean;
  isAdmin: boolean;
  isApproved: boolean;
}

interface AuthContextValue {
  user: AuthUser | null;
  token: string | null;
  loading: boolean;
  stage: AuthStage;
  pendingUsername: string;
  mfaSecret: string;
  passwordResetDelivery: string;
  authHeaders: Record<string, string>;
  supportsPasswordLogin: boolean;
  supportsFederatedLogin: boolean;
  federatedLoginLabel: string;
  login: (username: string, password: string) => Promise<void>;
  loginWithFederation: (returnTo?: string) => Promise<void>;
  completeFederatedLogin: (callbackUrl?: string) => Promise<string>;
  completeNewPassword: (newPassword: string) => Promise<void>;
  verifyMfa: (code: string) => Promise<void>;
  verifyMfaSetup: (code: string) => Promise<void>;
  goToForgotPassword: () => void;
  requestPasswordReset: (username: string) => Promise<void>;
  confirmPasswordReset: (code: string, newPassword: string) => Promise<void>;
  goToLogin: () => void;
  logout: () => void;
}

type AccessTokenClaims = {
  exp: number;
  sub?: string;
  username?: string;
  client_id?: string;
  scope?: string;
  "cognito:groups"?: string[] | string;
};

type IdTokenClaims = {
  email?: string;
  "cognito:username"?: string;
  "custom:role"?: string;
  "custom:itar_access"?: string;
  "custom:us_person_verified"?: string;
};

type HostedUiTokenResponse = {
  access_token?: string;
  id_token?: string;
  refresh_token?: string;
  expires_in?: number;
  token_type?: string;
  error?: string;
  error_description?: string;
};

type HostedUiPkceState = {
  state: string;
  verifier: string;
  returnTo: string;
};

type HostedUiSession = {
  accessToken: string;
  idToken: string;
  refreshToken: string | null;
  expiresAt: number;
};

function sanitizeEnvValue(value: string | undefined): string {
  const trimmed = (value || "").trim();
  if (!trimmed) return "";
  const lower = trimmed.toLowerCase();
  if (lower === "none" || lower === "null" || lower === "undefined") return "";
  return trimmed;
}

function envFlagEnabled(value: string | undefined, defaultValue = false): boolean {
  const trimmed = sanitizeEnvValue(value);
  if (!trimmed) return defaultValue;
  return ["1", "true", "yes", "on"].includes(trimmed.toLowerCase());
}

function parseCsvEnv(value: string | undefined): string[] {
  return sanitizeEnvValue(value)
    .split(",")
    .map((entry) => entry.trim())
    .filter(Boolean);
}

function normalizeUrlOrigin(value: string): string {
  const trimmed = sanitizeEnvValue(value);
  if (!trimmed) return "";
  return trimmed.replace(/\/+$/, "");
}

function normalizeHostedUiDomain(value: string): string {
  const trimmed = sanitizeEnvValue(value);
  if (!trimmed) return "";
  const withoutProtocol = trimmed.replace(/^https?:\/\//i, "");
  return withoutProtocol.replace(/\/+$/, "");
}

function safeSessionStorage(): Storage | undefined {
  if (typeof window === "undefined") return undefined;
  return window.sessionStorage;
}

function base64UrlEncode(bytes: Uint8Array): string {
  let binary = "";
  bytes.forEach((value) => {
    binary += String.fromCharCode(value);
  });
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function randomUrlSafeString(byteLength = 32): string {
  const bytes = new Uint8Array(byteLength);
  crypto.getRandomValues(bytes);
  return base64UrlEncode(bytes);
}

async function sha256Base64Url(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return base64UrlEncode(new Uint8Array(digest));
}

function safeJsonParse<T>(value: string | null): T | null {
  if (!value) return null;
  try {
    return JSON.parse(value) as T;
  } catch {
    return null;
  }
}

function formatOauthError(payload: HostedUiTokenResponse | null, fallback: string): string {
  const description = payload?.error_description || payload?.error;
  return description ? description.replace(/\+/g, " ") : fallback;
}

const RAW_USER_POOL_ID =
  (import.meta.env.VITE_COGNITO_USER_POOL_ID as string | undefined) ||
  (import.meta.env.REACT_APP_COGNITO_USER_POOL_ID as string | undefined) ||
  "";
const RAW_CLIENT_ID =
  (import.meta.env.VITE_COGNITO_CLIENT_ID as string | undefined) ||
  (import.meta.env.REACT_APP_COGNITO_CLIENT_ID as string | undefined) ||
  "";

const USER_POOL_ID = sanitizeEnvValue(RAW_USER_POOL_ID);
const CLIENT_ID = sanitizeEnvValue(RAW_CLIENT_ID);
const USER_POOL_ID_PATTERN = /^[-a-z0-9]+_[A-Za-z0-9]+$/i;
const CLIENT_ID_PATTERN = /^[A-Za-z0-9]+$/;
const IS_VALID_USER_POOL_ID = USER_POOL_ID_PATTERN.test(USER_POOL_ID);
const IS_VALID_CLIENT_ID = CLIENT_ID_PATTERN.test(CLIENT_ID);
const HAS_VALID_COGNITO_CONFIG = IS_VALID_USER_POOL_ID && IS_VALID_CLIENT_ID;

const AUTH_BYPASS_LOCAL =
  import.meta.env.DEV &&
  !["0", "false", "no"].includes(
    String(import.meta.env.VITE_AUTH_BYPASS_LOCAL ?? "true")
      .trim()
      .toLowerCase(),
  );

const API_AUTH_HOSTS = (
  (import.meta.env.VITE_API_AUTH_HOSTS as string | undefined) || "127.0.0.1:8000,localhost:8000"
)
  .split(",")
  .map((entry) => entry.trim())
  .filter(Boolean);

const HOSTED_UI_DOMAIN = normalizeHostedUiDomain(
  import.meta.env.VITE_COGNITO_HOSTED_UI_DOMAIN as string | undefined,
);
const HOSTED_UI_REDIRECT_URI = normalizeUrlOrigin(
  import.meta.env.VITE_COGNITO_REDIRECT_URI as string | undefined,
);
const HOSTED_UI_LOGOUT_URI = normalizeUrlOrigin(
  import.meta.env.VITE_COGNITO_LOGOUT_URI as string | undefined,
);
const HOSTED_UI_SCOPE =
  sanitizeEnvValue(import.meta.env.VITE_COGNITO_OAUTH_SCOPES as string | undefined) ||
  "openid email aws.cognito.signin.user.admin";
const HOSTED_UI_IDENTITY_PROVIDER = sanitizeEnvValue(
  import.meta.env.VITE_COGNITO_IDENTITY_PROVIDER as string | undefined,
);
const HOSTED_UI_BUTTON_LABEL =
  sanitizeEnvValue(import.meta.env.VITE_COGNITO_FEDERATED_BUTTON_LABEL as string | undefined) ||
  "Sign in with NASA PIV";
const PASSWORD_LOGIN_DISABLED = envFlagEnabled(
  import.meta.env.VITE_COGNITO_PASSWORD_LOGIN_DISABLED as string | undefined,
  false,
);
const PASSWORD_LOGIN_ENABLED = !PASSWORD_LOGIN_DISABLED;
const APPROVED_GROUPS = parseCsvEnv(import.meta.env.VITE_MIRA_ALLOWED_GROUPS as string | undefined).map(
  (group) => group.toLowerCase(),
);
const APPROVED_USERNAMES = parseCsvEnv(
  import.meta.env.VITE_MIRA_ALLOWED_USERNAMES as string | undefined,
).map((username) => username.toLowerCase());
const APPROVED_EMAILS = parseCsvEnv(import.meta.env.VITE_MIRA_ALLOWED_EMAILS as string | undefined).map(
  (email) => email.toLowerCase(),
);
const HAS_VALID_HOSTED_UI_CONFIG = Boolean(HOSTED_UI_DOMAIN && IS_VALID_CLIENT_ID);

const HOSTED_UI_SESSION_KEY = "mira.auth.hosted-ui.session";
const HOSTED_UI_PKCE_KEY = "mira.auth.hosted-ui.pkce";

const cognitoStorage = safeSessionStorage();

if (!AUTH_BYPASS_LOCAL && (USER_POOL_ID || CLIENT_ID) && !HAS_VALID_COGNITO_CONFIG) {
  console.error(
    "[auth] Invalid Cognito configuration. Check VITE_COGNITO_USER_POOL_ID and VITE_COGNITO_CLIENT_ID.",
    {
      hasUserPoolId: Boolean(USER_POOL_ID),
      hasClientId: Boolean(CLIENT_ID),
      userPoolIdPreview: USER_POOL_ID ? `${USER_POOL_ID.slice(0, 12)}...` : "",
    },
  );
}

if (!AUTH_BYPASS_LOCAL && HOSTED_UI_DOMAIN && !HAS_VALID_HOSTED_UI_CONFIG) {
  console.error(
    "[auth] Invalid hosted UI configuration. Check VITE_COGNITO_HOSTED_UI_DOMAIN and VITE_COGNITO_CLIENT_ID.",
  );
}

let userPool: CognitoUserPool | null = null;
if (!AUTH_BYPASS_LOCAL && HAS_VALID_COGNITO_CONFIG) {
  try {
    userPool = new CognitoUserPool({
      UserPoolId: USER_POOL_ID,
      ClientId: CLIENT_ID,
      Storage: cognitoStorage,
    });
  } catch (error) {
    console.error("[auth] Failed to initialize Cognito user pool.", error);
    userPool = null;
  }
}

const AuthContext = createContext<AuthContextValue | null>(null);

const LOCAL_DEV_USER: AuthUser = {
  username: "local-dev",
  email: "local-dev@boundstate.local",
  groups: ["mira-admin", "mira-itar"],
  role: "admin",
  itarAccess: "full",
  usPersonVerified: true,
  isItarCleared: true,
  isAdmin: true,
  isApproved: true,
};

function parseGroups(rawGroups: AccessTokenClaims["cognito:groups"]): string[] {
  if (!rawGroups) return [];
  if (Array.isArray(rawGroups)) return rawGroups.map(String);
  return [String(rawGroups)];
}

function parseUserFromTokens(accessToken: string, idToken: string): AuthUser {
  const accessClaims = jwtDecode<AccessTokenClaims>(accessToken);
  const idClaims = jwtDecode<IdTokenClaims>(idToken);

  const groups = parseGroups(accessClaims["cognito:groups"]);
  const usPersonRaw = idClaims["custom:us_person_verified"];
  const usPersonVerified =
    usPersonRaw === undefined ? null : String(usPersonRaw).toLowerCase() === "true";
  const itarAccess = idClaims["custom:itar_access"] || "";
  const normalizedGroups = groups.map((group) => group.toLowerCase());
  const groupBasedItar = normalizedGroups.includes("mira-itar");
  const customUsPersonValid = usPersonVerified !== false;
  const customItarValid = !itarAccess || ["full", "read"].includes(itarAccess);
  const username = idClaims["cognito:username"] || accessClaims.username || "";
  const email = idClaims.email || "";
  const approvalConfigured =
    APPROVED_GROUPS.length > 0 || APPROVED_USERNAMES.length > 0 || APPROVED_EMAILS.length > 0;
  const isApproved =
    !approvalConfigured
    || normalizedGroups.includes("mira-admin")
    || normalizedGroups.some((group) => APPROVED_GROUPS.includes(group))
    || (username ? APPROVED_USERNAMES.includes(username.toLowerCase()) : false)
    || (email ? APPROVED_EMAILS.includes(email.toLowerCase()) : false);

  return {
    username,
    email,
    groups,
    role: idClaims["custom:role"] || "viewer",
    itarAccess,
    usPersonVerified,
    isItarCleared: groupBasedItar && customUsPersonValid && customItarValid,
    isAdmin: normalizedGroups.includes("mira-admin"),
    isApproved,
  };
}

function parseUserFromSession(session: CognitoUserSession): AuthUser {
  return parseUserFromTokens(
    session.getAccessToken().getJwtToken(),
    session.getIdToken().getJwtToken(),
  );
}

function hostedUiBaseUrl(): string {
  if (!HOSTED_UI_DOMAIN) return "";
  return `https://${HOSTED_UI_DOMAIN}`;
}

function hostedUiRedirectUri(): string {
  if (HOSTED_UI_REDIRECT_URI) return HOSTED_UI_REDIRECT_URI;
  if (typeof window === "undefined") return "";
  return `${window.location.origin}/auth/callback`;
}

function hostedUiLogoutUri(): string {
  if (HOSTED_UI_LOGOUT_URI) return HOSTED_UI_LOGOUT_URI;
  if (typeof window === "undefined") return "";
  return `${window.location.origin}/`;
}

function currentRelativePath(): string {
  if (typeof window === "undefined") return "/";
  const value = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  return value.startsWith("/auth/") ? "/" : value;
}

function readHostedUiSession(): HostedUiSession | null {
  const storage = safeSessionStorage();
  const session = safeJsonParse<HostedUiSession>(storage?.getItem(HOSTED_UI_SESSION_KEY) ?? null);
  if (!session?.accessToken || !session?.idToken || !session?.expiresAt) {
    return null;
  }
  return session;
}

function writeHostedUiSession(session: HostedUiSession): void {
  safeSessionStorage()?.setItem(HOSTED_UI_SESSION_KEY, JSON.stringify(session));
}

function clearHostedUiSession(): void {
  safeSessionStorage()?.removeItem(HOSTED_UI_SESSION_KEY);
}

function readPkceState(): HostedUiPkceState | null {
  return safeJsonParse<HostedUiPkceState>(safeSessionStorage()?.getItem(HOSTED_UI_PKCE_KEY) ?? null);
}

function writePkceState(state: HostedUiPkceState): void {
  safeSessionStorage()?.setItem(HOSTED_UI_PKCE_KEY, JSON.stringify(state));
}

function clearPkceState(): void {
  safeSessionStorage()?.removeItem(HOSTED_UI_PKCE_KEY);
}

async function postHostedUiTokenRequest(
  params: URLSearchParams,
): Promise<HostedUiTokenResponse> {
  const response = await fetch(`${hostedUiBaseUrl()}/oauth2/token`, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: params,
  });

  let payload: HostedUiTokenResponse | null = null;
  try {
    payload = (await response.json()) as HostedUiTokenResponse;
  } catch {
    payload = null;
  }

  if (!response.ok) {
    throw new Error(formatOauthError(payload, "Federated login failed."));
  }

  if (!payload?.access_token || !payload?.id_token || !payload.expires_in) {
    throw new Error("Hosted UI token response is incomplete.");
  }

  return payload;
}

function shouldAttachAuthHeader(input: RequestInfo | URL, token: string): boolean {
  if (!token) return false;
  const rawUrl =
    typeof input === "string"
      ? input
      : input instanceof URL
      ? input.toString()
      : input.url;

  let parsed: URL;
  try {
    parsed = new URL(rawUrl, window.location.origin);
  } catch {
    return false;
  }

  if (parsed.pathname.startsWith("/api")) return true;
  if (API_AUTH_HOSTS.includes(parsed.host)) return true;
  return false;
}

function isApiRequest(input: RequestInfo | URL): boolean {
  const rawUrl =
    typeof input === "string"
      ? input
      : input instanceof URL
      ? input.toString()
      : input.url;

  let parsed: URL;
  try {
    parsed = new URL(rawUrl, window.location.origin);
  } catch {
    return false;
  }

  return parsed.pathname.startsWith("/api") || API_AUTH_HOSTS.includes(parsed.host);
}

function mergeAuthorizationHeader(
  existingHeaders: HeadersInit | undefined,
  token: string,
): Headers {
  const headers = new Headers(existingHeaders);
  if (!headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  return headers;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [stage, setStage] = useState<AuthStage>("login");
  const [pendingUsername, setPendingUsername] = useState("");
  const [mfaSecret, setMfaSecret] = useState("");
  const [challengeUser, setChallengeUser] = useState<CognitoUser | null>(null);
  const [passwordResetUser, setPasswordResetUser] = useState<CognitoUser | null>(null);
  const [passwordResetDelivery, setPasswordResetDelivery] = useState("");
  const [newPasswordAttributes, setNewPasswordAttributes] = useState<Record<string, string>>({});
  const [sessionMode, setSessionMode] = useState<SessionMode>("none");
  const tokenRef = useRef<string | null>(null);
  const logoutRef = useRef<() => void>(() => {});

  const resetInteractiveState = useCallback(() => {
    setStage("login");
    setChallengeUser(null);
    setPasswordResetUser(null);
    setPasswordResetDelivery("");
    setPendingUsername("");
    setMfaSecret("");
    setNewPasswordAttributes({});
  }, []);

  const beginSession = useCallback(
    (session: CognitoUserSession) => {
      clearHostedUiSession();
      const accessToken = session.getAccessToken().getJwtToken();
      setToken(accessToken);
      setUser(parseUserFromSession(session));
      setSessionMode("user-pool");
      resetInteractiveState();
    },
    [resetInteractiveState],
  );

  const beginHostedUiSession = useCallback(
    (payload: HostedUiTokenResponse) => {
      if (!payload.access_token || !payload.id_token || !payload.expires_in) {
        throw new Error("Hosted UI token response is incomplete.");
      }
      const expiresAt = Date.now() + payload.expires_in * 1000;
      writeHostedUiSession({
        accessToken: payload.access_token,
        idToken: payload.id_token,
        refreshToken: payload.refresh_token ?? readHostedUiSession()?.refreshToken ?? null,
        expiresAt,
      });
      setToken(payload.access_token);
      setUser(parseUserFromTokens(payload.access_token, payload.id_token));
      setSessionMode("hosted-ui");
      resetInteractiveState();
    },
    [resetInteractiveState],
  );

  const startMfaSetup = useCallback(
    (targetUser: CognitoUser, resolve: () => void, reject: (reason?: unknown) => void) => {
      targetUser.associateSoftwareToken({
        associateSecretCode: (secretCode: string) => {
          setChallengeUser(targetUser);
          setMfaSecret(secretCode);
          setStage("mfa-setup");
          resolve();
        },
        onFailure: reject,
      });
    },
    [],
  );

  useEffect(() => {
    if (AUTH_BYPASS_LOCAL) {
      setUser(LOCAL_DEV_USER);
      setToken(null);
      setSessionMode("local");
      setLoading(false);
      return;
    }

    const hostedUiSession = readHostedUiSession();
    if (hostedUiSession && hostedUiSession.expiresAt > Date.now()) {
      setUser(parseUserFromTokens(hostedUiSession.accessToken, hostedUiSession.idToken));
      setToken(hostedUiSession.accessToken);
      setSessionMode("hosted-ui");
      setLoading(false);
      return;
    }
    clearHostedUiSession();

    if (!userPool) {
      setSessionMode("none");
      setLoading(false);
      return;
    }

    const currentUser = userPool.getCurrentUser();
    if (!currentUser) {
      setSessionMode("none");
      setLoading(false);
      return;
    }

    currentUser.getSession((err: Error | null, session: CognitoUserSession | null) => {
      if (err || !session || !session.isValid()) {
        setSessionMode("none");
        setLoading(false);
        return;
      }
      beginSession(session);
      setLoading(false);
    });
  }, [beginSession]);

  const logout = useCallback(() => {
    clearHostedUiSession();
    clearPkceState();

    if (AUTH_BYPASS_LOCAL) {
      setUser(LOCAL_DEV_USER);
      setToken(null);
      setSessionMode("local");
      setLoading(false);
      return;
    }

    const currentUser = userPool?.getCurrentUser();
    if (currentUser) {
      currentUser.signOut();
    }

    setUser(null);
    setToken(null);
    setSessionMode("none");
    resetInteractiveState();
  }, [resetInteractiveState]);

  tokenRef.current = token;
  logoutRef.current = logout;

  useLayoutEffect(() => {
    const originalFetch = window.fetch.bind(window);

    window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      const currentToken = tokenRef.current;
      if (!currentToken || !shouldAttachAuthHeader(input, currentToken)) {
        return originalFetch(input, init);
      }

      let response: Response;
      if (input instanceof Request) {
        const headers = mergeAuthorizationHeader(input.headers, currentToken);
        if (init?.headers) {
          const initHeaders = new Headers(init.headers);
          initHeaders.forEach((value, key) => headers.set(key, value));
          if (!headers.has("Authorization")) {
            headers.set("Authorization", `Bearer ${currentToken}`);
          }
        }
        response = await originalFetch(new Request(input, { ...init, headers }));
      } else {
        response = await originalFetch(input, {
          ...init,
          headers: mergeAuthorizationHeader(init?.headers, currentToken),
        });
      }

      if (response.status === 401 && isApiRequest(input)) {
        logoutRef.current();
      }

      return response;
    };

    return () => {
      window.fetch = originalFetch;
    };
  }, []);

  const login = useCallback(
    (username: string, password: string) => {
      if (!PASSWORD_LOGIN_ENABLED) {
        return Promise.reject(
          new Error("Password login is disabled for this MIRA deployment. Use the PIV sign-in path."),
        );
      }
      if (!userPool) {
        return Promise.reject(
          new Error("Cognito not configured. Set VITE_COGNITO_USER_POOL_ID and VITE_COGNITO_CLIENT_ID."),
        );
      }

      return new Promise<void>((resolve, reject) => {
        const trimmedUsername = username.trim();
        const cognitoUser = new CognitoUser({
          Username: trimmedUsername,
          Pool: userPool,
        });

        setPendingUsername(trimmedUsername);
        setChallengeUser(cognitoUser);

        const authDetails = new AuthenticationDetails({
          Username: trimmedUsername,
          Password: password,
        });

        cognitoUser.authenticateUser(authDetails, {
          onSuccess: (session: CognitoUserSession) => {
            beginSession(session);
            resolve();
          },
          onFailure: reject,
          newPasswordRequired: () => {
            setNewPasswordAttributes({});
            setStage("new-password");
            resolve();
          },
          totpRequired: () => {
            setStage("mfa-verify");
            resolve();
          },
          mfaSetup: () => {
            startMfaSetup(cognitoUser, resolve, reject);
          },
        });
      });
    },
    [beginSession, startMfaSetup],
  );

  const loginWithFederation = useCallback(async (returnTo?: string) => {
    if (!HAS_VALID_HOSTED_UI_CONFIG) {
      throw new Error(
        "Hosted UI is not configured. Set VITE_COGNITO_HOSTED_UI_DOMAIN and VITE_COGNITO_CLIENT_ID.",
      );
    }

    const verifier = randomUrlSafeString(64);
    const state = randomUrlSafeString(32);
    const codeChallenge = await sha256Base64Url(verifier);
    const targetPath = returnTo?.trim() || currentRelativePath();

    writePkceState({
      state,
      verifier,
      returnTo: targetPath.startsWith("/") ? targetPath : "/",
    });

    const params = new URLSearchParams({
      client_id: CLIENT_ID,
      response_type: "code",
      scope: HOSTED_UI_SCOPE,
      redirect_uri: hostedUiRedirectUri(),
      state,
      code_challenge_method: "S256",
      code_challenge: codeChallenge,
    });

    if (HOSTED_UI_IDENTITY_PROVIDER) {
      params.set("identity_provider", HOSTED_UI_IDENTITY_PROVIDER);
    }

    window.location.assign(`${hostedUiBaseUrl()}/oauth2/authorize?${params.toString()}`);
  }, []);

  const completeFederatedLogin = useCallback(
    async (callbackUrl?: string) => {
      if (!HAS_VALID_HOSTED_UI_CONFIG) {
        throw new Error(
          "Hosted UI is not configured. Set VITE_COGNITO_HOSTED_UI_DOMAIN and VITE_COGNITO_CLIENT_ID.",
        );
      }

      const url = new URL(callbackUrl || window.location.href);
      const oauthError = url.searchParams.get("error_description") || url.searchParams.get("error");
      if (oauthError) {
        clearPkceState();
        throw new Error(oauthError.replace(/\+/g, " "));
      }

      const code = url.searchParams.get("code");
      const state = url.searchParams.get("state");
      if (!code || !state) {
        throw new Error("Hosted UI callback is missing the authorization code.");
      }

      const pkce = readPkceState();
      if (!pkce || pkce.state !== state) {
        clearPkceState();
        throw new Error("Hosted UI state validation failed.");
      }

      const payload = await postHostedUiTokenRequest(
        new URLSearchParams({
          grant_type: "authorization_code",
          client_id: CLIENT_ID,
          code,
          redirect_uri: hostedUiRedirectUri(),
          code_verifier: pkce.verifier,
        }),
      );

      beginHostedUiSession(payload);
      clearPkceState();
      return pkce.returnTo || "/";
    },
    [beginHostedUiSession],
  );

  const completeNewPassword = useCallback(
    (newPassword: string) => {
      if (!challengeUser) {
        return Promise.reject(new Error("No active new-password challenge."));
      }

      return new Promise<void>((resolve, reject) => {
        challengeUser.completeNewPasswordChallenge(
          newPassword,
          newPasswordAttributes,
          {
            onSuccess: (session: CognitoUserSession) => {
              beginSession(session);
              resolve();
            },
            onFailure: reject,
            totpRequired: () => {
              setStage("mfa-verify");
              resolve();
            },
            mfaSetup: () => {
              startMfaSetup(challengeUser, resolve, reject);
            },
          },
        );
      });
    },
    [beginSession, challengeUser, newPasswordAttributes, startMfaSetup],
  );

  const verifyMfa = useCallback(
    (code: string) => {
      if (!challengeUser) {
        return Promise.reject(new Error("No MFA challenge in progress."));
      }
      return new Promise<void>((resolve, reject) => {
        challengeUser.sendMFACode(
          code,
          {
            onSuccess: (session: CognitoUserSession) => {
              beginSession(session);
              resolve();
            },
            onFailure: reject,
          },
          "SOFTWARE_TOKEN_MFA",
        );
      });
    },
    [beginSession, challengeUser],
  );

  const verifyMfaSetup = useCallback(
    (code: string) => {
      if (!challengeUser) {
        return Promise.reject(new Error("No MFA setup challenge in progress."));
      }
      return new Promise<void>((resolve, reject) => {
        challengeUser.verifySoftwareToken(code, "MIRA Authenticator", {
          onSuccess: (session?: CognitoUserSession) => {
            if (session && typeof session.getAccessToken === "function") {
              beginSession(session);
              resolve();
              return;
            }
            challengeUser.getSession((err: Error | null, fallbackSession: CognitoUserSession | null) => {
              if (err || !fallbackSession || !fallbackSession.isValid()) {
                reject(err || new Error("MFA setup completed, but session is unavailable."));
                return;
              }
              beginSession(fallbackSession);
              resolve();
            });
          },
          onFailure: reject,
        });
      });
    },
    [beginSession, challengeUser],
  );

  const goToForgotPassword = useCallback(() => {
    setStage("forgot-password-request");
    setChallengeUser(null);
    setPasswordResetUser(null);
    setPasswordResetDelivery("");
    setMfaSecret("");
    setNewPasswordAttributes({});
  }, []);

  const requestPasswordReset = useCallback((username: string) => {
    if (!userPool) {
      return Promise.reject(
        new Error("Cognito not configured. Set VITE_COGNITO_USER_POOL_ID and VITE_COGNITO_CLIENT_ID."),
      );
    }

    const trimmedUsername = username.trim();
    if (!trimmedUsername) {
      return Promise.reject(new Error("Username is required."));
    }

    return new Promise<void>((resolve, reject) => {
      let settled = false;
      const cognitoUser = new CognitoUser({
        Username: trimmedUsername,
        Pool: userPool,
      });

      setPendingUsername(trimmedUsername);
      setPasswordResetUser(cognitoUser);
      setPasswordResetDelivery("");

      cognitoUser.forgotPassword({
        onSuccess: () => {
          if (!settled) {
            settled = true;
            setStage("forgot-password-confirm");
            resolve();
          }
        },
        onFailure: (err) => {
          if (!settled) {
            settled = true;
            reject(err);
          }
        },
        inputVerificationCode: (data?: { DeliveryMedium?: string; Destination?: string }) => {
          if (settled) return;
          settled = true;
          const delivery = data?.Destination
            ? `${data.DeliveryMedium || "Code"} sent to ${data.Destination}`
            : "Verification code sent.";
          setPasswordResetDelivery(delivery);
          setStage("forgot-password-confirm");
          resolve();
        },
      });
    });
  }, []);

  const confirmPasswordReset = useCallback(
    (code: string, newPassword: string) => {
      if (!passwordResetUser) {
        return Promise.reject(new Error("No password reset challenge in progress."));
      }
      return new Promise<void>((resolve, reject) => {
        passwordResetUser.confirmPassword(code.trim(), newPassword, {
          onSuccess: () => {
            setPasswordResetUser(null);
            setPasswordResetDelivery("");
            setPendingUsername("");
            setStage("login");
            resolve();
          },
          onFailure: reject,
        });
      });
    },
    [passwordResetUser],
  );

  const goToLogin = useCallback(() => {
    setStage("login");
    setChallengeUser(null);
    setPasswordResetUser(null);
    setPasswordResetDelivery("");
    setMfaSecret("");
    setNewPasswordAttributes({});
  }, []);

  const refreshHostedUiSession = useCallback(
    async (refreshToken: string) => {
      const payload = await postHostedUiTokenRequest(
        new URLSearchParams({
          grant_type: "refresh_token",
          client_id: CLIENT_ID,
          refresh_token: refreshToken,
        }),
      );
      beginHostedUiSession({
        ...payload,
        refresh_token: payload.refresh_token ?? refreshToken,
      });
    },
    [beginHostedUiSession],
  );

  useEffect(() => {
    if (!token) return;

    let claims: AccessTokenClaims;
    try {
      claims = jwtDecode<AccessTokenClaims>(token);
    } catch {
      logout();
      return;
    }

    if (!claims.exp) return;

    const msUntilRefresh = claims.exp * 1000 - Date.now() - 300000;
    if (msUntilRefresh <= 0) {
      logout();
      return;
    }

    const refreshTimer = window.setTimeout(() => {
      if (sessionMode === "hosted-ui") {
        const session = readHostedUiSession();
        if (!session?.refreshToken) {
          logout();
          return;
        }
        void refreshHostedUiSession(session.refreshToken).catch(() => logout());
        return;
      }

      if (sessionMode !== "user-pool" || !userPool) {
        return;
      }

      const currentUser = userPool.getCurrentUser();
      if (!currentUser) {
        logout();
        return;
      }
      currentUser.getSession((err: Error | null, session: CognitoUserSession | null) => {
        if (err || !session || !session.isValid()) {
          logout();
          return;
        }
        beginSession(session);
      });
    }, msUntilRefresh);

    return () => window.clearTimeout(refreshTimer);
  }, [beginSession, logout, refreshHostedUiSession, sessionMode, token]);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      token,
      loading,
      stage,
      pendingUsername,
      mfaSecret,
      passwordResetDelivery,
      authHeaders: token ? { Authorization: `Bearer ${token}` } : {},
      supportsPasswordLogin: PASSWORD_LOGIN_ENABLED,
      supportsFederatedLogin: HAS_VALID_HOSTED_UI_CONFIG,
      federatedLoginLabel: HOSTED_UI_BUTTON_LABEL,
      login,
      loginWithFederation,
      completeFederatedLogin,
      completeNewPassword,
      verifyMfa,
      verifyMfaSetup,
      goToForgotPassword,
      requestPasswordReset,
      confirmPasswordReset,
      goToLogin,
      logout,
    }),
    [
      user,
      token,
      loading,
      stage,
      pendingUsername,
      mfaSecret,
      passwordResetDelivery,
      PASSWORD_LOGIN_ENABLED,
      login,
      loginWithFederation,
      completeFederatedLogin,
      completeNewPassword,
      verifyMfa,
      verifyMfaSetup,
      goToForgotPassword,
      requestPasswordReset,
      confirmPasswordReset,
      goToLogin,
      logout,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return ctx;
}
