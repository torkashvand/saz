'use client';

import { useState, useMemo } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { DollarSign, Zap, TrendingUp, ArrowUpDown } from 'lucide-react';
import type { RunStep } from '@/lib/types';

interface CostMetricsViewProps {
  steps: RunStep[];
  totalTokens: number;
  totalCost: number;
  onSelectStep?: (stepNumber: number) => void;
}

type SortField = 'step' | 'tokens' | 'cost';
type SortOrder = 'asc' | 'desc';

export function CostMetricsView({ steps, totalTokens, totalCost, onSelectStep }: CostMetricsViewProps) {
  const [sortField, setSortField] = useState<SortField>('cost');
  const [sortOrder, setSortOrder] = useState<SortOrder>('desc');

  // Calculate derived metrics
  const stepsWithCost = steps.filter(s => s.cost_usd && s.cost_usd > 0);
  const avgTokensPerStep = stepsWithCost.length > 0
    ? Math.round(stepsWithCost.reduce((sum, s) => sum + (s.tokens || 0), 0) / stepsWithCost.length)
    : 0;
  const avgCostPerStep = stepsWithCost.length > 0
    ? stepsWithCost.reduce((sum, s) => sum + (s.cost_usd || 0), 0) / stepsWithCost.length
    : 0;

  const mostExpensiveStep = steps.reduce((max, step) =>
    (step.cost_usd || 0) > (max.cost_usd || 0) ? step : max
  , steps[0] || { cost_usd: 0 });

  // Sorted steps
  const sortedSteps = useMemo(() => {
    const sorted = [...stepsWithCost].sort((a, b) => {
      let aVal, bVal;
      if (sortField === 'step') {
        aVal = a.number;
        bVal = b.number;
      } else if (sortField === 'tokens') {
        aVal = a.tokens || 0;
        bVal = b.tokens || 0;
      } else {
        aVal = a.cost_usd || 0;
        bVal = b.cost_usd || 0;
      }

      return sortOrder === 'asc' ? aVal - bVal : bVal - aVal;
    });
    return sorted;
  }, [stepsWithCost, sortField, sortOrder]);

  const toggleSort = (field: SortField) => {
    if (sortField === field) {
      setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortOrder('desc');
    }
  };

  const formatCost = (cost: number) => `$${cost.toFixed(4)}`;

  return (
    <div className="space-y-6">
      {/* Summary cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card>
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium text-slate-500">
                Avg per AI Step
              </CardTitle>
              <Zap className="h-4 w-4 text-slate-400" />
            </div>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold text-slate-900">
              {avgTokensPerStep.toLocaleString()}
            </p>
            <p className="text-xs text-slate-500 mt-1">
              tokens • {formatCost(avgCostPerStep)}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium text-slate-500">
                Most Expensive Step
              </CardTitle>
              <TrendingUp className="h-4 w-4 text-slate-400" />
            </div>
          </CardHeader>
          <CardContent>
            <p className="text-base font-bold text-slate-900 truncate">
              Step {mostExpensiveStep.number + 1}: {mostExpensiveStep.name}
            </p>
            <p className="text-xs text-slate-500 mt-1">
              {formatCost(mostExpensiveStep.cost_usd || 0)} •{' '}
              {((mostExpensiveStep.cost_usd || 0) / totalCost * 100).toFixed(1)}% of total
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium text-slate-500">
                AI vs Non-AI Cost
              </CardTitle>
              <DollarSign className="h-4 w-4 text-slate-400" />
            </div>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold text-slate-900">
              {((stepsWithCost.reduce((sum, s) => sum + (s.cost_usd || 0), 0) / totalCost) * 100).toFixed(0)}%
            </p>
            <p className="text-xs text-slate-500 mt-1">
              {formatCost(stepsWithCost.reduce((sum, s) => sum + (s.cost_usd || 0), 0))} AI •{' '}
              {formatCost(totalCost - stepsWithCost.reduce((sum, s) => sum + (s.cost_usd || 0), 0))} other
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Sortable table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Cost Breakdown by Step</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200">
                  <th className="text-left py-3 px-4">
                    <button
                      onClick={() => toggleSort('step')}
                      className="flex items-center gap-1 hover:text-slate-900 transition-colors"
                    >
                      <span className="font-medium text-slate-700">Step</span>
                      {sortField === 'step' && <ArrowUpDown className="h-3.5 w-3.5" />}
                    </button>
                  </th>
                  <th className="text-left py-3 px-4 font-medium text-slate-700">Name</th>
                  <th className="text-right py-3 px-4">
                    <button
                      onClick={() => toggleSort('tokens')}
                      className="flex items-center gap-1 ml-auto hover:text-slate-900 transition-colors"
                    >
                      <span className="font-medium text-slate-700">Tokens</span>
                      {sortField === 'tokens' && <ArrowUpDown className="h-3.5 w-3.5" />}
                    </button>
                  </th>
                  <th className="text-right py-3 px-4">
                    <button
                      onClick={() => toggleSort('cost')}
                      className="flex items-center gap-1 ml-auto hover:text-slate-900 transition-colors"
                    >
                      <span className="font-medium text-slate-700">Cost (USD)</span>
                      {sortField === 'cost' && <ArrowUpDown className="h-3.5 w-3.5" />}
                    </button>
                  </th>
                  <th className="text-right py-3 px-4 font-medium text-slate-700">% of Total</th>
                  <th className="py-3 px-4"></th>
                </tr>
              </thead>
              <tbody>
                {sortedSteps.map((step) => {
                  const percentage = ((step.cost_usd || 0) / totalCost) * 100;
                  return (
                    <tr
                      key={step.id}
                      className="border-b border-slate-100 hover:bg-slate-50 transition-colors cursor-pointer"
                      onClick={() => onSelectStep && onSelectStep(step.number)}
                    >
                      <td className="py-3 px-4 font-medium text-slate-900">
                        {step.number + 1}
                      </td>
                      <td className="py-3 px-4 text-slate-700 truncate max-w-xs">
                        {step.name}
                      </td>
                      <td className="py-3 px-4 text-right text-slate-900 font-mono">
                        {(step.tokens || 0).toLocaleString()}
                      </td>
                      <td className="py-3 px-4 text-right text-slate-900 font-mono">
                        {formatCost(step.cost_usd || 0)}
                      </td>
                      <td className="py-3 px-4 text-right text-slate-700">
                        {percentage.toFixed(1)}%
                      </td>
                      <td className="py-3 px-4">
                        {/* Visual bar */}
                        <div className="w-20 h-2 bg-slate-100 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-blue-500 rounded-full transition-all"
                            style={{ width: `${Math.min(percentage, 100)}%` }}
                          />
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
              <tfoot>
                <tr className="border-t-2 border-slate-300 font-semibold">
                  <td className="py-3 px-4" colSpan={2}>Total</td>
                  <td className="py-3 px-4 text-right font-mono">{totalTokens.toLocaleString()}</td>
                  <td className="py-3 px-4 text-right font-mono">{formatCost(totalCost)}</td>
                  <td className="py-3 px-4 text-right">100%</td>
                  <td className="py-3 px-4"></td>
                </tr>
              </tfoot>
            </table>
          </div>

          {stepsWithCost.length === 0 && (
            <div className="text-center py-12 text-slate-500">
              <p className="text-sm">No AI operations with cost tracking</p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}