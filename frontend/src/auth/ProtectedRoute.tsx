import React from "react";
import { LoginPage } from "@/auth/LoginPage";
import { useAuth } from "@/auth/AuthContext";

interface ProtectedRouteProps {
  children: React.ReactNode;
  requireItar?: boolean;
  requireAdmin?: boolean;
}

export function ProtectedRoute({
  children,
  requireItar = false,
  requireAdmin = false,
}: ProtectedRouteProps) {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center text-sm text-slate-600">
        Loading authentication...
      </div>
    );
  }

  if (!user) {
    return <LoginPage />;
  }

  if (requireItar && !user.isItarCleared) {
    return (
      <div className="min-h-screen flex items-center justify-center px-4">
        <div className="max-w-lg rounded-xl border border-amber-300 bg-amber-50 p-6 text-amber-900">
          <h2 className="text-xl font-semibold mb-2">ITAR Access Required</h2>
          <p className="text-sm">
            This workflow is restricted to verified U.S. person accounts with ITAR clearance.
            Contact a MIRA administrator to request access.
          </p>
        </div>
      </div>
    );
  }

  if (requireAdmin && !user.isAdmin) {
    return (
      <div className="min-h-screen flex items-center justify-center px-4">
        <div className="max-w-lg rounded-xl border border-red-300 bg-red-50 p-6 text-red-900">
          <h2 className="text-xl font-semibold mb-2">Admin Access Required</h2>
          <p className="text-sm">This area is restricted to MIRA administrators.</p>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}

