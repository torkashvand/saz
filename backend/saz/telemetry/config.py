"""Telemetry configuration."""

from enum import Enum


class TelemetryLevel(str, Enum):
    """Telemetry trace level."""

    OFF = "off"  # No telemetry
    META = "meta"  # Minimal: step transitions, verdicts, progress
    BRIEF = "brief"  # META + tool calls, policy stats, timing
    VERBOSE = "verbose"  # BRIEF + input summaries, detailed stats


class TelemetryConfig:
    """Telemetry configuration for a workflow run."""

    def __init__(
        self,
        trace_level: TelemetryLevel = TelemetryLevel.META,
        sample_rate: float = 1.0,
    ):
        """
        Initialize telemetry config.

        Args:
            trace_level: Level of detail to emit (off/meta/brief/verbose)
            sample_rate: Sampling rate (0.0-1.0), default 1.0 (all runs)
        """
        self.trace_level = trace_level
        self.sample_rate = max(0.0, min(1.0, sample_rate))

    @classmethod
    def from_dsl(cls, telemetry_dict: dict | None) -> "TelemetryConfig":
        """
        Create config from DSL telemetry section.

        Args:
            telemetry_dict: DSL telemetry configuration

        Returns:
            TelemetryConfig instance
        """
        if not telemetry_dict:
            return cls()

        trace_level_str = telemetry_dict.get("trace_level", "meta")
        try:
            trace_level = TelemetryLevel(trace_level_str)
        except ValueError:
            trace_level = TelemetryLevel.META

        sample_rate = telemetry_dict.get("sample_rate", 1.0)

        return cls(trace_level=trace_level, sample_rate=sample_rate)

    def should_emit(self, level: TelemetryLevel) -> bool:
        """
        Check if we should emit events at the given level.

        Args:
            level: Level to check

        Returns:
            True if this level should be emitted
        """
        if self.trace_level == TelemetryLevel.OFF:
            return False

        level_order = {
            TelemetryLevel.META: 1,
            TelemetryLevel.BRIEF: 2,
            TelemetryLevel.VERBOSE: 3,
        }

        return level_order.get(level, 0) <= level_order.get(self.trace_level, 0)

    def is_enabled(self) -> bool:
        """Check if telemetry is enabled."""
        return self.trace_level != TelemetryLevel.OFF
