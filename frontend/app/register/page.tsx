'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useRegisterForms } from '@/lib/hooks'
import { useToast } from '@/components/ui/use-toast'
import type { RegisterFormsResponse } from '@/lib/types'

const EXAMPLE_FORM = `name: UserRegistration
fields:
  - name: username
    type: text
    required: true
    regex: "^[a-zA-Z0-9_]{3,20}$"
  - name: email
    type: text
    required: true
  - name: age
    type: number
    required: true
    min: 18
    max: 120
  - name: newsletter
    type: boolean
    required: false`

export default function RegisterPage() {
  const router = useRouter()
  const { toast } = useToast()
  const registerMutation = useRegisterForms()

  const [formYaml, setFormYaml] = useState('')
  const [registeredFlow, setRegisteredFlow] = useState<RegisterFormsResponse | null>(null)

  useEffect(() => {
    const saved = localStorage.getItem('last_form_yaml')
    if (saved) setFormYaml(saved)

    const savedFlow = localStorage.getItem('last_registered_flow')
    if (savedFlow) {
      try {
        setRegisteredFlow(JSON.parse(savedFlow))
      } catch {}
    }
  }, [])

  const handleRegister = async () => {
    if (!formYaml.trim()) {
      toast({
        title: 'Error',
        description: 'Form YAML is required',
        variant: 'destructive',
      })
      return
    }

    try {
      const result = await registerMutation.mutateAsync({
        form_yaml: formYaml,
      })

      setRegisteredFlow(result)
      localStorage.setItem('last_form_yaml', formYaml)
      localStorage.setItem('last_registered_flow', JSON.stringify(result))

      toast({
        title: 'Success',
        description: `Form "${result.name}" registered`,
      })
    } catch (error: any) {
      toast({
        title: 'Registration Failed',
        description: error.message || 'An error occurred',
        variant: 'destructive',
      })
    }
  }

  return (
    <div className="container mx-auto px-4 py-8">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Register Form</h1>
          <p className="text-muted-foreground">Define your form in YAML</p>
        </div>
        <div className="flex gap-2">
          <Button
            onClick={handleRegister}
            disabled={registerMutation.isPending}
          >
            {registerMutation.isPending ? 'Registering...' : 'Register'}
          </Button>
          {registeredFlow && (
            <Button variant="outline" onClick={() => router.push('/runs/new')}>
              Create Run →
            </Button>
          )}
        </div>
      </div>

      <div className="grid lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>Form YAML</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => setFormYaml(EXAMPLE_FORM)}
              >
                Load Example
              </Button>
              <textarea
                value={formYaml}
                onChange={(e) => setFormYaml(e.target.value)}
                className="w-full h-96 p-4 border rounded font-mono text-sm"
                placeholder="Paste your YAML here..."
              />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Preview</CardTitle>
          </CardHeader>
          <CardContent>
            {registeredFlow ? (
              <div className="space-y-2">
                <p><strong>Flow ID:</strong> {registeredFlow.flow_id}</p>
                <p><strong>Name:</strong> {registeredFlow.name}</p>
                <pre className="text-xs bg-muted p-4 rounded overflow-auto max-h-96">
                  {JSON.stringify(registeredFlow.json_schema, null, 2)}
                </pre>
              </div>
            ) : (
              <p className="text-center py-12 text-muted-foreground">
                Register to see preview
              </p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
