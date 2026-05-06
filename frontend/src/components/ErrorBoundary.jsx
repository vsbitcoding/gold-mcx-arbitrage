import React from "react";

/**
 * Catch render-time / lifecycle errors in any descendant component and
 * render a friendly fallback instead of the white screen of death.
 * Console + reload button so the user can recover without restarting the tab.
 */
export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    // eslint-disable-next-line no-console
    console.error("[ErrorBoundary]", error, info);
  }

  reset = () => {
    this.setState({ error: null });
  };

  render() {
    if (!this.state.error) return this.props.children;
    const msg = String(this.state.error?.message || this.state.error || "Unknown error");
    return (
      <div className="error-boundary">
        <div className="error-boundary-card">
          <div className="error-boundary-title">Something broke</div>
          <div className="error-boundary-msg">{msg}</div>
          <div className="error-boundary-actions">
            <button className="btn btn-primary" onClick={() => window.location.reload()}>Reload</button>
            <button className="btn btn-secondary" onClick={this.reset}>Try again</button>
          </div>
          <details className="error-boundary-stack">
            <summary>Technical detail</summary>
            <pre>{String(this.state.error?.stack || "")}</pre>
          </details>
        </div>
      </div>
    );
  }
}
