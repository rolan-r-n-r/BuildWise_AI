import { Component, type ErrorInfo, type ReactNode } from 'react';
import { Icon } from './Icon';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  onReset?: () => void;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('BuildWise component error caught by boundary:', error, errorInfo);
  }

  public reset = () => {
    this.setState({ hasError: false, error: null });
    this.props.onReset?.();
  };

  public render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }
      return (
        <div
          role="alert"
          className="fixed inset-0 z-[1300] flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-xs select-none"
        >
          <div className="w-full max-w-md bg-white dark:bg-slate-900 rounded-[20px] border border-slate-200 dark:border-slate-800 shadow-2xl p-6 text-center space-y-4">
            <div className="w-12 h-12 rounded-full bg-red-100 dark:bg-red-950/60 text-red-600 dark:text-red-400 mx-auto flex items-center justify-center">
              <Icon name="alert-triangle" size={24} />
            </div>
            <div>
              <h3 className="text-[16px] font-bold text-[var(--text-1)]">
                Unable to load component
              </h3>
              <p className="text-[12px] text-[var(--text-2)] mt-1">
                {this.state.error?.message || 'An unexpected rendering error occurred.'}
              </p>
            </div>
            <button
              type="button"
              onClick={this.reset}
              className="px-4 py-2 bg-[var(--accent)] text-white text-[13px] font-semibold rounded-xl hover:brightness-110 active:brightness-95 transition-all cursor-pointer"
            >
              Dismiss
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
