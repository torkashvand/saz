'use client';

import { useState } from 'react';
import { AlertCircle, ChevronDown, ChevronRight, Settings, FileText, RefreshCw, Key, ExternalLink, Eye } from 'lucide-react';
import { Button } from './ui/button';
import { Card, CardContent } from './ui/card';
import { CollapsibleJson } from './json-view';
import type { ErrorSummary, ErrorCategory, RemediationAction } from '@/lib/types-enhanced';

interface ErrorSummaryProps {
  error: ErrorSummary;
  onAction?: (action: RemediationAction) => void;
}

/**
 * Get icon and styling for error category.
 */
function getErrorCategoryConfig(category: ErrorCategory) {
  switch (category) {
    case 'missing_credential':
      return {
        icon: Key,
        color: 'text-amber-600',
        bgColor: 'bg-amber-50',
        borderColor: 'border-amber-200',
      };
    case 'http_error':
    case 'timeout':
    case 'rate_limit':
      return {
        icon: ExternalLink,
        color: 'text-orange-600',
        bgColor: 'bg-orange-50',
        borderColor: 'border-orange-200',
      };
    case 'validation_error':
    case 'user_error':
      return {
        icon: AlertCircle,
        color: 'text-blue-600',
        bgColor: 'bg-blue-50',
        borderColor: 'border-blue-200',
      };
    case 'permission_denied':
      return {
        icon: AlertCircle,
        color: 'text-red-600',
        bgColor: 'bg-red-50',
        borderColor: 'border-red-200',
      };
    case 'internal_error':
    case 'unknown':
    default:
      return {
        icon: AlertCircle,
        color: 'text-red-600',
        bgColor: 'bg-red-50',
        borderColor: 'border-red-200',
      };
  }
}

/**
 * Get human-readable label and button config for remediation action.
 */
function getRemediationConfig(action: RemediationAction) {
  switch (action) {
    case 'configure_credential':
      return {
        label: 'Configure Credential',
        icon: Key,
        variant: 'default' as const,
      };
    case 'check_api_status':
      return {
        label: 'Check API Status',
        icon: ExternalLink,
        variant: 'outline' as const,
      };
    case 'fix_input_data':
      return {
        label: 'Review Flow Input',
        icon: FileText,
        variant: 'outline' as const,
      };
    case 'retry':
      return {
        label: 'Retry from Failing Step',
        icon: RefreshCw,
        variant: 'default' as const,
      };
    case 'contact_support':
      return {
        label: 'Contact Support',
        icon: ExternalLink,
        variant: 'outline' as const,
      };
    case 'check_permissions':
      return {
        label: 'Check Permissions',
        icon: Settings,
        variant: 'outline' as const,
      };
    case 'view_logs':
      return {
        label: 'View Logs',
        icon: Eye,
        variant: 'outline' as const,
      };
  }
}

/**
 * Display human-readable error summary with clear next actions.
 *
 * Design principles:
 * - No stack traces or internal details by default
 * - Clear, actionable error message
 * - Prominent remediation buttons
 * - Collapsible technical details for engineers
 */
export function ErrorSummaryBanner({ error, onAction }: ErrorSummaryProps) {
  const [showTechnicalDetails, setShowTechnicalDetails] = useState(false);
  const config = getErrorCategoryConfig(error.category);
  const Icon = config.icon;

  return (
    <Card className={`border-2 ${config.borderColor} ${config.bgColor}`}>
      <CardContent className="pt-6">
        {/* Main error message */}
        <div className="flex items-start gap-3 mb-4">
          <Icon className={`h-6 w-6 ${config.color} flex-shrink-0 mt-0.5`} />
          <div className="flex-1">
            <h3 className="text-lg font-semibold text-slate-900 mb-1">
              Run Failed
            </h3>
            <p className="text-slate-700 text-base leading-relaxed">
              {error.message}
            </p>
            {error.failed_step_number && (
              <p className="text-sm text-slate-600 mt-2">
                Failed at <span className="font-semibold">Step {error.failed_step_number}: {error.failed_step_name}</span>
              </p>
            )}
          </div>
        </div>

        {/* Remediation actions */}
        {error.remediation_actions.length > 0 && (
          <div className="mb-4">
            <p className="text-sm font-medium text-slate-700 mb-2">Suggested actions:</p>
            <div className="flex flex-wrap gap-2">
              {error.remediation_actions.map((action) => {
                const actionConfig = getRemediationConfig(action);
                const ActionIcon = actionConfig.icon;
                return (
                  <Button
                    key={action}
                    variant={actionConfig.variant}
                    size="sm"
                    onClick={() => onAction?.(action)}
                    className="gap-2"
                  >
                    <ActionIcon className="h-4 w-4" />
                    {actionConfig.label}
                  </Button>
                );
              })}
            </div>
          </div>
        )}

        {/* Collapsible technical details */}
        <div className="border-t border-slate-200 pt-4">
          <button
            onClick={() => setShowTechnicalDetails(!showTechnicalDetails)}
            className="flex items-center gap-2 text-sm font-medium text-slate-600 hover:text-slate-900 transition-colors"
          >
            {showTechnicalDetails ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronRight className="h-4 w-4" />
            )}
            Technical details (for engineers)
          </button>

          {showTechnicalDetails && (
            <div className="mt-3 space-y-3 text-sm">
              {/* Note: Stack traces are NOT included by default for security */}
              <div className="bg-blue-50 border border-blue-200 rounded p-3 mb-3">
                <p className="text-xs text-blue-800">
                  <strong>Note:</strong> Stack traces are not included in API responses by default for security.
                  Only error type and basic information are shown here.
                </p>
              </div>

              {error.technical_details.error_type && (
                <div>
                  <p className="font-medium text-slate-700">Error Type:</p>
                  <p className="font-mono text-xs text-slate-600 mt-1">
                    {error.technical_details.error_type}
                  </p>
                </div>
              )}

              {error.technical_details.http_status && (
                <div>
                  <p className="font-medium text-slate-700">HTTP Status:</p>
                  <p className="font-mono text-xs text-slate-600 mt-1">
                    {error.technical_details.http_status}
                  </p>
                </div>
              )}

              {error.technical_details.api_endpoint && (
                <div>
                  <p className="font-medium text-slate-700">API Endpoint:</p>
                  <p className="font-mono text-xs text-slate-600 mt-1 break-all">
                    {error.technical_details.api_endpoint}
                  </p>
                </div>
              )}

              {/* Stack traces are deliberately NOT displayed even if present */}
              {/* This is a security measure to prevent leaking internal details */}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
