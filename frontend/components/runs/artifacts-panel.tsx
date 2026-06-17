'use client';

import { useQuery } from '@tanstack/react-query';
import { Download, FileText } from 'lucide-react';
import { api } from '@/lib/api';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';

function formatBytes(n: number): string {
  if (!n) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(n) / Math.log(1024));
  return `${(n / Math.pow(1024, i)).toFixed(i ? 1 : 0)} ${units[i]}`;
}

export function ArtifactsPanel({ runId }: { runId: string }) {
  const { data } = useQuery({
    queryKey: ['artifacts', runId],
    queryFn: () => api.getRunArtifacts(runId),
  });
  const artifacts = data?.artifacts ?? [];
  if (artifacts.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Artifacts</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {artifacts.map((a) => (
          <div
            key={a.id}
            className="flex items-center justify-between rounded-md border border-slate-200 px-3 py-2"
          >
            <div className="flex items-center gap-2 min-w-0">
              <FileText className="h-4 w-4 text-slate-400 shrink-0" />
              <div className="min-w-0">
                <div className="text-sm font-medium truncate" title={a.filename}>
                  {a.filename}
                </div>
                <div className="text-xs text-slate-500">{formatBytes(a.size_bytes)}</div>
              </div>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => api.downloadArtifact(runId, a.id, a.filename)}
              data-testid={`download-${a.id}`}
            >
              <Download className="h-4 w-4 mr-1" />
              Download
            </Button>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
