from dataclasses import dataclass


@dataclass
class PipelineSummary:
    """Pipeline çalışması sonuç özeti."""
    total: int = 0
    resolved_count: int = 0
    unresolved_count: int = 0
    resolution_rate: float = 0.0
