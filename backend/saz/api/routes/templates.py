"""Templates API router for flow examples."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from saz.examples import get_template_manager

router = APIRouter(prefix="/api/templates", tags=["templates"])


# Response models
class TemplateMetadataResponse(BaseModel):
    """Metadata for a flow template."""

    id: str
    title: str
    description: str
    tags: list[str]
    complexity: str
    recommended: bool


class TemplateSummaryResponse(BaseModel):
    """Summary of a template with compiled info."""

    id: str
    title: str
    description: str
    tags: list[str]
    complexity: str
    recommended: bool
    flow_name: str
    steps_count: int
    ai_steps: int
    credentials: list[str]


class TemplateDetailResponse(BaseModel):
    """Full template details with YAML content."""

    metadata: TemplateMetadataResponse
    yaml: str
    flow_name: str
    flow_version: str
    flow_description: str
    steps_count: int
    ai_steps: int
    credentials: list[str]
    form_schema: dict


@router.get("/", response_model=list[TemplateSummaryResponse])
async def list_templates(recommended_only: bool = False):
    """
    List all available flow templates.

    Query params:
    - recommended_only: If true, only return recommended templates
    """
    manager = get_template_manager()

    templates = manager.list_recommended() if recommended_only else manager.list_templates()

    result = []
    for t in templates:
        # Extract workflow info from compiled spec
        workflow_steps = t.compiled.workflow_spec.get("steps", [])
        ai_steps_count = sum(1 for step in workflow_steps if step.get("type", "").startswith("ai."))

        result.append(
            TemplateSummaryResponse(
                id=t.metadata.id,
                title=t.metadata.title,
                description=t.metadata.description,
                tags=t.metadata.tags,
                complexity=t.metadata.complexity,
                recommended=t.metadata.recommended,
                flow_name=t.compiled.flow_name,
                steps_count=len(workflow_steps),
                ai_steps=ai_steps_count,
                credentials=t.compiled.credentials,
            )
        )

    return result


@router.get("/{template_id}", response_model=TemplateDetailResponse)
async def get_template(template_id: str):
    """
    Get full details and YAML content for a specific template.

    Path params:
    - template_id: The unique ID of the template
    """
    manager = get_template_manager()
    template = manager.get_template(template_id)

    if not template:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")

    # Extract workflow info from compiled spec
    workflow_steps = template.compiled.workflow_spec.get("steps", [])
    ai_steps_count = sum(1 for step in workflow_steps if step.get("type", "").startswith("ai."))

    return TemplateDetailResponse(
        metadata=TemplateMetadataResponse(
            id=template.metadata.id,
            title=template.metadata.title,
            description=template.metadata.description,
            tags=template.metadata.tags,
            complexity=template.metadata.complexity,
            recommended=template.metadata.recommended,
        ),
        yaml=template.yaml_content,
        flow_name=template.compiled.flow_name,
        flow_version=template.compiled.flow_version or "1.0",
        flow_description=template.compiled.flow_description or "",
        steps_count=len(workflow_steps),
        ai_steps=ai_steps_count,
        credentials=template.compiled.credentials,
        form_schema=template.compiled.form_schema or {},
    )
