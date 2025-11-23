"""Template manager for loading and validating flow templates."""

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

from saz.compiler import DSLCompiled, compile_dsl

logger = logging.getLogger(__name__)


@dataclass
class TemplateMetadata:
    """Metadata for a flow template."""

    id: str
    title: str
    description: str
    tags: list[str]
    complexity: str  # low, medium, high
    recommended: bool


@dataclass
class FlowTemplate:
    """A validated flow template."""

    metadata: TemplateMetadata
    yaml_content: str
    compiled: DSLCompiled
    file_path: str


class TemplateManager:
    """Manages loading and validation of flow templates."""

    def __init__(self, templates_dir: Path | None = None):
        if templates_dir is None:
            # Default to unified/ subdirectory in this module
            self_dir = Path(__file__).parent
            templates_dir = self_dir / "unified"

        self.templates_dir = templates_dir
        self.templates: dict[str, FlowTemplate] = {}
        self._loaded = False

    def load_templates(self) -> None:
        """Load and validate all templates from the templates directory."""
        if self._loaded:
            return

        if not self.templates_dir.exists():
            logger.warning(f"Templates directory does not exist: {self.templates_dir}")
            self._loaded = True
            return

        logger.info(f"Loading templates from {self.templates_dir}")

        yaml_files = list(self.templates_dir.glob("*.yaml"))
        if not yaml_files:
            logger.warning(f"No YAML files found in {self.templates_dir}")
            self._loaded = True
            return

        loaded_count = 0
        failed_count = 0

        for yaml_file in yaml_files:
            try:
                template = self._load_template(yaml_file)
                if template:
                    self.templates[template.metadata.id] = template
                    loaded_count += 1
                    logger.info(
                        f"Loaded template: {template.metadata.id} ({template.metadata.title})"
                    )
                else:
                    failed_count += 1
            except Exception as e:
                logger.error(f"Failed to load template {yaml_file.name}: {e}")
                failed_count += 1

        logger.info(f"Templates loaded: {loaded_count} succeeded, {failed_count} failed")
        self._loaded = True

    def _load_template(self, yaml_file: Path) -> FlowTemplate | None:
        """Load and validate a single template file."""
        try:
            yaml_content = yaml_file.read_text(encoding='utf-8')

            # Parse YAML to extract metadata
            parsed = yaml.safe_load(yaml_content)

            if 'meta' not in parsed:
                logger.warning(f"Template {yaml_file.name} missing 'meta' section")
                return None

            meta_dict = parsed['meta']

            # Extract metadata
            metadata = TemplateMetadata(
                id=meta_dict.get('id', yaml_file.stem),
                title=meta_dict.get('title', yaml_file.stem),
                description=meta_dict.get('description', ''),
                tags=meta_dict.get('tags', []),
                complexity=meta_dict.get('complexity', 'medium'),
                recommended=meta_dict.get('recommended', False),
            )

            # Remove meta section for compilation
            yaml_for_compile = yaml_content
            if 'meta:' in yaml_content:
                # Remove the meta section (simple string manipulation)
                lines = yaml_content.split('\n')
                cleaned_lines = []
                in_meta = False
                for line in lines:
                    if line.strip().startswith('meta:'):
                        in_meta = True
                        continue
                    if in_meta:
                        # Check if we've exited the meta section
                        if line and not line.startswith(' ') and not line.startswith('\t'):
                            in_meta = False
                        else:
                            continue
                    if not in_meta:
                        cleaned_lines.append(line)
                yaml_for_compile = '\n'.join(cleaned_lines)

            # Compile and validate
            try:
                compiled = compile_dsl(yaml_for_compile)
            except Exception as e:
                logger.error(f"Template {metadata.id} failed compilation: {e}")
                return None

            return FlowTemplate(
                metadata=metadata,
                yaml_content=yaml_for_compile,  # Store cleaned YAML without meta
                compiled=compiled,
                file_path=str(yaml_file),
            )

        except Exception as e:
            logger.error(f"Error processing template {yaml_file.name}: {e}")
            return None

    def get_template(self, template_id: str) -> FlowTemplate | None:
        """Get a template by ID."""
        if not self._loaded:
            self.load_templates()
        return self.templates.get(template_id)

    def list_templates(self) -> list[FlowTemplate]:
        """List all available templates."""
        if not self._loaded:
            self.load_templates()
        return list(self.templates.values())

    def list_recommended(self) -> list[FlowTemplate]:
        """List recommended templates."""
        if not self._loaded:
            self.load_templates()
        return [t for t in self.templates.values() if t.metadata.recommended]


# Global singleton instance
_template_manager: TemplateManager | None = None


def get_template_manager() -> TemplateManager:
    """Get the global template manager instance."""
    global _template_manager
    if _template_manager is None:
        _template_manager = TemplateManager()
        _template_manager.load_templates()
    return _template_manager
