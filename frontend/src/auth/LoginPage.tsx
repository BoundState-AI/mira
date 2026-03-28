import { FormEvent, useEffect, useMemo, useState } from "react";
import QRCode from "qrcode";
import { useAuth } from "@/auth/AuthContext";
import { BoundStateLogo } from "@/components/BoundStateLogo";

export function LoginPage() {
  const {
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
  } = useAuth();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [mfaCode, setMfaCode] = useState("");
  const [signupCode, setSignupCode] = useState("");
  const [resetCode, setResetCode] = useState("");
  const [resetPassword, setResetPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [mfaQrDataUrl, setMfaQrDataUrl] = useState("");

  const mfaOtpAuthUri = useMemo(() => {
    if (!mfaSecret) return "";
    const accountName = pendingUsername || "mira-user";
    const issuer = "MIRA";
    const label = `${issuer}:${accountName}`;
    return `otpauth://totp/${encodeURIComponent(label)}?secret=${encodeURIComponent(
      mfaSecret,
    )}&issuer=${encodeURIComponent(issuer)}&algorithm=SHA1&digits=6&period=30`;
  }, [mfaSecret, pendingUsername]);

  useEffect(() => {
    let canceled = false;
    if (stage !== "mfa-setup" || !mfaOtpAuthUri) {
      setMfaQrDataUrl("");
      return () => {
        canceled = true;
      };
    }

    QRCode.toDataURL(mfaOtpAuthUri, {
      errorCorrectionLevel: "M",
      margin: 1,
      width: 220,
    })
      .then((dataUrl) => {
        if (!canceled) {
          setMfaQrDataUrl(dataUrl);
        }
      })
      .catch(() => {
        if (!canceled) {
          setMfaQrDataUrl("");
        }
      });

    return () => {
      canceled = true;
    };
  }, [mfaOtpAuthUri, stage]);

  const handleLogin = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(username, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed.");
    } finally {
      setLoading(false);
    }
  };

  const handleSignUp = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      await signUp(username, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Signup failed.");
    } finally {
      setLoading(false);
    }
  };

  const handleConfirmSignUp = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      await confirmSignUp(signupCode.trim());
      setSignupCode("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Confirmation failed.");
    } finally {
      setLoading(false);
    }
  };

  const handleNewPassword = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      await completeNewPassword(newPassword);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Password update failed.");
    } finally {
      setLoading(false);
    }
  };

  const handleVerifyMfa = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      await verifyMfa(mfaCode.trim());
    } catch (err) {
      setError(err instanceof Error ? err.message : "MFA verification failed.");
    } finally {
      setLoading(false);
    }
  };

  const handleVerifyMfaSetup = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      await verifyMfaSetup(mfaCode.trim());
    } catch (err) {
      setError(err instanceof Error ? err.message : "MFA setup verification failed.");
    } finally {
      setLoading(false);
    }
  };

  const handleRequestPasswordReset = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      await requestPasswordReset(username);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Password reset request failed.");
    } finally {
      setLoading(false);
    }
  };

  const handleConfirmPasswordReset = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      await confirmPasswordReset(resetCode.trim(), resetPassword);
      setResetCode("");
      setResetPassword("");
      setPassword("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Password reset failed.");
    } finally {
      setLoading(false);
    }
  };

  const handleGoToForgotPassword = () => {
    setError("");
    goToForgotPassword();
  };

  const handleGoToSignup = () => {
    setError("");
    goToSignup();
  };

  const handleGoToLogin = () => {
    setError("");
    goToLogin();
  };

  return (
    <div className="min-h-screen bg-slate-100 flex items-center justify-center px-4">
      <div className="w-full max-w-md rounded-xl border border-slate-200 bg-white p-6 shadow-lg">
        <div className="mb-3 flex items-center justify-center gap-2">
          <BoundStateLogo variant="icon" theme="light" size="md" />
          <span className="text-lg font-semibold text-slate-900 tracking-tight">BoundState</span>
        </div>
        <h1 className="text-2xl font-semibold text-slate-900 mb-1">MIRA Secure Login</h1>
        <p className="text-sm text-slate-600 mb-6">
          Individual account access with required authenticator MFA.
        </p>

        {error && (
          <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </div>
        )}

        {stage === "login" && (
          <form onSubmit={handleLogin} className="space-y-3">
            <input
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500"
              placeholder="Username or email"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              autoFocus
            />
            <input
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500"
              type="password"
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
            />
            <button
              type="submit"
              disabled={loading || !username || !password}
              className="w-full rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
            >
              {loading ? "Signing in..." : "Sign in"}
            </button>
            <button
              type="button"
              onClick={handleGoToForgotPassword}
              className="w-full text-sm text-slate-600 underline underline-offset-2 hover:text-slate-900"
            >
              Forgot your password?
            </button>
            <button
              type="button"
              onClick={handleGoToSignup}
              className="w-full text-sm text-slate-600 underline underline-offset-2 hover:text-slate-900"
            >
              Create account
            </button>
          </form>
        )}

        {stage === "signup" && (
          <form onSubmit={handleSignUp} className="space-y-3">
            <p className="text-sm text-slate-700">
              Create your account with email verification. You&apos;ll set up authenticator MFA
              after confirming your email.
            </p>
            <input
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500"
              placeholder="Email"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="email"
              autoFocus
            />
            <input
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500"
              type="password"
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
            />
            <button
              type="submit"
              disabled={loading || !username.trim() || password.length < 12}
              className="w-full rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
            >
              {loading ? "Creating account..." : "Create account"}
            </button>
            <button
              type="button"
              onClick={handleGoToLogin}
              className="w-full text-sm text-slate-600 underline underline-offset-2 hover:text-slate-900"
            >
              Back to sign in
            </button>
          </form>
        )}

        {stage === "signup-confirm" && (
          <form onSubmit={handleConfirmSignUp} className="space-y-3">
            <p className="text-sm text-slate-700">
              {signupDelivery || "Enter the verification code sent to your email."}
            </p>
            <p className="text-xs text-slate-500">
              Account: <span className="font-medium text-slate-700">{pendingUsername}</span>
            </p>
            <input
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500"
              placeholder="Verification code"
              value={signupCode}
              onChange={(e) => setSignupCode(e.target.value.replace(/\s+/g, ""))}
              autoComplete="one-time-code"
              autoFocus
            />
            <button
              type="submit"
              disabled={loading || !signupCode.trim()}
              className="w-full rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
            >
              {loading ? "Verifying..." : "Verify and continue"}
            </button>
            <button
              type="button"
              onClick={handleGoToLogin}
              className="w-full text-sm text-slate-600 underline underline-offset-2 hover:text-slate-900"
            >
              Back to sign in
            </button>
          </form>
        )}

        {stage === "new-password" && (
          <form onSubmit={handleNewPassword} className="space-y-3">
            <p className="text-sm text-slate-700">
              Set your permanent password before continuing.
            </p>
            <input
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500"
              type="password"
              placeholder="New password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              autoComplete="new-password"
              autoFocus
            />
            <button
              type="submit"
              disabled={loading || newPassword.length < 12}
              className="w-full rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
            >
              {loading ? "Updating..." : "Set password"}
            </button>
          </form>
        )}

        {stage === "forgot-password-request" && (
          <form onSubmit={handleRequestPasswordReset} className="space-y-3">
            <p className="text-sm text-slate-700">
              Enter your username. We&apos;ll send a password reset code to your verified email.
            </p>
            <input
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500"
              placeholder="Username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              autoFocus
            />
            <button
              type="submit"
              disabled={loading || !username.trim()}
              className="w-full rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
            >
              {loading ? "Sending..." : "Send reset code"}
            </button>
            <button
              type="button"
              onClick={handleGoToLogin}
              className="w-full text-sm text-slate-600 underline underline-offset-2 hover:text-slate-900"
            >
              Back to sign in
            </button>
          </form>
        )}

        {stage === "forgot-password-confirm" && (
          <form onSubmit={handleConfirmPasswordReset} className="space-y-3">
            <p className="text-sm text-slate-700">
              {passwordResetDelivery || "Enter the verification code and your new password."}
            </p>
            <p className="text-xs text-slate-500">
              Account: <span className="font-medium text-slate-700">{pendingUsername}</span>
            </p>
            <input
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500"
              placeholder="Verification code"
              value={resetCode}
              onChange={(e) => setResetCode(e.target.value.replace(/\s+/g, ""))}
              autoComplete="one-time-code"
              autoFocus
            />
            <input
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500"
              type="password"
              placeholder="New password"
              value={resetPassword}
              onChange={(e) => setResetPassword(e.target.value)}
              autoComplete="new-password"
            />
            <button
              type="submit"
              disabled={loading || !resetCode.trim() || resetPassword.length < 12}
              className="w-full rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
            >
              {loading ? "Resetting..." : "Reset password"}
            </button>
            <button
              type="button"
              onClick={handleGoToLogin}
              className="w-full text-sm text-slate-600 underline underline-offset-2 hover:text-slate-900"
            >
              Back to sign in
            </button>
          </form>
        )}

        {stage === "mfa-setup" && (
          <form onSubmit={handleVerifyMfaSetup} className="space-y-3">
            <p className="text-sm text-slate-700">
              Scan this QR code with your phone authenticator app, then enter the 6-digit code.
            </p>
            {mfaQrDataUrl && (
              <div className="flex justify-center rounded-md border border-slate-300 bg-white p-3">
                <img src={mfaQrDataUrl} alt="MFA setup QR code" className="h-48 w-48" />
              </div>
            )}
            <div className="rounded-md border border-slate-300 bg-slate-50 p-3">
              <p className="text-xs text-slate-500 mb-1">Account</p>
              <p className="text-sm font-medium text-slate-800 mb-2">{pendingUsername || "mira-user"}</p>
              <p className="text-xs text-slate-500 mb-1">Setup key</p>
              <p className="font-mono text-sm break-all text-slate-900">{mfaSecret || "Unavailable"}</p>
            </div>
            <input
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-center tracking-widest text-sm outline-none focus:border-slate-500"
              placeholder="123456"
              value={mfaCode}
              onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
              autoFocus
            />
            <button
              type="submit"
              disabled={loading || mfaCode.length !== 6}
              className="w-full rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
            >
              {loading ? "Verifying..." : "Verify MFA setup"}
            </button>
          </form>
        )}

        {stage === "mfa-verify" && (
          <form onSubmit={handleVerifyMfa} className="space-y-3">
            <p className="text-sm text-slate-700">
              Open your phone authenticator app and enter the current 6-digit code.
            </p>
            <input
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-center tracking-widest text-sm outline-none focus:border-slate-500"
              placeholder="123456"
              value={mfaCode}
              onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
              autoFocus
            />
            <button
              type="submit"
              disabled={loading || mfaCode.length !== 6}
              className="w-full rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
            >
              {loading ? "Verifying..." : "Verify code"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
