"""schema_evolution.py — Schema auto-evolution for state-canon.

Provides:
  - SchemaTracker: snapshots schema over time
  - SchemaReconciler: detects schema drift (field_added, field_removed, etc.)
  - DriftAnalyzer: analyzes drift patterns over time
  - SchemaEvolution: orchestrates schema evolution

Architecture:
  state-canon → schema_evolution → drift detection → pattern analysis → schema update

This enables second-order cybernetics: the state-canon schema evolves
automatically based on observed drift patterns.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass
class SchemaSnapshot:
    """Snapshot of a domain's schema at a point in time."""
    
    domain: str
    fields: Dict[str, str]  # field_name -> type_name
    record_count: int
    timestamp: str
    provider: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SchemaSnapshot":
        return cls(
            domain=data["domain"],
            fields=data["fields"],
            record_count=data["record_count"],
            timestamp=data["timestamp"],
            provider=data.get("provider", ""),
        )


@dataclass
class SchemaDrift:
    """Schema-level drift detection."""
    
    kind: str  # "field_added", "field_removed", "field_type_changed", "domain_added", "domain_removed"
    domain: str
    subject: str  # field name or domain name
    detail: str
    evidence: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DriftPattern:
    """Detected pattern in drift history."""
    
    pattern_type: str  # "persistent", "recurring", "increasing", "decreasing"
    domain: str
    subject: str
    description: str
    confidence: float  # 0.0 to 1.0
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SchemaTracker:
    """Tracks schema snapshots over time.
    
    Usage:
        tracker = SchemaTracker()
        tracker.snapshot("services", {"name": "str", "status": "str"}, 5)
        history = tracker.get_history("services")
    """
    
    def __init__(self, state_file: str | Path | None = None):
        if state_file:
            self.state_file = Path(state_file)
        else:
            self.state_file = Path.home() / "vOSlab" / "state_canon_schema_history.json"
        
        self.snapshots: List[SchemaSnapshot] = []
        self._load()
    
    def _load(self) -> None:
        """Load state from JSON file."""
        if self.state_file.exists():
            try:
                with open(self.state_file, "r") as f:
                    data = json.load(f)
                self.snapshots = [
                    SchemaSnapshot.from_dict(s) for s in data.get("snapshots", [])
                ]
            except (json.JSONDecodeError, KeyError):
                pass
    
    def save(self) -> None:
        """Save state to JSON file."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        
        data = {
            "snapshots": [s.to_dict() for s in self.snapshots[-1000:]],  # Keep last 1000
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        
        with open(self.state_file, "w") as f:
            json.dump(data, f, indent=2)
    
    def snapshot(
        self,
        domain: str,
        fields: Dict[str, str],
        record_count: int,
        provider: str = "",
    ) -> SchemaSnapshot:
        """Take a schema snapshot for a domain.
        
        Args:
            domain: Domain name
            fields: Field names to type names mapping
            record_count: Number of records in domain
            provider: Provider identifier
        
        Returns:
            SchemaSnapshot with timestamp
        """
        snap = SchemaSnapshot(
            domain=domain,
            fields=fields,
            record_count=record_count,
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            provider=provider,
        )
        self.snapshots.append(snap)
        return snap
    
    def get_history(self, domain: str, limit: int = 10) -> List[SchemaSnapshot]:
        """Get schema history for a domain."""
        return [s for s in self.snapshots if s.domain == domain][-limit:]
    
    def get_latest(self, domain: str) -> Optional[SchemaSnapshot]:
        """Get latest schema snapshot for a domain."""
        history = self.get_history(domain, limit=1)
        return history[0] if history else None
    
    def get_all_domains(self) -> List[str]:
        """Get all domains with snapshots."""
        return list(set(s.domain for s in self.snapshots))


class SchemaReconciler:
    """Detects schema drift between snapshots.
    
    Usage:
        reconciler = SchemaReconciler()
        drifts = reconciler.diff(old_snapshot, new_snapshot)
    """
    
    def diff(
        self,
        old: SchemaSnapshot,
        new: SchemaSnapshot,
    ) -> List[SchemaDrift]:
        """Compare two schema snapshots and detect drift.
        
        Args:
            old: Previous schema snapshot
            new: Current schema snapshot
        
        Returns:
            List of SchemaDrift objects
        """
        drifts = []
        
        old_fields = set(old.fields.keys())
        new_fields = set(new.fields.keys())
        
        # Detect field additions
        added = new_fields - old_fields
        for field_name in added:
            drifts.append(SchemaDrift(
                kind="field_added",
                domain=new.domain,
                subject=field_name,
                detail=f"New field '{field_name}' ({new.fields[field_name]}) added to {new.domain}",
                evidence={
                    "old_fields": list(old_fields),
                    "new_fields": list(new_fields),
                    "field_type": new.fields[field_name],
                },
            ))
        
        # Detect field removals
        removed = old_fields - new_fields
        for field_name in removed:
            drifts.append(SchemaDrift(
                kind="field_removed",
                domain=new.domain,
                subject=field_name,
                detail=f"Field '{field_name}' ({old.fields[field_name]}) removed from {new.domain}",
                evidence={
                    "old_fields": list(old_fields),
                    "new_fields": list(new_fields),
                    "field_type": old.fields[field_name],
                },
            ))
        
        # Detect field type changes
        common = old_fields & new_fields
        for field_name in common:
            old_type = old.fields[field_name]
            new_type = new.fields[field_name]
            if old_type != new_type:
                drifts.append(SchemaDrift(
                    kind="field_type_changed",
                    domain=new.domain,
                    subject=field_name,
                    detail=f"Field '{field_name}' type changed from {old_type} to {new_type}",
                    evidence={
                        "old_type": old_type,
                        "new_type": new_type,
                    },
                ))
        
        return drifts


class DriftAnalyzer:
    """Analyzes drift patterns over time.
    
    Usage:
        analyzer = DriftAnalyzer()
        patterns = analyzer.analyze(drift_history)
    """
    
    def analyze(
        self,
        drift_history: List[List[SchemaDrift]],
        min_occurrences: int = 3,
    ) -> List[DriftPattern]:
        """Analyze drift history and detect patterns.
        
        Args:
            drift_history: List of drift lists (one per snapshot)
            min_occurrences: Minimum occurrences to consider a pattern
        
        Returns:
            List of detected patterns
        """
        patterns = []
        
        # Count drift occurrences by (kind, domain, subject)
        counts: Dict[Tuple[str, str, str], List[int]] = {}
        for i, drifts in enumerate(drift_history):
            for d in drifts:
                key = (d.kind, d.domain, d.subject)
                if key not in counts:
                    counts[key] = []
                counts[key].append(i)
        
        # Analyze patterns
        for (kind, domain, subject), indices in counts.items():
            if len(indices) < min_occurrences:
                continue
            
            # Check for persistent drift (appeared in >50% of snapshots)
            persistence = len(indices) / len(drift_history) if drift_history else 0
            if persistence > 0.5:
                patterns.append(DriftPattern(
                    pattern_type="persistent",
                    domain=domain,
                    subject=subject,
                    description=f"Drift '{kind}' for '{subject}' in {domain} persists in {persistence:.0%} of snapshots",
                    confidence=persistence,
                    evidence=[{"snapshot_index": i for i in indices}],
                ))
            
            # Check for recurring drift (gaps in indices)
            if len(indices) >= 3:
                gaps = [indices[i+1] - indices[i] for i in range(len(indices)-1)]
                if any(g > 1 for g in gaps):
                    patterns.append(DriftPattern(
                        pattern_type="recurring",
                        domain=domain,
                        subject=subject,
                        description=f"Drift '{kind}' for '{subject}' in {domain} recurs with gaps",
                        confidence=0.7,
                        evidence=[{"indices": indices, "gaps": gaps}],
                    ))
            
            # Check for increasing frequency
            if len(indices) >= 4:
                first_half = len(indices[:len(indices)//2])
                second_half = len(indices[len(indices)//2:])
                if second_half > first_half * 1.5:
                    patterns.append(DriftPattern(
                        pattern_type="increasing",
                        domain=domain,
                        subject=subject,
                        description=f"Drift '{kind}' for '{subject}' in {domain} is increasing",
                        confidence=0.8,
                        evidence=[{"first_half": first_half, "second_half": second_half}],
                    ))
        
        return patterns


class SchemaEvolution:
    """Orchestrates schema evolution based on drift patterns.
    
    Usage:
        evolution = SchemaEvolution()
        proposals = evolution.propose(schema_history, drift_patterns)
        evolution.apply(proposals)
    """
    
    def __init__(self, state_file: str | Path | None = None):
        self.tracker = SchemaTracker(state_file)
        self.reconciler = SchemaReconciler()
        self.analyzer = DriftAnalyzer()
    
    def snapshot_all(
        self,
        provider: Any,
        domains: List[str] | None = None,
    ) -> List[SchemaSnapshot]:
        """Take schema snapshots for all domains.
        
        Args:
            provider: StateProvider instance
            domains: Optional list of domains (default: all)
        
        Returns:
            List of snapshots
        """
        if domains is None:
            domains = provider.list_domains()
        
        snapshots = []
        for domain in domains:
            try:
                records = provider.query(domain)
                if records:
                    schema = provider.schema(domain)
                    snap = self.tracker.snapshot(
                        domain=domain,
                        fields=schema,
                        record_count=len(records),
                        provider=provider.__class__.__name__,
                    )
                    snapshots.append(snap)
            except Exception:
                pass
        
        self.tracker.save()
        return snapshots
    
    def detect_drift(self) -> List[SchemaDrift]:
        """Detect schema drift by comparing latest snapshots.
        
        Returns:
            List of schema drifts
        """
        drifts = []
        domains = self.tracker.get_all_domains()
        
        for domain in domains:
            history = self.tracker.get_history(domain, limit=2)
            if len(history) >= 2:
                old, new = history[-2], history[-1]
                domain_drifts = self.reconciler.diff(old, new)
                drifts.extend(domain_drifts)
        
        return drifts
    
    def analyze_patterns(
        self,
        lookback: int = 10,
        min_occurrences: int = 3,
    ) -> List[DriftPattern]:
        """Analyze drift patterns over recent history.
        
        Args:
            lookback: Number of snapshots to analyze
            min_occurrences: Minimum occurrences to consider
        
        Returns:
            List of detected patterns
        """
        domains = self.tracker.get_all_domains()
        all_patterns = []
        
        for domain in domains:
            history = self.tracker.get_history(domain, limit=lookback)
            if len(history) < 2:
                continue
            
            # Generate drift history by comparing consecutive snapshots
            drift_history = []
            for i in range(1, len(history)):
                drifts = self.reconciler.diff(history[i-1], history[i])
                drift_history.append(drifts)
            
            # Analyze patterns
            patterns = self.analyzer.analyze(drift_history, min_occurrences)
            all_patterns.extend(patterns)
        
        return all_patterns
    
    def propose(
        self,
        provider: Any,
        confidence_threshold: float = 0.7,
    ) -> List[Dict[str, Any]]:
        """Propose schema changes based on drift patterns.
        
        Args:
            provider: StateProvider instance
            confidence_threshold: Minimum confidence to propose
        
        Returns:
            List of proposals
        """
        # Take fresh snapshots
        self.snapshot_all(provider)
        
        # Detect current drift
        drifts = self.detect_drift()
        
        # Analyze patterns
        patterns = self.analyze_patterns()
        
        # Generate proposals
        proposals = []
        
        for pattern in patterns:
            if pattern.confidence < confidence_threshold:
                continue
            
            if pattern.pattern_type == "persistent" and "field_added" in pattern.description:
                # Propose adding field to schema
                proposals.append({
                    "type": "add_field",
                    "domain": pattern.domain,
                    "field": pattern.subject,
                    "reason": pattern.description,
                    "confidence": pattern.confidence,
                })
            
            elif pattern.pattern_type == "persistent" and "field_removed" in pattern.description:
                # Propose removing field from schema
                proposals.append({
                    "type": "remove_field",
                    "domain": pattern.domain,
                    "field": pattern.subject,
                    "reason": pattern.description,
                    "confidence": pattern.confidence,
                })
        
        return proposals
    
    def get_status(self) -> Dict[str, Any]:
        """Get current schema evolution status."""
        domains = self.tracker.get_all_domains()
        drifts = self.detect_drift()
        patterns = self.analyze_patterns()
        
        return {
            "domains_tracked": len(domains),
            "domains": domains,
            "current_drifts": len(drifts),
            "drift_kinds": list(set(d.kind for d in drifts)),
            "patterns_detected": len(patterns),
            "pattern_types": list(set(p.pattern_type for p in patterns)),
            "high_confidence_patterns": len([p for p in patterns if p.confidence > 0.7]),
        }


# Global instance
_evolution: Optional[SchemaEvolution] = None


def get_schema_evolution() -> SchemaEvolution:
    """Get or create the global schema evolution instance."""
    global _evolution
    if _evolution is None:
        _evolution = SchemaEvolution()
    return _evolution


def snapshot_schema(provider: Any, domains: List[str] | None = None) -> List[SchemaSnapshot]:
    """Take schema snapshots."""
    return get_schema_evolution().snapshot_all(provider, domains)


def detect_schema_drift() -> List[SchemaDrift]:
    """Detect schema drift."""
    return get_schema_evolution().detect_drift()


def get_schema_patterns() -> List[DriftPattern]:
    """Get detected drift patterns."""
    return get_schema_evolution().analyze_patterns()
