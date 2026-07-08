import { describe, it, expect } from 'vitest';
import { toFriendlyError } from '@/lib/flows/friendly-validation';
import type { ValidationError } from '@/lib/flows/types';
import type { WorkflowStepDraft } from '@/lib/flows/types';

const approvalStep: WorkflowStepDraft = { id: 'review', type: 'human.approval' };
const documentStep: WorkflowStepDraft = {
  id: 'render_draft',
  type: 'tool.call',
  tool: 'docx_render',
};

describe('toFriendlyError', () => {
  it('translates a missing approval setting into a reviewer prompt', () => {
    const err: ValidationError = {
      code: 'step.missing_field',
      message: "step 'review' missing required field: params",
      step_id: 'review',
    };
    expect(toFriendlyError(err, approvalStep).message).toMatch(/who should review/i);
  });

  it('translates a missing docx param into a document-settings message', () => {
    const err: ValidationError = {
      code: 'step.empty_field',
      message: "step 'render_draft' has empty field: params",
      step_id: 'render_draft',
    };
    expect(toFriendlyError(err, documentStep).message).toMatch(/document settings/i);
  });

  it('translates a missing form field reference into a plain-language message', () => {
    const err: ValidationError = {
      code: 'expression.unknown_form_field',
      message: 'unknown form field reference',
    };
    expect(toFriendlyError(err).message).toMatch(/no longer exists/i);
  });

  it('translates a JSON parse error in advanced mode', () => {
    const err: ValidationError = { code: 'json.invalid', message: 'Unexpected token } in JSON' };
    expect(toFriendlyError(err).message).toMatch(/invalid JSON/i);
  });

  it('translates a webhook.wait missing event into a wait prompt', () => {
    const err: ValidationError = {
      code: 'step.webhook_wait_missing_event',
      message: "webhook.wait step 'wait' missing params.event_name",
      step_id: 'wait',
    };
    expect(toFriendlyError(err).message).toMatch(/wait for/i);
  });

  it('keeps the original technical message available', () => {
    const err: ValidationError = { code: 'json.invalid', message: 'Unexpected token } in JSON' };
    expect(toFriendlyError(err).technical).toBe('Unexpected token } in JSON');
  });

  it('falls back to the original message for unknown codes', () => {
    const err: ValidationError = { code: 'something.weird', message: 'raw backend message' };
    expect(toFriendlyError(err).message).toBe('raw backend message');
  });
});
