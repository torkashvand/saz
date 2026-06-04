'use client';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { TrendingUp, DollarSign, Zap } from 'lucide-react';
import type { RunStep } from '@/lib/types';

interface CostMetricsTabProps {
  steps: RunStep[];
  totalTokens: number;
  totalCost: number;
}

function formatCost(cost: number): string {
  return `$${cost.toFixed(4)}`;
}

/**
 * Cost breakdown tab showing per-step token usage and costs.
 *
 * Design principles:
 * - Show only derived, cost-specific insights (no duplication with global summary)
 * - Detailed breakdown table
 * - Visual representation of cost distribution
 */
export function CostMetricsTab({ steps, totalTokens, totalCost }: CostMetricsTabProps) {
  // Calculate averages
  const stepsWithTokens = steps.filter((s) => s.tokens && s.tokens > 0);
  const avgTokensPerStep =
    stepsWithTokens.length > 0
      ? Math.round(
          stepsWithTokens.reduce((sum, s) => sum + (s.tokens || 0), 0) / stepsWithTokens.length,
        )
      : 0;

  const stepsWithCost = steps.filter((s) => s.cost_usd && s.cost_usd > 0);
  const avgCostPerStep =
    stepsWithCost.length > 0
      ? stepsWithCost.reduce((sum, s) => sum + (s.cost_usd || 0), 0) / stepsWithCost.length
      : 0;

  // Find most expensive step
  const mostExpensiveStep = steps.reduce(
    (max, step) => ((step.cost_usd || 0) > (max.cost_usd || 0) ? step : max),
    steps[0] || { cost_usd: 0 },
  );

  // Calculate LLM vs non-LLM split (heuristic: steps with tokens are LLM)
  const llmSteps = steps.filter((s) => s.tokens && s.tokens > 0);
  const llmCost = llmSteps.reduce((sum, s) => sum + (s.cost_usd || 0), 0);
  const nonLlmCost = totalCost - llmCost;
  const llmPercentage = totalCost > 0 ? (llmCost / totalCost) * 100 : 0;

  return (
    <div className="space-y-6">
      {/* Derived insights - no duplication with global summary */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card>
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium text-slate-500">Avg per AI Step</CardTitle>
              <Zap className="h-4 w-4 text-slate-400" />
            </div>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold text-slate-900">{avgTokensPerStep.toLocaleString()}</p>
            <p className="text-xs text-slate-500 mt-1">tokens • {formatCost(avgCostPerStep)}</p>
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
              {(((mostExpensiveStep.cost_usd || 0) / totalCost) * 100).toFixed(1)}% of total
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
            <p className="text-2xl font-bold text-slate-900">{llmPercentage.toFixed(0)}%</p>
            <p className="text-xs text-slate-500 mt-1">
              {formatCost(llmCost)} AI • {formatCost(nonLlmCost)} other
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Detailed breakdown table */}
      <Card>
        <CardHeader>
          <CardTitle>Cost Breakdown by Step</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200">
                  <th className="text-left py-3 px-4 font-medium text-slate-700">Step</th>
                  <th className="text-left py-3 px-4 font-medium text-slate-700">Name</th>
                  <th className="text-right py-3 px-4 font-medium text-slate-700">Tokens</th>
                  <th className="text-right py-3 px-4 font-medium text-slate-700">Cost (USD)</th>
                  <th className="text-right py-3 px-4 font-medium text-slate-700">% of Total</th>
                </tr>
              </thead>
              <tbody>
                {steps.map((step) => {
                  const tokens = step.tokens || 0;
                  const cost = step.cost_usd || 0;
                  const percentage = totalCost > 0 ? (cost / totalCost) * 100 : 0;

                  return (
                    <tr key={step.id} className="border-b border-slate-100 hover:bg-slate-50">
                      <td className="py-3 px-4 text-slate-900 font-medium">{step.number}</td>
                      <td className="py-3 px-4 text-slate-900">{step.name}</td>
                      <td className="py-3 px-4 text-right text-slate-700">
                        {tokens > 0 ? tokens.toLocaleString() : '-'}
                      </td>
                      <td className="py-3 px-4 text-right text-slate-700 font-mono">
                        {cost > 0 ? formatCost(cost) : '-'}
                      </td>
                      <td className="py-3 px-4 text-right text-slate-500">
                        {percentage > 0 ? (
                          <div className="flex items-center justify-end gap-2">
                            <div className="w-16 bg-slate-200 rounded-full h-2">
                              <div
                                className="bg-blue-500 h-2 rounded-full"
                                style={{ width: `${Math.min(percentage, 100)}%` }}
                              />
                            </div>
                            <span className="text-xs">{percentage.toFixed(1)}%</span>
                          </div>
                        ) : (
                          '-'
                        )}
                      </td>
                    </tr>
                  );
                })}

                {/* Total row */}
                <tr className="bg-slate-50 font-semibold">
                  <td colSpan={2} className="py-3 px-4 text-slate-900">
                    Total
                  </td>
                  <td className="py-3 px-4 text-right text-slate-900">
                    {totalTokens.toLocaleString()}
                  </td>
                  <td className="py-3 px-4 text-right text-slate-900 font-mono">
                    {formatCost(totalCost)}
                  </td>
                  <td className="py-3 px-4 text-right text-slate-900">100%</td>
                </tr>
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
