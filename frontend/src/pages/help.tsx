import { Link } from "react-router-dom";

import { useI18n } from "../i18n";

export function HelpPage(): JSX.Element {
  const { t } = useI18n();

  return (
    <div className="stack-layout">
      <section className="page-header">
        <div>
          <p className="page-eyebrow">{t("layout.help")}</p>
          <h1 className="page-title">{t("help.title")}</h1>
          <p className="page-subtitle">{t("help.subtitle")}</p>
        </div>
      </section>

      <div className="grid">
        <section className="surface-panel">
          <p className="surface-panel-label">{t("help.quickStart")}</p>
          <h2 className="surface-panel-title">{t("help.primaryPathTitle")}</h2>
          <p className="surface-panel-note">{t("help.primaryPathBody")}</p>
          <div className="dashboard-hero-actions">
            <Link className="btn" to="/monitoring" viewTransition>{t("nav.monitoring")}</Link>
            <Link className="btn secondary" to="/logs" viewTransition>{t("nav.logs")}</Link>
          </div>
        </section>

        <section className="surface-panel">
          <p className="surface-panel-label">{t("help.troubleshoot")}</p>
          <h2 className="surface-panel-title">{t("help.commonIssuesTitle")}</h2>
          <ol className="help-list">
            <li>{t("help.metricsIssue")}</li>
            <li>{t("help.toolIssue")}</li>
            <li>{t("help.adapterIssue")}</li>
          </ol>
        </section>
      </div>

      <section className="surface-panel">
        <p className="surface-panel-label">{t("help.fastPaths")}</p>
        <h2 className="surface-panel-title">{t("help.fastPathsTitle")}</h2>
        <div className="tool-grid">
          <Link className="surface-panel tool-card" to="/monitoring" viewTransition>
            <h3>{t("nav.monitoring")}</h3>
            <p>{t("help.monitoringHint")}</p>
          </Link>
          <Link className="surface-panel tool-card" to="/logs" viewTransition>
            <h3>{t("nav.logs")}</h3>
            <p>{t("help.logsHint")}</p>
          </Link>
          <Link className="surface-panel tool-card" to="/tools" viewTransition>
            <h3>{t("nav.tools")}</h3>
            <p>{t("help.toolsHint")}</p>
          </Link>
          <Link className="surface-panel tool-card" to="/settings" viewTransition>
            <h3>{t("nav.settings")}</h3>
            <p>{t("help.settingsHint")}</p>
          </Link>
        </div>
      </section>
    </div>
  );
}
