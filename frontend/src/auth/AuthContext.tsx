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
  CognitoUserAttribute,
  CognitoUserPool,
  CognitoUserSession,
} from "amazon-cognito-identity-js";
import { jwtDecode } from "jwt-decode";

type AuthStage =
  | "login"
  | "signup"
  | "signup-confirm"
  | "new-password"
  | "mfa-setup"
  | "mfa-verify"
  | "forgot-password-request"
  | "forgot-password-confirm";

interface AuthUser {
  username: string;
  email: string;
  groups: string[];
  role: string;
  itarAccess: string;
  usPersonVerified: boolean | null;
  isItarCleared: boolean;
  isAdmin: boolean;
}

interface AuthContextValue {
  user: AuthUser | null;
  token: string | null;
  loading: boolean;
  stage: AuthStage;
  pendingUsername: string;
  mfaSecret: string;
  signupDelivery: string;
  passwordResetDelivery: string;
  authHeaders: Record<string, string>;
  goToSignup: () => void;
  signUp: (email: string, password: string) => Promise<void>;
  confirmSignUp: (code: string) => Promise<void>;
  login: (username: string, password: string) => Promise<void>;
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

function sanitizeEnvValue(value: string | undefined): string {
  const trimmed = (value || "").trim();
  if (!trimmed) return "";
  const lower = trimmed.toLowerCase();
  if (lower === "none" || lower === "null" || lower === "undefined") return "";
  return trimmed;
}

function envFlagEnabled(value: string | undefined, defaultValue: boolean): boolean {
  const fallback = defaultValue ? "true" : "false";
  return !["0", "false", "no"].includes(String(value ?? fallback).trim().toLowerCase());
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
const AUTH_BYPASS_ENABLED =
  envFlagEnabled(import.meta.env.VITE_AUTH_BYPASS as string | undefined, false) ||
  (import.meta.env.DEV &&
    envFlagEnabled(import.meta.env.VITE_AUTH_BYPASS_LOCAL as string | undefined, true));
const API_AUTH_HOSTS = (
  (import.meta.env.VITE_API_AUTH_HOSTS as string | undefined) || "127.0.0.1:8000,localhost:8000"
)
  .split(",")
  .map((entry) => entry.trim())
  .filter(Boolean);

const cognitoStorage =
  typeof window !== "undefined" && window.sessionStorage ? window.sessionStorage : undefined;

if (!AUTH_BYPASS_ENABLED && (USER_POOL_ID || CLIENT_ID) && !HAS_VALID_COGNITO_CONFIG) {
  console.error(
    "[auth] Invalid Cognito configuration. Check VITE_COGNITO_USER_POOL_ID and VITE_COGNITO_CLIENT_ID.",
    {
      hasUserPoolId: Boolean(USER_POOL_ID),
      hasClientId: Boolean(CLIENT_ID),
      userPoolIdPreview: USER_POOL_ID ? `${USER_POOL_ID.slice(0, 12)}...` : "",
    },
  );
}

let userPool: CognitoUserPool | null = null;
if (!AUTH_BYPASS_ENABLED && HAS_VALID_COGNITO_CONFIG) {
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

const AUTH_BYPASS_USER: AuthUser = {
  username: "mira-admin",
  email: "mira-admin@boundstate.local",
  groups: ["mira-admin", "mira-itar"],
  role: "admin",
  itarAccess: "full",
  usPersonVerified: true,
  isItarCleared: true,
  isAdmin: true,
};

const PENDING_SIGNUP_STORAGE_KEY = "boundstate:mira-pending-signup:v1";

function parseGroups(rawGroups: AccessTokenClaims["cognito:groups"]): string[] {
  if (!rawGroups) return [];
  if (Array.isArray(rawGroups)) return rawGroups.map(String);
  return [String(rawGroups)];
}

function parseUserFromSession(session: CognitoUserSession): AuthUser {
  const accessToken = session.getAccessToken().getJwtToken();
  const idToken = session.getIdToken().getJwtToken();
  const accessClaims = jwtDecode<AccessTokenClaims>(accessToken);
  const idClaims = jwtDecode<IdTokenClaims>(idToken);

  const groups = parseGroups(accessClaims["cognito:groups"]);
  const usPersonRaw = idClaims["custom:us_person_verified"];
  const usPersonVerified =
    usPersonRaw === undefined ? null : String(usPersonRaw).toLowerCase() === "true";
  const itarAccess = idClaims["custom:itar_access"] || "";
  const groupBasedItar = groups.includes("mira-itar");
  const customUsPersonValid = usPersonVerified !== false;
  const customItarValid = !itarAccess || ["full", "read"].includes(itarAccess);

  return {
    username: idClaims["cognito:username"] || accessClaims.username || "",
    email: idClaims.email || "",
    groups,
    role: idClaims["custom:role"] || "viewer",
    itarAccess,
    usPersonVerified,
    isItarCleared: groupBasedItar && customUsPersonValid && customItarValid,
    isAdmin: groups.includes("mira-admin"),
  };
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
  const [signupDelivery, setSignupDelivery] = useState("");
  const [signupTelemetryPending, setSignupTelemetryPending] = useState(false);
  const [challengeUser, setChallengeUser] = useState<CognitoUser | null>(null);
  const [passwordResetUser, setPasswordResetUser] = useState<CognitoUser | null>(null);
  const [passwordResetDelivery, setPasswordResetDelivery] = useState("");
  const [newPasswordAttributes, setNewPasswordAttributes] = useState<Record<string, string>>({});
  const signupPasswordRef = useRef("");
  const tokenRef = useRef<string | null>(null);
  const logoutRef = useRef<() => void>(() => {});

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    try {
      setSignupTelemetryPending(window.sessionStorage.getItem(PENDING_SIGNUP_STORAGE_KEY) === "1");
    } catch {
      setSignupTelemetryPending(false);
    }
  }, []);

  const beginSession = useCallback((session: CognitoUserSession) => {
    const accessToken = session.getAccessToken().getJwtToken();
    setToken(accessToken);
    setUser(parseUserFromSession(session));
    setStage("login");
    setChallengeUser(null);
    setPasswordResetUser(null);
    setPasswordResetDelivery("");
    setSignupDelivery("");
    setMfaSecret("");
    setNewPasswordAttributes({});
    signupPasswordRef.current = "";
  }, []);

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
    if (AUTH_BYPASS_ENABLED) {
      setUser(AUTH_BYPASS_USER);
      setToken(null);
      setLoading(false);
      return;
    }
    if (!userPool) {
      setLoading(false);
      return;
    }
    const currentUser = userPool.getCurrentUser();
    if (!currentUser) {
      setLoading(false);
      return;
    }
    currentUser.getSession((err: Error | null, session: CognitoUserSession | null) => {
      if (err || !session || !session.isValid()) {
        setLoading(false);
        return;
      }
      beginSession(session);
      setLoading(false);
    });
  }, [beginSession]);

  useEffect(() => {
    if (!signupTelemetryPending || !token || !user || typeof window === "undefined") {
      return;
    }

    let cancelled = false;
    void window
      .fetch("/api/usage/events", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          event_type: "signup_complete",
          path: "/signup/complete",
          module_id: "auth",
          page_label: "Signup Complete",
          navigation_type: "unknown",
          client_session_id: `signup-${user.username || user.email || "unknown"}`,
          referrer: null,
        }),
        keepalive: true,
      })
      .finally(() => {
        if (cancelled) {
          return;
        }
        setSignupTelemetryPending(false);
        try {
          window.sessionStorage.removeItem(PENDING_SIGNUP_STORAGE_KEY);
        } catch {
          // Ignore storage failures; the event is best-effort telemetry.
        }
      });

    return () => {
      cancelled = true;
    };
  }, [signupTelemetryPending, token, user]);

  const logout = useCallback(() => {
    if (AUTH_BYPASS_ENABLED) {
      setUser(AUTH_BYPASS_USER);
      setToken(null);
      setLoading(false);
      return;
    }
    const currentUser = userPool?.getCurrentUser();
    if (currentUser) {
      currentUser.signOut();
    }
    setUser(null);
    setToken(null);
    setStage("login");
    setChallengeUser(null);
    setPasswordResetUser(null);
    setPasswordResetDelivery("");
    setPendingUsername("");
    setSignupDelivery("");
    setMfaSecret("");
    setNewPasswordAttributes({});
    signupPasswordRef.current = "";
  }, []);

  const goToSignup = useCallback(() => {
    setStage("signup");
    setChallengeUser(null);
    setPasswordResetUser(null);
    setPasswordResetDelivery("");
    setSignupDelivery("");
    setMfaSecret("");
    setNewPasswordAttributes({});
    signupPasswordRef.current = "";
  }, []);

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
            // Do not echo existing attributes (for example email) back to Cognito here.
            // For NEW_PASSWORD_REQUIRED, Cognito rejects attempts to modify already-set values.
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

  const signUp = useCallback((email: string, password: string) => {
    if (!userPool) {
      return Promise.reject(
        new Error("Cognito not configured. Set VITE_COGNITO_USER_POOL_ID and VITE_COGNITO_CLIENT_ID."),
      );
    }

    const trimmedEmail = email.trim().toLowerCase();
    if (!trimmedEmail) {
      return Promise.reject(new Error("Email is required."));
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmedEmail)) {
      return Promise.reject(new Error("Enter a valid email address."));
    }

    return new Promise<void>((resolve, reject) => {
      userPool.signUp(
        trimmedEmail,
        password,
        [new CognitoUserAttribute({ Name: "email", Value: trimmedEmail })],
        [],
        (err, result) => {
          if (err) {
            reject(err);
            return;
          }

          const delivery = result?.codeDeliveryDetails?.Destination
            ? `${result.codeDeliveryDetails.DeliveryMedium || "Code"} sent to ${result.codeDeliveryDetails.Destination}`
            : "Verification code sent to your email.";

          setPendingUsername(trimmedEmail);
          setChallengeUser(
            result?.user ||
              new CognitoUser({
                Username: trimmedEmail,
                Pool: userPool,
              }),
          );
          setPasswordResetUser(null);
          setPasswordResetDelivery("");
          setSignupDelivery(delivery);
          setMfaSecret("");
          setNewPasswordAttributes({});
          signupPasswordRef.current = password;
          setStage("signup-confirm");
          resolve();
        },
      );
    });
  }, []);

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

  const confirmSignUp = useCallback(
    (code: string) => {
      if (!userPool) {
        return Promise.reject(
          new Error("Cognito not configured. Set VITE_COGNITO_USER_POOL_ID and VITE_COGNITO_CLIENT_ID."),
        );
      }
      if (!pendingUsername) {
        return Promise.reject(new Error("No signup confirmation in progress."));
      }

      const targetUser =
        challengeUser && challengeUser.getUsername() === pendingUsername
          ? challengeUser
          : new CognitoUser({
              Username: pendingUsername,
              Pool: userPool,
            });

      return new Promise<void>((resolve, reject) => {
        targetUser.confirmRegistration(code.trim(), true, async (err) => {
          if (err) {
            reject(err);
            return;
          }

          setChallengeUser(null);
          setSignupDelivery("");
          setSignupTelemetryPending(true);
          try {
            window.sessionStorage.setItem(PENDING_SIGNUP_STORAGE_KEY, "1");
          } catch {
            // Ignore storage failures; signup telemetry will still work within this render lifecycle.
          }

          const signupPassword = signupPasswordRef.current;
          signupPasswordRef.current = "";
          if (!signupPassword) {
            setStage("login");
            resolve();
            return;
          }

          try {
            await login(pendingUsername, signupPassword);
            resolve();
          } catch {
            setStage("login");
            reject(new Error("Account verified. Sign in with your new credentials to continue."));
          }
        });
      });
    },
    [challengeUser, login, pendingUsername],
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
    setSignupDelivery("");
    setMfaSecret("");
    setNewPasswordAttributes({});
    signupPasswordRef.current = "";
  }, []);

  const requestPasswordReset = useCallback(
    (username: string) => {
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
    },
    [],
  );

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
    setSignupDelivery("");
    setMfaSecret("");
    setNewPasswordAttributes({});
    signupPasswordRef.current = "";
  }, []);

  useEffect(() => {
    if (!token || !userPool) return;
    const claims = jwtDecode<AccessTokenClaims>(token);
    if (!claims.exp) return;

    const msUntilRefresh = claims.exp * 1000 - Date.now() - 300000;
    if (msUntilRefresh <= 0) {
      logout();
      return;
    }

    const refreshTimer = window.setTimeout(() => {
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
  }, [beginSession, logout, token]);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      token,
      loading,
      stage,
      pendingUsername,
      mfaSecret,
      signupDelivery,
      passwordResetDelivery,
      authHeaders: token ? { Authorization: `Bearer ${token}` } : {},
      goToSignup,
      signUp,
      confirmSignUp,
      login,
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
      signupDelivery,
      passwordResetDelivery,
      goToSignup,
      signUp,
      confirmSignUp,
      login,
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
