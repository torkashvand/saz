'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useCreateRun } from '@/lib/hooks'
import { useToast } from '@/components/ui/use-toast'
import type { RegisterFlowResponse } from '@/lib/types'

export default function NewRunPage() {
  const router = useRouter()
  const { toast } = useToast()
  const createRunMutation = useCreateRun()

  const [registeredFlow, setRegisteredFlow] = useState<RegisterFlowResponse | null>(null)
  const [formData, setFormData] = useState<Record<string, any>>({})

  useEffect(() => {
    const savedFlow = localStorage.getItem('last_registered_flow_v2')
    if (savedFlow) {
      try {
        setRegisteredFlow(JSON.parse(savedFlow))
      } catch {}
    }
  }, [])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!registeredFlow) return

    try {
      const result = await createRunMutation.mutateAsync({
        flow_id: registeredFlow.flow_id,
        payload: formData,
      })

      toast({
        title: 'Run Created',
        description: `Run ${result.run_id} created successfully`,
      })

      router.push(`/runs/${result.run_id}`)
    } catch (error: any) {
      toast({
        title: 'Failed to Create Run',
        description: error.message || 'An error occurred',
        variant: 'destructive',
      })
    }
  }

  if (!registeredFlow) {
    return (
      <div className="container mx-auto px-4 py-12">
        <Card className="max-w-lg mx-auto">
          <CardHeader>
            <CardTitle>No Workflow Registered</CardTitle>
            <CardDescription>You need to register a workflow before creating a run</CardDescription>
          </CardHeader>
          <CardContent>
            <Button onClick={() => router.push('/register')} className="w-full">
              Go to Register Workflow
            </Button>
          </CardContent>
        </Card>
      </div>
    )
  }

  const properties = registeredFlow.form_schema.properties || {}
  const required = registeredFlow.form_schema.required || []

  return (
    <div className="container mx-auto px-4 py-8">
      <div className="max-w-2xl mx-auto">
        <div className="mb-6">
          <h1 className="text-3xl font-bold">Create New Run</h1>
          <p className="text-muted-foreground mt-1">
            Fill in the form to execute the workflow
          </p>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Workflow Input</CardTitle>
            <CardDescription>
              {registeredFlow.workflow_summary.steps_count} steps • {registeredFlow.workflow_summary.ai_steps} AI operations
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-4">
              {Object.entries(properties).map(([name, prop]: [string, any]) => {
                const isRequired = required.includes(name)
                const fieldType = prop.type === 'number' || prop.type === 'integer' ? 'number' : 'text'

                return (
                  <div key={name} className="space-y-2">
                    <Label htmlFor={name}>
                      {prop.title || name}
                      {isRequired && <span className="text-red-500 ml-1">*</span>}
                    </Label>
                    {prop.description && (
                      <p className="text-xs text-muted-foreground">{prop.description}</p>
                    )}
                    <Input
                      id={name}
                      type={fieldType}
                      value={formData[name] || ''}
                      onChange={(e) => {
                        const value = fieldType === 'number' ? parseFloat(e.target.value) : e.target.value
                        setFormData({...formData, [name]: value})
                      }}
                      required={isRequired}
                      min={prop.minimum}
                      max={prop.maximum}
                      placeholder={prop.example || prop.description}
                    />
                  </div>
                )
              })}

              <div className="pt-4">
                <Button type="submit" disabled={createRunMutation.isPending} className="w-full">
                  {createRunMutation.isPending ? 'Creating Run...' : 'Create Run'}
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>

        {registeredFlow.workflow_summary.credentials &&
         registeredFlow.workflow_summary.credentials.length > 0 && (
          <Card className="mt-4 border-orange-200 bg-orange-50">
            <CardHeader>
              <CardTitle className="text-orange-900 text-sm">Credentials Required</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-orange-700 mb-2">
                This workflow requires the following credentials to be configured:
              </p>
              <div className="flex flex-wrap gap-1">
                {registeredFlow.workflow_summary.credentials.map((cred) => (
                  <span key={cred} className="text-xs bg-orange-100 text-orange-700 px-2 py-1 rounded font-mono">
                    {cred}
                  </span>
                ))}
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  )
}
