import Link from 'next/link';
import { ArrowRight, Workflow, PlayCircle, Key } from 'lucide-react';

export default function HomePage() {
  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-50 to-slate-100">
      <div className="max-w-6xl mx-auto px-4 py-16">
        {/* Hero */}
        <div className="text-center mb-16">
          <h1 className="text-5xl font-bold text-slate-900 mb-4">
            Saz Agentic Workflow Engine
          </h1>
          <p className="text-xl text-slate-600 max-w-3xl mx-auto mb-2">
            Internal platform for auditable, policy-driven agentic workflows.
          </p>
          <p className="text-lg text-slate-500 max-w-3xl mx-auto">
            Orchestrate multi-step flows with LLM-assisted decision-making, human approvals,
            and strong guardrails for PII, budgets, and compliance.
          </p>
        </div>

        {/* Action Cards */}
        <div className="grid md:grid-cols-3 gap-6 mb-12">
          <ActionCard
            icon={<Workflow className="w-8 h-8" />}
            title="Browse Flows"
            description="Explore workflow definitions with policies and execution graphs"
            href="/flows"
          />
          <ActionCard
            icon={<PlayCircle className="w-8 h-8" />}
            title="View Runs"
            description="Monitor live executions, review audit trails, and analyze costs"
            href="/runs"
          />
          <ActionCard
            icon={<Key className="w-8 h-8" />}
            title="Manage Credentials"
            description="Configure secure credentials for flow integrations"
            href="/credentials"
          />
        </div>

        {/* Phase Info */}
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-6 text-center">
          <p className="text-sm text-blue-900">
            <strong>Phase 1 Pilot:</strong> Human-in-the-loop workflows for incident triage,
            change approvals, and ticket classification. All runs are auditable and policy-enforced.
          </p>
        </div>
      </div>
    </div>
  );
}

function ActionCard({
  icon,
  title,
  description,
  href,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  href: string;
}) {
  return (
    <Link
      href={href}
      className="bg-white rounded-lg p-6 shadow-sm border border-slate-200 hover:shadow-md hover:border-slate-300 transition-all group"
    >
      <div className="text-blue-600 mb-3">{icon}</div>
      <h3 className="text-lg font-semibold text-slate-900 mb-2 group-hover:text-blue-600 transition-colors">
        {title}
      </h3>
      <p className="text-slate-600 text-sm mb-4">{description}</p>
      <div className="flex items-center text-blue-600 text-sm font-medium">
        Go <ArrowRight className="w-4 h-4 ml-1 group-hover:translate-x-1 transition-transform" />
      </div>
    </Link>
  );
}
