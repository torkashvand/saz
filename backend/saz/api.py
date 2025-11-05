"""FastAPI service for agentic workflow registration and execution."""
from datetime import datetime, UTC
from uuid import UUID, uuid4
from contextlib import asynccontextmanager
import yaml
import structlog
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel as PydanticBase
from sqlalchemy.orm import Session
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from saz.db import get_db, FlowTable, RunTable, RunStepTable
from saz.compiler import compile_dsl
from saz.agents import PlannerAgent, ExecutorAgent, CriticAgent, Verdict
from saz.tools import create_default_registry
from saz.policies import create_default_policy_engine
from saz.db.models import ProcessStatusEnum
from saz.db.credentials import get_vault
from saz.triggers import TriggerScheduler
from saz.api_helpers import (
    build_flow_graph,
    build_run_status_map,
    validate_form_payload,
    extract_step_details
)

logger = structlog.get_logger(__name__)

# Initialize trigger scheduler globally
SCHEDULER = TriggerScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown."""
    # Startup
    SCHEDULER.start()
    logger.info("app_started", scheduler_running=SCHEDULER.scheduler.running)
    yield
    # Shutdown
    SCHEDULER.stop()
    logger.info("app_shutdown")


app = FastAPI(
    title="Saz Agentic Workflow API",
    version="0.2.0",
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Request/Response Models ---
class RegisterFlowRequest(PydanticBase):
    yaml: str


class RegisterFlowResponse(PydanticBase):
    flow_id: str
    name: str
    form_schema: dict
    workflow_summary: dict


class CreateRunRequest(PydanticBase):
    flow_id: str
    payload: dict


class CreateRunResponse(PydanticBase):
    run_id: str
    status: str


class GetRunResponse(PydanticBase):
    run_id: str
    flow_id: str
    status: str
    started_at: str
    completed_at: str | None
    totals: dict
    steps: list[dict]
    artifacts: list[str]
    failure_reason: str | None = None
    failing_step_id: str | None = None


class CreateCredentialRequest(PydanticBase):
    name: str
    credential_type: str
    data: dict
    description: str | None = None


class CreateCredentialResponse(PydanticBase):
    credential_id: str
    name: str
    credential_type: str


class CredentialListItem(PydanticBase):
    credential_id: str
    name: str
    description: str | None
    credential_type: str
    created_at: str
    updated_at: str


# --- Global Registry ---
# Initialize global tool registry and policy engine
TOOL_REGISTRY = create_default_registry(
    callback_base_url="http://localhost:8000",
    artifact_storage_path="/tmp/saz/artifacts"
)

POLICY_ENGINE = create_default_policy_engine(
    max_tokens=100000,
    max_cost_usd=10.0,
    max_steps=50,
    enforce_pii_redaction=False  # Warning only for now
)

# Initialize agents
PLANNER = PlannerAgent(model="gpt-4o")
EXECUTOR = ExecutorAgent()
CRITIC = CriticAgent(model="gpt-4o")


# --- Agentic Execution Loop ---
async def run_agentic_loop(
    run_id: UUID,
    workflow_spec: dict,
    current_data: dict,
    budget: dict,
    db: Session
) -> tuple[str, dict]:
    """
    Execute the agentic workflow loop: Plan → Execute → Critique → Continue.

    Returns:
        Tuple of (final_status, final_state)
    """
    run_id_str = str(run_id)
    completed_steps = []

    # Initialize policy engine for this run
    POLICY_ENGINE.initialize_run(run_id_str)

    logger.info("agentic_loop_start", run_id=run_id_str, workflow=workflow_spec.get("name"))

    try:
        # Step 1: Plan
        plan = await PLANNER.plan(
            workflow_spec=workflow_spec,
            tool_registry=TOOL_REGISTRY.get_tool_specs(),
            run_id=run_id_str,
            completed_steps=completed_steps,
            current_data=current_data,
            budget=POLICY_ENGINE.get_budget_status(run_id_str)
        )

        logger.info("plan_generated", run_id=run_id_str, steps=len(plan.steps))

        # Execute each step in the plan
        for step in plan.steps:
            # Record step in budget
            POLICY_ENGINE.record_step(run_id_str)

            # Check if step is human_approval or webhook_wait
            if step.action.value == "human_approval":
                # Store step and suspend
                logger.info("step_requires_human_approval", run_id=run_id_str, step_id=step.step_id)
                return "suspended", current_data

            if step.action.value == "webhook_wait":
                # Store step and wait for webhook
                logger.info("step_waiting_for_webhook", run_id=run_id_str, step_id=step.step_id)
                return "waiting", current_data

            # Step 2: Ground (Executor)
            tool_call = EXECUTOR.ground(
                step=step,
                tool_registry=TOOL_REGISTRY.get_tool_specs_dict(),
                current_data=current_data,
                run_id=run_id_str
            )

            # Step 3: Policy check
            allowed, reason = POLICY_ENGINE.check_tool_call(
                tool_name=tool_call.tool,
                arguments=tool_call.arguments,
                run_id=run_id_str
            )

            if not allowed:
                logger.error("policy_violation", run_id=run_id_str, reason=reason)
                return "failed", {"error": f"Policy violation: {reason}"}

            # Step 4: Execute tool
            try:
                result = await TOOL_REGISTRY.execute_tool(
                    tool_name=tool_call.tool,
                    arguments=tool_call.arguments,
                    idempotency_key=tool_call.idempotency_key,
                    run_id=run_id_str,
                    step_id=step.step_id
                )

                # Extract AI metadata if present
                ai_metadata = None
                step_tokens = None
                step_cost = None
                if isinstance(result, dict) and "usage" in result and "metadata" in result:
                    ai_metadata = {
                        "op": result["metadata"].get("op"),
                        "temperature": result["metadata"].get("temperature"),
                        "model": result["metadata"].get("model"),
                        "tokens": result["usage"].get("tokens"),
                        "cost_usd": result["usage"].get("cost_usd")
                    }
                    step_tokens = result["usage"].get("tokens", 0)
                    step_cost = result["usage"].get("cost_usd", 0.0)
                    # Extract actual output from AI result
                    result = result.get("output", result)

                # Redact PII from result
                result = POLICY_ENGINE.redact_output(result)

                # Build artifacts list
                artifacts_list = []
                if isinstance(result, dict) and "artifact_id" in result:
                    artifacts_list.append(result["artifact_id"])

                # Store step result with AI metadata and cost tracking
                step_record = RunStepTable(
                    run_id=run_id,
                    step_number=len(completed_steps),
                    step_name=step.step_id,
                    status="success",
                    input_data=step.input_template,
                    output_data=result if not ai_metadata else {"output": result, "ai": ai_metadata},
                    retry_count=0,
                    artifacts=artifacts_list if artifacts_list else None,
                    tokens=step_tokens,
                    cost_usd=step_cost
                )
                db.add(step_record)

                # Update run totals
                if step_tokens:
                    run = db.query(RunTable).filter(RunTable.run_id == run_id).first()
                    run.tokens_used += step_tokens
                    run.cost_usd += step_cost

                db.commit()

                # Merge result into current data
                if isinstance(result, dict):
                    current_data = {**current_data, **result, f"{step.step_id}_result": result}
                else:
                    current_data[f"{step.step_id}_result"] = result

            except Exception as e:
                logger.error("tool_execution_failed", run_id=run_id_str, step=step.step_id, error=str(e))

                # Log failed step
                step_record = RunStepTable(
                    run_id=run_id,
                    step_number=len(completed_steps),
                    step_name=step.step_id,
                    status="failed",
                    input_data=step.input_template,
                    error=str(e),
                    retry_count=0
                )
                db.add(step_record)
                db.commit()

                # Handle error based on step configuration
                if step.error_handling.value == "fail":
                    return "failed", {"error": str(e), "failed_step": step.step_id}
                elif step.error_handling.value == "escalate":
                    return "suspended", {**current_data, "error": str(e), "failed_step": step.step_id}
                else:
                    # Retry logic would go here
                    continue

            # Step 5: Critique
            critique = await CRITIC.critique(
                step=step,
                tool_call=tool_call.model_dump(),
                result=result,
                run_id=run_id_str,
                completed_steps=completed_steps,
                current_state=current_data
            )

            logger.info("critique_received", run_id=run_id_str, step=step.step_id, verdict=critique.verdict.value)

            # Handle critique verdict
            if critique.verdict == Verdict.FAIL:
                return "failed", {**current_data, "critique_reason": critique.reasoning}
            elif critique.verdict == Verdict.ESCALATE:
                return "suspended", {**current_data, "escalation_reason": critique.reasoning}
            elif critique.verdict == Verdict.REPLAN:
                # For now, treat replan as failure (full replanning not implemented yet)
                return "failed", {**current_data, "replan_needed": critique.reasoning}

            # Step passed, continue
            completed_steps.append(step.step_id)

        # All steps completed successfully
        logger.info("agentic_loop_complete", run_id=run_id_str)
        return "completed", current_data

    except Exception as e:
        logger.error("agentic_loop_failed", run_id=run_id_str, error=str(e))
        return "failed", {**current_data, "error": str(e)}


# --- Endpoints ---
@app.post("/runs", response_model=CreateRunResponse)
async def create_run(req: CreateRunRequest, db: Session = Depends(get_db)):
    """Create a new agentic workflow run with initial payload."""
    flow_id = UUID(req.flow_id)

    # Get flow from DB
    flow = db.query(FlowTable).filter(FlowTable.flow_id == flow_id).first()
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    # Get workflow spec and form schema from stored definition
    form_schema = flow.definition.get("form_schema")
    workflow_spec = flow.definition.get("workflow_spec")
    policies = flow.definition.get("policies", {})

    if not form_schema or not workflow_spec:
        raise HTTPException(status_code=500, detail="Flow missing required definition fields")

    # Validate payload against stored form schema
    is_valid, error_msg = validate_form_payload(req.payload, form_schema)
    if not is_valid:
        raise HTTPException(status_code=400, detail=f"Invalid payload: {error_msg}")
    validated_payload = req.payload

    # Create run in database
    run = RunTable(
        flow_id=flow_id,
        status=ProcessStatusEnum.RUNNING,
        current_state=validated_payload,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # Execute agentic workflow
    final_status, final_state = await run_agentic_loop(
        run_id=run.run_id,
        workflow_spec=workflow_spec,
        current_data=validated_payload,
        budget=policies.get("budget", {}),
        db=db
    )

    # Update run status
    run.status = ProcessStatusEnum(final_status)
    run.current_state = final_state
    if final_status == "completed":
        run.completed_at = datetime.now(UTC)
    db.commit()

    return CreateRunResponse(
        run_id=str(run.run_id),
        status=run.status.value,
    )


@app.get("/runs/{run_id}", response_model=GetRunResponse)
def get_run(run_id: str, db: Session = Depends(get_db)):
    """Get detailed run information with steps and totals."""
    run_uuid = UUID(run_id)
    run = db.query(RunTable).filter(RunTable.run_id == run_uuid).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    # Build step details
    steps_detail, artifacts_list, total_tokens, total_cost = extract_step_details(run.steps)

    return GetRunResponse(
        run_id=str(run.run_id),
        flow_id=str(run.flow_id),
        status=run.status.value,
        started_at=run.created_at.isoformat(),
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
        totals={
            "tokens": total_tokens,
            "cost_usd": round(total_cost, 6)
        },
        steps=steps_detail,
        artifacts=list(set(artifacts_list))  # Deduplicate
    )


@app.post("/credentials", response_model=CreateCredentialResponse)
def create_credential(req: CreateCredentialRequest, db: Session = Depends(get_db)):
    """Create encrypted credential."""
    vault = get_vault()

    try:
        credential = vault.create_credential(
            db=db,
            name=req.name,
            credential_type=req.credential_type,
            data=req.data,
            description=req.description
        )

        return CreateCredentialResponse(
            credential_id=str(credential.credential_id),
            name=credential.name,
            credential_type=credential.credential_type
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/credentials", response_model=list[CredentialListItem])
def list_credentials(db: Session = Depends(get_db)):
    """List all credentials (metadata only, no secrets)."""
    vault = get_vault()
    credentials = vault.list_credentials(db)
    return credentials


@app.delete("/credentials/{name}")
def delete_credential(name: str, db: Session = Depends(get_db)):
    """Delete credential by name."""
    vault = get_vault()

    if not vault.delete_credential(db, name):
        raise HTTPException(status_code=404, detail="Credential not found")

    return {"status": "deleted", "name": name}


@app.post("/webhooks/{flow_id}/trigger")
async def webhook_trigger(flow_id: str, payload: dict, db: Session = Depends(get_db)):
    """Trigger a workflow via webhook."""
    flow_uuid = UUID(flow_id)
    flow = db.query(FlowTable).filter(FlowTable.flow_id == flow_uuid).first()
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    # Get workflow spec and form schema from stored definition
    form_schema = flow.definition.get("form_schema")
    workflow_spec = flow.definition.get("workflow_spec")
    policies = flow.definition.get("policies", {})

    if not form_schema or not workflow_spec:
        raise HTTPException(status_code=500, detail="Flow missing required definition fields")

    # Validate payload against stored form schema
    try:
        required_fields = form_schema.get("required", [])
        for field in required_fields:
            if field not in payload:
                raise ValueError(f"Missing required field: {field}")
        validated_payload = payload
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid payload: {e}")

    # Create run
    run = RunTable(
        flow_id=flow_uuid,
        status=ProcessStatusEnum.RUNNING,
        current_state=validated_payload,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # Execute workflow asynchronously (in background)
    # For now, execute synchronously - in production use background tasks
    final_status, final_state = await run_agentic_loop(
        run_id=run.run_id,
        workflow_spec=workflow_spec,
        current_data=validated_payload,
        budget=policies.get("budget", {}),
        db=db
    )

    run.status = ProcessStatusEnum(final_status)
    run.current_state = final_state
    if final_status == "completed":
        run.completed_at = datetime.now(UTC)
    db.commit()

    return {
        "run_id": str(run.run_id),
        "status": run.status.value,
        "triggered_by": "webhook"
    }


@app.post("/runs/{run_id}/resume")
async def resume_run_webhook(run_id: str, callback_data: dict, db: Session = Depends(get_db)):
    """Resume a waiting run via webhook callback."""
    # Same as advance but specifically for webhook callbacks
    run_uuid = UUID(run_id)
    run = db.query(RunTable).filter(RunTable.run_id == run_uuid).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    if run.status != ProcessStatusEnum.WAITING:
        raise HTTPException(status_code=400, detail=f"Run not in waiting status: {run.status}")

    # Get workflow spec from stored definition
    flow = run.flow
    workflow_spec = flow.definition.get("workflow_spec")
    policies = flow.definition.get("policies", {})

    if not workflow_spec:
        raise HTTPException(status_code=500, detail="Flow missing workflow_spec")

    # Merge callback data
    updated_state = {**run.current_state, "webhook_callback": callback_data}

    # Resume workflow
    run.status = ProcessStatusEnum.RUNNING
    db.commit()

    final_status, final_state = await run_agentic_loop(
        run_id=run.run_id,
        workflow_spec=workflow_spec,
        current_data=updated_state,
        budget=policies.get("budget", {}),
        db=db
    )

    run.status = ProcessStatusEnum(final_status)
    run.current_state = final_state
    if final_status == "completed":
        run.completed_at = datetime.now(UTC)
    db.commit()

    return {
        "run_id": str(run.run_id),
        "status": run.status.value,
        "resumed_by": "webhook"
    }


@app.get("/runs/{run_id}/steps")
def get_run_steps(run_id: str, db: Session = Depends(get_db)):
    """Get execution history (all steps) for a run."""
    run_uuid = UUID(run_id)
    run = db.query(RunTable).filter(RunTable.run_id == run_uuid).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    steps = db.query(RunStepTable).filter(RunStepTable.run_id == run_uuid).order_by(RunStepTable.step_number).all()

    return {
        "run_id": str(run.run_id),
        "flow_id": str(run.flow_id),
        "status": run.status.value,
        "steps": [
            {
                "step_id": str(step.step_id),
                "step_number": step.step_number,
                "step_name": step.step_name,
                "status": step.status,
                "input_data": step.input_data,
                "output_data": step.output_data,
                "error": step.error,
                "retry_count": step.retry_count,
                "artifacts": step.artifacts,
                "started_at": step.started_at.isoformat(),
                "completed_at": step.completed_at.isoformat() if step.completed_at else None
            }
            for step in steps
        ]
    }


@app.get("/runs/{run_id}/compliance")
def get_run_compliance(run_id: str, db: Session = Depends(get_db)):
    """
    Get compliance report for a run: tokens, cost, policy violations.
    """
    run_uuid = UUID(run_id)
    run = db.query(RunTable).filter(RunTable.run_id == run_uuid).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    steps = db.query(RunStepTable).filter(RunStepTable.run_id == run_uuid).order_by(RunStepTable.step_number).all()

    # Aggregate AI costs
    total_tokens = 0
    total_cost_usd = 0.0
    ai_steps = []

    for step in steps:
        if step.output_data and isinstance(step.output_data, dict) and "ai" in step.output_data:
            ai_meta = step.output_data["ai"]
            tokens = ai_meta.get("tokens", 0)
            cost = ai_meta.get("cost_usd", 0.0)

            total_tokens += tokens
            total_cost_usd += cost

            ai_steps.append({
                "step_name": step.step_name,
                "op": ai_meta.get("op"),
                "tokens": tokens,
                "cost_usd": cost,
                "temperature": ai_meta.get("temperature"),
                "model": ai_meta.get("model")
            })

    # Get policy budget status
    budget_status = POLICY_ENGINE.get_budget_status(run_id)

    return {
        "run_id": str(run.run_id),
        "flow_id": str(run.flow_id),
        "status": run.status.value,
        "compliance": {
            "ai_usage": {
                "total_tokens": total_tokens,
                "total_cost_usd": round(total_cost_usd, 6),
                "steps_count": len(ai_steps),
                "steps": ai_steps
            },
            "budget": budget_status,
            "policy_violations": []  # TODO: Track policy violations
        }
    }


@app.post("/runs/{run_id}/replay")
async def replay_run(
    run_id: str,
    from_step: int = 0,
    db: Session = Depends(get_db)
):
    """
    Replay a run from a specific step number.

    Creates a new run with pinned inputs from the original run's step history.
    """
    run_uuid = UUID(run_id)
    original_run = db.query(RunTable).filter(RunTable.run_id == run_uuid).first()
    if not original_run:
        raise HTTPException(status_code=404, detail="Run not found")

    # Get original steps
    original_steps = db.query(RunStepTable).filter(
        RunStepTable.run_id == run_uuid
    ).order_by(RunStepTable.step_number).all()

    if from_step >= len(original_steps):
        raise HTTPException(status_code=400, detail=f"Invalid from_step: {from_step}, run has {len(original_steps)} steps")

    # Get workflow spec from stored definition
    flow = original_run.flow
    workflow_spec = flow.definition.get("workflow_spec")
    policies = flow.definition.get("policies", {})

    if not workflow_spec:
        raise HTTPException(status_code=500, detail="Flow missing workflow_spec")

    # Reconstruct state up to from_step
    replayed_state = {**original_run.current_state}
    completed_step_names = []

    for step in original_steps[:from_step]:
        if step.output_data:
            replayed_state[f"{step.step_name}_result"] = step.output_data
        completed_step_names.append(step.step_name)

    # Create new run for replay
    new_run = RunTable(
        flow_id=flow.flow_id,
        status=ProcessStatusEnum.RUNNING,
        current_state=replayed_state,
        created_by=f"replay_from_run_{run_id}_step_{from_step}"
    )
    db.add(new_run)
    db.commit()
    db.refresh(new_run)

    # Execute workflow from the replay point
    final_status, final_state = await run_agentic_loop(
        run_id=new_run.run_id,
        workflow_spec=workflow_spec,
        current_data=replayed_state,
        budget=policies.get("budget", {}),
        db=db
    )

    new_run.status = ProcessStatusEnum(final_status)
    new_run.current_state = final_state
    if final_status == "completed":
        new_run.completed_at = datetime.now(UTC)
    db.commit()

    return {
        "original_run_id": run_id,
        "new_run_id": str(new_run.run_id),
        "replayed_from_step": from_step,
        "status": new_run.status.value,
        "state": new_run.current_state
    }


@app.post("/flows/register", response_model=RegisterFlowResponse)
def register_flow(req: RegisterFlowRequest, db: Session = Depends(get_db)):
    """Register YAML DSL workflow."""
    try:
        compiled = compile_dsl(req.yaml)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid YAML: {e}")

    # Check if flow already exists
    existing_flow = db.query(FlowTable).filter(FlowTable.name == compiled.flow_name).first()
    if existing_flow:
        # Update existing flow
        existing_flow.description = compiled.flow_description
        existing_flow.definition = {
            "dsl": compiled.raw_dsl,
            "workflow_spec": compiled.workflow_spec,
            "form_schema": compiled.form_schema,
            "policies": compiled.policies,
            "triggers": compiled.triggers,
            "credentials": compiled.credentials
        }
        existing_flow.updated_at = datetime.now(UTC)
        db.commit()
        db.refresh(existing_flow)

        return RegisterFlowResponse(
            flow_id=str(existing_flow.flow_id),
            name=compiled.flow_name,
            form_schema=compiled.form_schema,
            workflow_summary={
                "steps_count": len(compiled.workflow_spec["steps"]),
                "ai_steps": sum(1 for s in compiled.workflow_spec["steps"] if s.get("type", "").startswith("ai.")),
                "credentials_required": compiled.credentials if isinstance(compiled.credentials, list) else []
            }
        )

    # Create new flow
    flow = FlowTable(
        name=compiled.flow_name,
        description=compiled.flow_description,
        definition={
            "dsl": compiled.raw_dsl,
            "workflow_spec": compiled.workflow_spec,
            "form_schema": compiled.form_schema,
            "policies": compiled.policies,
            "triggers": compiled.triggers,
            "credentials": compiled.credentials
        }
    )
    db.add(flow)
    db.commit()
    db.refresh(flow)

    return RegisterFlowResponse(
        flow_id=str(flow.flow_id),
        name=compiled.flow_name,
        form_schema=compiled.form_schema,
        workflow_summary={
            "steps_count": len(compiled.workflow_spec["steps"]),
            "ai_steps": sum(1 for s in compiled.workflow_spec["steps"] if s.get("type", "").startswith("ai.")),
            "credentials_required": compiled.credentials if isinstance(compiled.credentials, list) else []
        }
    )


@app.get("/flows/{flow_id}/graph")
def get_flow_graph(flow_id: str, db: Session = Depends(get_db)):
    """Get workflow graph visualization data."""
    flow_uuid = UUID(flow_id)
    flow = db.query(FlowTable).filter(FlowTable.flow_id == flow_uuid).first()
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    workflow_spec = flow.definition.get("workflow_spec", {})
    return build_flow_graph(workflow_spec)


@app.get("/runs/{run_id}/graph")
def get_run_graph(run_id: str, db: Session = Depends(get_db)):
    """Get run graph with status overlay."""
    run_uuid = UUID(run_id)
    run = db.query(RunTable).filter(RunTable.run_id == run_uuid).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    # Get base flow graph
    flow_graph = get_flow_graph(str(run.flow_id), db)

    # Build status map from run steps
    workflow_spec = run.flow.definition.get("workflow_spec", {})
    status_map = build_run_status_map(run.steps, workflow_spec)

    return {
        "nodes": flow_graph["nodes"],
        "edges": flow_graph["edges"],
        "status": status_map
    }


@app.get("/")
def root():
    return {"message": "Saz Agentic Workflow API", "version": "0.0.1"}
