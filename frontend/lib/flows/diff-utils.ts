/**
 * Line-based diff utilities for YAML change tracking
 */

export type LineChangeType = 'added' | 'modified' | 'unchanged';

export interface LineDiff {
  lineNumber: number; // 1-indexed (Monaco line numbers)
  changeType: LineChangeType;
}

/**
 * Compute line-by-line diff between baseline and current YAML
 * Returns array of LineDiff for all lines in current YAML
 */
export function computeLineDiff(baselineYaml: string, currentYaml: string): LineDiff[] {
  const baselineLines = baselineYaml.split('\n');
  const currentLines = currentYaml.split('\n');

  const diffs: LineDiff[] = [];

  // Simple line-by-line comparison
  // This is not a perfect LCS diff, but works well for incremental edits
  const maxLines = Math.max(baselineLines.length, currentLines.length);

  for (let i = 0; i < currentLines.length; i++) {
    const currentLine = currentLines[i];
    const baselineLine = i < baselineLines.length ? baselineLines[i] : undefined;

    let changeType: LineChangeType;

    if (baselineLine === undefined) {
      // Line added (current has more lines than baseline)
      changeType = 'added';
    } else if (currentLine !== baselineLine) {
      // Line modified
      changeType = 'modified';
    } else {
      // Line unchanged
      changeType = 'unchanged';
    }

    diffs.push({
      lineNumber: i + 1, // Monaco uses 1-indexed line numbers
      changeType,
    });
  }

  return diffs;
}

/**
 * Format time ago string for baseline timestamp
 */
export function formatTimeAgo(date: Date | null): string {
  if (!date) return 'never';

  const seconds = Math.floor((Date.now() - date.getTime()) / 1000);

  if (seconds < 5) return 'just now';
  if (seconds < 60) return `${seconds}s ago`;

  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;

  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;

  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}
