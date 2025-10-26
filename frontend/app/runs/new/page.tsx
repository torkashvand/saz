'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useCreateRun } from '@/lib/hooks'
import { useToast } from '@/components/ui/use-toast'
import type { RegisterFormsResponse } from '@/lib/types'

export default function NewRunPage() {
  const router = useRouter()
  const { toast } = useToast()
  const createRunMutation = useCreateRun()

  const [registeredFlow, setRegisteredFlow] = useState<RegisterFormsResponse | null>(null)
  const [formData, setFormData] = useState<Record<string, any>>({})

  useEffect(() => {
    const savedFlow = localStorage.getItem('last_registered_flow')
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
        description: `Run ID: ${result.run_id}`,
      })

      router.push(`/runs/${result.run_id}`)
    } catch (error: any) {
      toast({
        title: 'Failed',
        description: error.message,
        variant: 'destructive',
      })
    }
  }

  if (!registeredFlow) {
    return (
      <div className="container mx-auto px-4 py-12">
        <Card className="max-w-lg mx-auto">
          <CardHeader>
            <CardTitle>No Form Registered</CardTitle>
            <CardDescription>Register a form first</CardDescription>
          </CardHeader>
          <CardContent>
            <Button onClick={() => router.push('/register')} className="w-full">
              Go to Register
            </Button>
          </CardContent>
        </Card>
      </div>
    )
  }

  const properties = registeredFlow.json_schema.properties || {}
  const required = registeredFlow.json_schema.required || []

  return (
    <div className="container mx-auto px-4 py-8">
      <div className="max-w-2xl mx-auto">
        <h1 className="text-3xl font-bold mb-6">Create New Run</h1>

        <Card>
          <CardHeader>
            <CardTitle>{registeredFlow.name}</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-4">
              {Object.entries(properties).map(([name, prop]: [string, any]) => (
                <div key={name}>
                  <Label htmlFor={name}>
                    {name}
                    {required.includes(name) && <span className="text-red-500">*</span>}
                  </Label>
                  <Input
                    id={name}
                    type={prop.type === 'number' ? 'number' : 'text'}
                    value={formData[name] || ''}
                    onChange={(e) => setFormData({...formData, [name]: e.target.value})}
                    required={required.includes(name)}
                  />
                </div>
              ))}
              <Button type="submit" disabled={createRunMutation.isPending} className="w-full">
                {createRunMutation.isPending ? 'Creating...' : 'Create Run'}
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
