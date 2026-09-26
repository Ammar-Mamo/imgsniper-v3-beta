"""
Script to update import paths after restructuring

DISABLED -- audit finding P3-7.

This is a leftover migration script from an earlier restructuring. Its
replacement table points at modules that NO LONGER EXIST (watermark_remover,
text_detector, logo_detector, watermark_detector, watermark_model_manager,
watermark_processor, transparent_detector, model_manager). Running it today
would rewrite imports across the whole of src/ toward non-existent paths and
CORRUPT the source tree.

It is kept on disk only because the project has no git history yet, so deleting
it would be irreversible. Delete it once a baseline commit exists.
"""

import sys

sys.stderr.write(
    "\n[DISABLED] update_imports.py is a stale restructuring migration script.\n"
    "           Running it would rewrite imports across src/ toward modules that\n"
    "           no longer exist and corrupt the source tree (audit P3-7).\n"
    "           Nothing was modified. Exiting.\n\n"
)
sys.exit(2)

import os
import re
from pathlib import Path

def update_imports_in_file(file_path):
    """Update import statements in a single file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original_content = content
        
        # Update imports based on new structure
        replacements = {
            # Core imports
            'from ..core.config import': 'from ..config import',
            'from ...core.config import': 'from ...config import',
            'from ....core.config import': 'from ....config import',
            
            # i18n imports
            'from ..core.i18n import': 'from ..i18n.i18n import',
            'from ...core.i18n import': 'from ...i18n.i18n import',
            'from ....core.i18n import': 'from ....i18n.i18n import',
            
            # Processors imports
            'from .corruption_detector import': 'from ..detectors.corruption_detector import',
            'from .duplicate_detector import': 'from ..detectors.duplicate_detector import',
            'from .similarity_detector import': 'from ..detectors.similarity_detector import',
            
            # Utils imports
            'from ..utils.file_utils import': 'from ...utils.helpers.file_utils import',
            'from ...utils.file_utils import': 'from ....utils.helpers.file_utils import',
            'from ..utils.scan_modes import': 'from ...utils.helpers.scan_modes import',
            'from ..utils.system_monitor import': 'from ...utils.helpers.system_monitor import',
            'from ..utils.date_extractor import': 'from ...utils.helpers.date_extractor import',
            'from ..utils.dimension_input import': 'from ...utils.helpers.dimension_input import',
            'from ..utils.model_manager import': 'from ...utils.helpers.model_manager import',
            
            # Report imports
            'from ..utils.report_generator import': 'from ...utils.reports.report_generator import',
            'from ...utils.report_generator import': 'from ....utils.reports.report_generator import',
            'from ..utils.report_formatter import': 'from ...utils.reports.report_formatter import',
            'from ..utils.image_info_extractor import': 'from ...utils.reports.image_info_extractor import',
            
            # Watermark imports
            'from .watermark_remover import': 'from ..watermark.watermark_remover import',
            'from .text_detector import': 'from ..watermark.text_detector import',
            'from .logo_detector import': 'from ..watermark.logo_detector import',
            'from .watermark_detector import': 'from ..watermark.watermark_detector import',
            'from .watermark_model_manager import': 'from ..watermark.watermark_model_manager import',
            'from .watermark_processor import': 'from ..watermark.watermark_processor import',
            'from .transparent_detector import': 'from ..watermark.transparent_detector import',
        }
        
        # Apply replacements
        for old_import, new_import in replacements.items():
            content = content.replace(old_import, new_import)
        
        # Save if changed
        if content != original_content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"Updated: {file_path}")
            return True
        return False
        
    except Exception as e:
        print(f"Error updating {file_path}: {e}")
        return False

def main():
    """Update all Python files in the project."""
    project_root = Path(__file__).parent.parent
    src_dir = project_root / "src"
    
    updated_files = 0
    total_files = 0
    
    # Find all Python files
    for py_file in src_dir.rglob("*.py"):
        if "__pycache__" not in str(py_file):
            total_files += 1
            if update_imports_in_file(py_file):
                updated_files += 1
    
    print(f"\nSummary:")
    print(f"Total Python files: {total_files}")
    print(f"Updated files: {updated_files}")
    print(f"No changes needed: {total_files - updated_files}")

if __name__ == "__main__":
    main()