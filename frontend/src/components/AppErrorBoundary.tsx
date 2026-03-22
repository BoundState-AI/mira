import { Component, type ErrorInfo, type ReactNode } from "react";

type AppErrorBoundaryProps = {
  children: ReactNode;
};

type AppErrorBoundaryState = {
  hasError: boolean;
  eventId: string;
};

export class AppErrorBoundary extends Component<AppErrorBoundaryProps, AppErrorBoundaryState> {
  state: AppErrorBoundaryState = {
    hasError: false,
    eventId: "",
  };

  static getDerivedStateFromError(): AppErrorBoundaryState {
    return {
      hasError: true,
      eventId: Math.random().toString(36).slice(2, 10),
    };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("Unhandled app render error", {
      error,
      componentStack: errorInfo.componentStack,
      eventId: this.state.eventId,
    });
  }

  private handleReload = () => {
    window.location.reload();
  };

  private handleHome = () => {
    window.location.assign("/");
  };

  render() {
    if (!this.state.hasError) {
      return this.props.children;
    }

    return (
      <div className="min-h-screen bg-slate-950 px-6 py-12 text-slate-100">
        <div className="mx-auto flex min-h-[70vh] max-w-3xl flex-col justify-center rounded-3xl border border-slate-800 bg-slate-900/90 p-8 shadow-2xl">
          <p className="text-sm font-semibold uppercase tracking-[0.24em] text-cyan-300">
            Application Error
          </p>
          <h1 className="mt-4 text-3xl font-semibold tracking-tight text-white">
            This page crashed before it finished rendering.
          </h1>
          <p className="mt-4 max-w-2xl text-base leading-7 text-slate-300">
            The app caught the failure instead of dropping you on a blank screen. Reload to try
            again, or go back to the home workspace and restart the flow.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <button
              className="rounded-xl bg-cyan-400 px-5 py-3 text-sm font-semibold text-slate-950 transition hover:bg-cyan-300"
              onClick={this.handleReload}
              type="button"
            >
              Reload App
            </button>
            <button
              className="rounded-xl border border-slate-700 px-5 py-3 text-sm font-semibold text-slate-100 transition hover:border-slate-500 hover:bg-slate-800"
              onClick={this.handleHome}
              type="button"
            >
              Go Home
            </button>
          </div>
          <p className="mt-8 text-sm text-slate-400">
            Error ID: <span className="font-mono text-slate-200">{this.state.eventId}</span>
          </p>
        </div>
      </div>
    );
  }
}
