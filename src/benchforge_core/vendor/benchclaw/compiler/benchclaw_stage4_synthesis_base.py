"""
benchclaw_stage4_synthesis_base.py - Parent base class for HABITAT-ISB benchmark synthesis.

All dataset-specific generators inherit from this base class.
This module handles common tasks: GT loading, image path resolution, validation.
"""

import json
import zlib
from pathlib import Path
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional


class BenchClawSynthesisBase(ABC):
    """Base class for Stage 4 synthesis tasks.

    Subclasses must implement:
    - generate_items() -> List[Dict]
    - get_dimension_map() -> Dict[str, Any]
    - get_allowed_templates() -> List[str]
    """

    def __init__(self, workspace_root: str, gt_path: Optional[str] = None):
        self.workspace_root = Path(workspace_root)
        self.gt_path = Path(gt_path) if gt_path else None
        self._gt_records = None

    def load_gt_records(self) -> List[Dict]:
        """Load ground truth records."""
        if self._gt_records is not None:
            return self._gt_records

        if not self.gt_path or not self.gt_path.exists():
            raise FileNotFoundError(f"GT path not found: {self.gt_path}")

        records = []
        with open(self.gt_path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        self._gt_records = records
        return self._gt_records

    def resolve_image_path(self, image_ref: str, scene: str, frame_num: str) -> str:
        """Resolve image path for model-visible dataset."""
        return f"./images/{scene}/{scene}_{frame_num}.png"

    @abstractmethod
    def generate_items(self) -> List[Dict[str, Any]]:
        """Generate benchmark items. Must be implemented by subclasses."""
        pass

    @abstractmethod
    def get_dimension_map(self) -> Dict[str, Any]:
        """Return dimension definitions."""
        pass

    @abstractmethod
    def get_allowed_templates(self) -> List[str]:
        """Return allowed template identifiers."""
        pass

    def validate_item(self, item: Dict) -> bool:
        """Validate a single benchmark item."""
        required_fields = ["item_id", "scene", "frame_id", "question", "dimension"]
        for field in required_fields:
            if field not in item or not item[field]:
                return False
        return True

    def validate_items(self, items: List[Dict]) -> Dict[str, int]:
        """Validate a batch of items, return counts."""
        valid = []
        invalid = []
        for item in items:
            if self.validate_item(item):
                valid.append(item)
            else:
                invalid.append(item)
        return {
            "total": len(items),
            "valid": len(valid),
            "invalid": len(invalid),
            "valid_items": valid,
            "invalid_items": invalid
        }


class SynthesisRunner:
    """Orchestrates the synthesis pipeline."""

    def __init__(self, base: BenchClawSynthesisBase, output_dir: str):
        self.base = base
        self.output_dir = Path(output_dir)

    def run_generate(self) -> List[Dict]:
        """Run item generation."""
        items = self.base.generate_items()
        validation = self.base.validate_items(items)
        print(f"[SynthesisRunner] Generated {validation['total']} items, {validation['valid']} valid, {validation['invalid']} invalid")
        return validation["valid_items"]

    def run(self):
        """Run full synthesis pipeline."""
        items = self.run_generate()
        return {"items": items, "validation": self.base.validate_items(items)}


if __name__ == "__main__":
    print("[benchclaw_stage4_synthesis_base] Parent runtime loaded successfully")
