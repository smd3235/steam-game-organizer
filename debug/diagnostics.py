from core.constants import APP_NAME


class Diagnostics:
    """A diagnostic report for troubleshooting: project layout, config state,
    library paths, and tool availability. Built from the objects the app
    already holds, so it never reaches for anything that isn't there."""

    def __init__(self, config, state, logger):
        self.config = config
        self.state = state
        self.logger = logger

    def report(self):
        """A multi-line text report suitable for pasting into a support ticket."""
        lines = []
        lines.append("DIAGNOSTIC REPORT")
        lines.append("=" * 40)
        lines.append("")
        lines.append(f"App: {APP_NAME}")
        lines.append(f"Project root: {self.config.project_root}")
        lines.append(f"Config dir: {getattr(self.config, 'config_dir', 'n/a')}")
        lines.append(f"Library root: {self.config.library_root}")
        lines.append(f"Library exists: {self.config.library_root.is_dir() if self.config.library_root else False}")
        lines.append(f"Developer mode: {self.config.developer_mode}")
        lines.append("")
        lines.append("Settings:")
        for key, value in (self.config.settings or {}).items():
            lines.append(f"  {key}: {value}")
        lines.append("")
        lines.append("State:")
        try:
            st = self.state.get()
            for field in ("scan", "organize", "extract"):
                lines.append(f"  {field}: {getattr(st, field, 'n/a')}")
        except Exception as exc:
            lines.append(f"  (unavailable: {type(exc).__name__})")
        lines.append("")
        lines.append(f"Log file: {getattr(self.logger, 'path', 'n/a')}")
        lines.append("")
        lines.append("End of report")
        return "\n".join(lines)

    def health(self):
        """A dict of health-check results keyed by concern."""
        project_root = self.config.project_root
        return {
            "project_root": str(project_root),
            "project_root_exists": project_root.is_dir(),
            "library_root": str(self.config.library_root) if self.config.library_root else None,
            "library_root_exists": self.config.library_root.is_dir() if self.config.library_root else False,
        }

    def health_text(self):
        """A single-line health summary."""
        h = self.health()
        parts = []
        parts.append(f"project_root={'ok' if h['project_root_exists'] else 'missing'}")
        parts.append(f"library={'ok' if h['library_root_exists'] else 'missing'}")
        return " | ".join(parts)
