import { Component, type ReactNode } from "react";

interface State {
  hasError: boolean;
  error: Error | null;
}

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: { componentStack: string }): void {
    console.error("[ErrorBoundary]", error, info.componentStack);
  }

  handleReload = (): void => {
    this.setState({ hasError: false, error: null });
    void globalThis.location.reload();
  };

  render(): ReactNode {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <div style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          minHeight: "100vh",
          padding: "2rem",
          fontFamily: "system-ui, sans-serif",
          color: "#374151",
          gap: "1rem",
        }}>
          <h1 style={{ fontSize: "1.25rem", fontWeight: 600 }}>页面遇到问题</h1>
          <p style={{ maxWidth: "32rem", textAlign: "center", lineHeight: 1.6 }}>
            应用遇到未预期的错误。你可以刷新页面重试，或稍后再访问。
          </p>
          <button
            onClick={this.handleReload}
            style={{
              padding: "0.5rem 1.5rem",
              borderRadius: "0.375rem",
              border: "none",
              background: "#2563eb",
              color: "#fff",
              fontSize: "1rem",
              cursor: "pointer",
            }}
            type="button"
          >
            刷新页面
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
