/**
 * Format utilities for displaying events and run data
 */

/**
 * Format duration in milliseconds to human-readable string
 */
export function formatDuration(ms: number | null | undefined): string {
  if (!ms) return '-';

  const seconds = Math.floor(ms / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);

  if (hours > 0) return `${hours}h ${minutes % 60}m`;
  if (minutes > 0) return `${minutes}m ${seconds % 60}s`;
  if (seconds > 0) return `${seconds}s`;
  return `${ms}ms`;
}

/**
 * Format timestamp as relative time (e.g., "+2.3s", "+1m 15s")
 */
export function formatRelativeTime(timestamp: string, baseTimestamp?: string): string {
  const eventTime = new Date(timestamp).getTime();
  const baseTime = baseTimestamp ? new Date(baseTimestamp).getTime() : Date.now();
  const diffMs = eventTime - baseTime;

  if (diffMs < 0) {
    return formatDuration(Math.abs(diffMs));
  }

  return `+${formatDuration(diffMs)}`;
}

/**
 * Format absolute timestamp
 */
export function formatTimestamp(timestamp: string): string {
  const date = new Date(timestamp);
  return date.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    fractionalSecondDigits: 3,
  });
}

/**
 * Format cost in USD
 */
export function formatCost(usd: number): string {
  if (usd === 0) return '$0.00';
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(2)}`;
}

/**
 * Format token count with thousands separator
 */
export function formatTokens(tokens: number): string {
  return tokens.toLocaleString();
}
