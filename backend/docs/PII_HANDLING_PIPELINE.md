# Privacy-by-Default PII Handling Pipeline

## Overview

The PII handling pipeline implements **privacy-by-default** across the workflow engine, ensuring that:

1. **Model/LLM tools never receive raw PII** - inputs are automatically tokenized
2. **Outbound integrations receive real PII only on explicitly approved paths** - selective detokenization
3. **Policy enforcement blocks PII on non-approved paths** - fail-fast with clear error messages
4. **All operations are auditable** - comprehensive logging and compliance reporting
5. **Run-scoped token vaults** - ephemeral, deterministic tokenization per workflow run

## Architecture

### Components

#### 1. PIITokenVault (`saz/policies/pii_token_vault.py`)

**Purpose**: Run-scoped, in-memory vault for deterministic tokenization/detokenization.

**Key Features**:
- Deterministic tokens: Same PII value → same token within a run
- Bidirectional mapping: Tokens ↔ PII values
- Safe for logs: Tokens are clearly identifiable (e.g., `__PII_EMAIL_1__`)
- Automatic cleanup: Vault cleared when run completes
- Selective detokenization: Path-based allow-lists

**Methods**:
- `tokenize(pii_type, pii_value)` - Generate deterministic token
- `detokenize(token)` - Restore original PII value
- `tokenize_dict(data, pii_detector)` - Recursively tokenize dictionary
- `detokenize_dict(data, allowed_paths)` - Selectively detokenize based on paths
- `scan_for_tokens(data)` - Find all paths containing tokens
- `clear()` - Clear all mappings

#### 2. PolicyEngine Enhancements (`saz/policies/policy_engine.py`)

**New Configuration**:
```python
PolicyEngine(
    tokenize_model_inputs=True,  # Tokenize inputs for model tools
    pii_allow_lists={            # Per-tool path allow-lists
        "http_request": ["headers.Authorization"],
        "email_send": ["to", "from", "subject", "body"],
    }
)
```

**New Methods**:
- `tokenize_arguments(tool_name, arguments, run_id)` - Tokenize for model tools
- `detokenize_arguments(tool_name, arguments, run_id)` - Detokenize for outbound tools
- `clear_token_vault(run_id)` - Clean up vault after run completion
- `get_token_vault_stats(run_id)` - Get tokenization statistics

**Tool Classification**:

**Model Tools** (receive tokenized inputs):
- `ai.assess`, `ai.generate`, `ai.plan`, `ai.extract`, `ai.route`, `ai.score`
- `ai.normalize`, `ai.match`, `ai.evaluate`, `ai.compare`
- `ai.translate`, `ai.summarize`, `ai.fix_json`, `ai.transform`

**Outbound Tools** (selective detokenization):
- `http_request`, `webhook_emit`, `ansible_run`

#### 3. Workflow Executor Integration (`saz/engine/executor.py`)

**Execution Flow**:

```
1. Policy check (detect raw PII in arguments)
   ↓
2. Tokenize arguments (for model tools)
   ↓
3. Detokenize arguments (for outbound tools, selective)
   ↓
4. Execute tool
   ↓
5. Redact PII from output
   ↓
6. Critique result
   ↓
7. Clear token vault (on run completion)
```

**Integration Points**:

**executor.py:600-613**:
```python
# Tokenize arguments for model tools
tool_call.arguments = self.policy_engine.tokenize_arguments(
    tool_name=tool_call.tool,
    arguments=tool_call.arguments,
    run_id=run_id,
)

# Detokenize arguments for outbound tools (selective)
tool_call.arguments = self.policy_engine.detokenize_arguments(
    tool_name=tool_call.tool,
    arguments=tool_call.arguments,
    run_id=run_id,
)
```

**executor.py:825, 846**:
```python
# Clear token vault for completed/failed runs
self.policy_engine.clear_token_vault(run_id)
```

## DSL Configuration

### Schema (`saz/compiler/dsl.py`)

```yaml
policies:
  pii:
    # If true, PII is allowed (less restrictive)
    # If false, PII is blocked by default
    allow: false

    # If true, PII is tokenized before model tool invocations
    tokenize_model_inputs: true

    # Exceptions to PII blocking rules
    exceptions:
      tools:
        # Per-tool allow-lists
        http_request:
          allow:
            - headers.Authorization
            - headers.X-API-Key

        email_send:
          # Shorthand: array of paths
          - to
          - from
          - subject
          - body
```

### Default Allow-Lists

```python
default_allow_lists = {
    "email_send": ["to", "from", "subject", "body"],
    "http_request": ["headers.Authorization"],
}
```

User-provided exceptions override defaults.

## Behavioral Examples

### Example 1: Model Tool with PII (Tokenized)

**Input**:
```python
# Step: ai.extract
arguments = {
    "instruction": "Extract email from text",
    "data": {
        "text": "Contact alice@example.com for help"
    }
}
```

**Tokenized Arguments Sent to Model**:
```python
{
    "instruction": "Extract email from text",
    "data": {
        "text": "Contact __PII_EMAIL_1__ for help"
    }
}
```

**Result**: Model never sees `alice@example.com` ✅

### Example 2: Outbound Tool with Approved Path (Detokenized)

**Configuration**:
```yaml
pii:
  exceptions:
    tools:
      http_request:
        allow:
          - headers.Authorization
```

**Input**:
```python
# Step: http_request
arguments = {
    "url": "https://api.example.com",
    "headers": {
        "Authorization": "Bearer __PII_API_KEY_1__"
    }
}
```

**Detokenized Arguments Sent to API**:
```python
{
    "url": "https://api.example.com",
    "headers": {
        "Authorization": "Bearer sk_test_secret123"
    }
}
```

**Result**: Real API key restored on approved path ✅

### Example 3: Outbound Tool with Disallowed Path (Blocked)

**Configuration**:
```yaml
pii:
  exceptions:
    tools:
      http_request:
        allow:
          - headers.Authorization  # Only header allowed
```

**Input**:
```python
# Step: http_request
arguments = {
    "url": "https://api.example.com",
    "body": {
        "api_key": "__PII_API_KEY_1__"  # Not allowed!
    }
}
```

**Result**: 🚫 **PolicyViolation** raised:
```
PII detected on non-approved paths for http_request: ['body.api_key'].
Approved paths: ['headers.Authorization']
```

Run fails with clear error indicating which paths violated policy.

## Audit & Observability

### Log Events

**Tokenization**:
```json
{
  "event": "pii_tokenized_for_model",
  "run_id": "run-123",
  "tool": "ai.extract",
  "tokenized_paths": ["data.email", "data.text"],
  "token_count": 2
}
```

**Detokenization**:
```json
{
  "event": "pii_detokenized_for_outbound",
  "run_id": "run-123",
  "tool": "http_request",
  "detokenized_paths": ["headers.Authorization"]
}
```

**Policy Violations**:
```json
{
  "event": "pii_detected_on_disallowed_paths",
  "run_id": "run-123",
  "tool": "http_request",
  "disallowed_paths": ["body.api_key"],
  "allowed_paths": ["headers.Authorization"]
}
```

### Compliance Report

```python
report = policy_engine.get_compliance_report(run_id)
```

**Output**:
```json
{
  "run_id": "run-123",
  "budget": { "tokens": {...}, "cost": {...} },
  "rate_limits": {...},
  "pii_tokenization": {
    "run_id": "run-123",
    "total_tokens": 5,
    "unique_values": 4,
    "tokens_by_type": {
      "email": 2,
      "phone": 1,
      "api_key": 2
    }
  },
  "policies_enforced": {
    "rate_limiting": true,
    "pii_detection": true,
    "pii_redaction": true,
    "pii_tokenization": true,
    "budget_tracking": true
  }
}
```

## Testing

### Unit Tests

**Token Vault** (`tests/unit/test_pii_token_vault.py`):
- 31 tests covering tokenization, detokenization, path matching, vault management

**PolicyEngine** (`tests/unit/test_policy_engine_pii.py`):
- 21 tests covering model tools, outbound tools, policy checks, DSL configuration

**Run Tests**:
```bash
pytest tests/unit/test_pii_token_vault.py -v
pytest tests/unit/test_policy_engine_pii.py -v
```

### Example Workflow

**Demo**: `examples/pii_handling_demo.yaml`

Demonstrates:
1. Model tools receiving tokenized inputs
2. Outbound tools with approved paths
3. Policy enforcement blocking disallowed paths
4. End-to-end PII handling

## Security Considerations

### Token Format

Tokens use the format: `__PII_<TYPE>_<COUNTER>__`

**Example**: `__PII_EMAIL_1__`, `__PII_API_KEY_2__`

**Properties**:
- Clearly identifiable as tokens (not confused with real data)
- Include PII type for debugging
- Deterministic counter per type
- Safe for logging and artifacts

### Vault Lifecycle

1. **Created**: On first tokenization for a run
2. **Used**: Throughout run execution
3. **Cleared**: Immediately after run completes or fails
4. **Ephemeral**: No persistence, in-memory only

### Path Matching

**Exact Match**:
```python
allowed_paths = {"to", "from"}
"to"    → ✅ allowed
"from"  → ✅ allowed
"body"  → ❌ disallowed
```

**Nested Match**:
```python
allowed_paths = {"headers.Authorization"}
"headers.Authorization"      → ✅ allowed
"headers.Content-Type"       → ❌ disallowed
"body.headers.Authorization" → ❌ disallowed (wrong level)
```

**Array Index Handling**:
```python
allowed_paths = {"recipients"}
"recipients[0]" → ✅ allowed (index stripped)
"recipients[1]" → ✅ allowed (index stripped)
```

## Migration Guide

### Existing Workflows

**Before** (no tokenization):
```yaml
policies:
  pii:
    allow: false  # Block all PII
```

**After** (with tokenization):
```yaml
policies:
  pii:
    allow: false
    tokenize_model_inputs: true  # NEW
    exceptions:                   # NEW
      tools:
        email_send: [to, from, subject]
        http_request:
          allow: [headers.Authorization]
```

### Backward Compatibility

**Default Behavior** (if not specified):
- `tokenize_model_inputs`: `true` (enabled by default)
- `pii_allow_lists`: Default allow-lists applied (email_send, http_request)

**Legacy Mode** (disable tokenization):
```yaml
policies:
  pii:
    tokenize_model_inputs: false
```

## Performance Considerations

### Tokenization Overhead

- **Detection**: Regex-based pattern matching (~1ms per KB)
- **Tokenization**: Dict traversal + string replacement (~0.5ms per KB)
- **Vault Lookup**: O(1) hash map lookups (< 0.1ms)

### Memory Usage

- **Per Token**: ~200 bytes (bidirectional mapping)
- **Typical Run**: 10-50 tokens (~2-10 KB)
- **Large Run**: 500 tokens (~100 KB)

**Recommendation**: Token vaults are lightweight and cleared after each run.

### Concurrency

- **Thread-Safe**: Each run gets its own vault (no shared state)
- **Parallel Steps**: Safe for concurrent step execution
- **Idempotent**: Retries produce same tokens (deterministic)

## Troubleshooting

### Issue: PII Not Detected

**Symptom**: Expected PII is not tokenized.

**Causes**:
1. **Value too short**: Generic API keys require 32+ characters
2. **Format mismatch**: Pattern doesn't match PII type
3. **Private IPs**: Not detected by default (`redact_private_ips=False`)

**Solution**:
```python
# Check detection explicitly
findings = pii_detector.detect("test@example.com")
print(findings)  # Should show [{"type": "email", "value": "...", ...}]
```

### Issue: PolicyViolation on Approved Path

**Symptom**: Detokenization blocked despite path being approved.

**Causes**:
1. **Path format mismatch**: Use dots for nesting (`headers.Authorization` not `headers/Authorization`)
2. **Array indices**: Path includes `[0]` but should be stripped
3. **Typo in allow-list**: Check DSL configuration

**Solution**:
```python
# Check path matching
vault = policy_engine._get_token_vault(run_id)
paths = vault.scan_for_tokens(arguments)
print(f"Token paths: {paths}")
print(f"Allowed paths: {policy_engine.pii_allow_lists}")
```

### Issue: Token Vault Not Cleared

**Symptom**: Memory usage grows over many runs.

**Causes**:
1. **Run not completing**: Vault only cleared on completion/failure
2. **Exception in cleanup**: Check logs for errors

**Solution**:
```python
# Manually clear if needed
policy_engine.clear_token_vault(run_id)
```

## Future Enhancements

### Potential Improvements

1. **Custom Token Format**: Allow configurable token patterns
2. **Token Expiration**: Time-based vault expiration for long-running workflows
3. **Partial Detokenization**: Masked detokenization (e.g., `a***@example.com`)
4. **Cross-Run Consistency**: Optional persistent vault for multi-run workflows
5. **PII Provenance**: Track where PII originated (form field, step output)
6. **Regex-Based Allow-Lists**: Support wildcards in path matching (e.g., `headers.*`)

## References

- **Token Vault**: `saz/policies/pii_token_vault.py`
- **Policy Engine**: `saz/policies/policy_engine.py`
- **PII Detector**: `saz/policies/pii_detector.py`
- **Workflow Executor**: `saz/engine/executor.py`
- **DSL Compiler**: `saz/compiler/dsl.py`
- **Tests**: `tests/unit/test_pii_token_vault.py`, `tests/unit/test_policy_engine_pii.py`
- **Example**: `examples/pii_handling_demo.yaml`
