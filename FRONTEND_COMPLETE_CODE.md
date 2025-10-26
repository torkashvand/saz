# Complete Frontend Code Reference

Copy these files into your `frontend/` directory.

## App Pages

### `app/register/page.tsx`

```typescript
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
```

### `app/runs/new/page.tsx`

```typescript
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
```

### `app/runs/[id]/page.tsx`

```typescript
'use client'

import { useParams } from 'next/navigation'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { useRun, useAdvanceRun } from '@/lib/hooks'
import { useToast } from '@/components/ui/use-toast'
import { Loader2 } from 'lucide-react'

export default function RunDetailPage() {
  const params = useParams()
  const runId = params.id as string
  const { toast } = useToast()

  const { data: run, isLoading } = useRun(runId)
  const advanceMutation = useAdvanceRun(runId)

  const handleAdvance = async () => {
    try {
      await advanceMutation.mutateAsync({ event: 'continue' })
      toast({
        title: 'Run Advanced',
        description: 'Workflow step executed',
      })
    } catch (error: any) {
      toast({
        title: 'Failed',
        description: error.message,
        variant: 'destructive',
      })
    }
  }

  if (isLoading) {
    return (
      <div className="container mx-auto px-4 py-12 flex justify-center">
        <Loader2 className="h-8 w-8 animate-spin" />
      </div>
    )
  }

  if (!run) {
    return <div className="container mx-auto px-4 py-12">Run not found</div>
  }

  const canAdvance = ['suspended', 'waiting'].includes(run.status)

  return (
    <div className="container mx-auto px-4 py-8">
      <h1 className="text-3xl font-bold mb-6">Run Details</h1>

      <div className="grid gap-6">
        <Card>
          <CardHeader>
            <CardTitle>Status: {run.status}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {canAdvance && (
              <Button
                onClick={handleAdvance}
                disabled={advanceMutation.isPending}
              >
                {advanceMutation.isPending ? 'Advancing...' : 'Advance Workflow'}
              </Button>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>State</CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="text-xs bg-muted p-4 rounded overflow-auto">
              {JSON.stringify(run.state, null, 2)}
            </pre>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
```

## UI Components (shadcn/ui minimal set)

Create these in `components/ui/`:

### `components/ui/button.tsx`

```typescript
import * as React from "react"
import { cn } from "@/lib/utils"

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'default' | 'outline' | 'secondary' | 'ghost'
  size?: 'default' | 'sm' | 'lg'
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = 'default', size = 'default', ...props }, ref) => {
    const variants = {
      default: 'bg-primary text-primary-foreground hover:bg-primary/90',
      outline: 'border border-input bg-background hover:bg-accent',
      secondary: 'bg-secondary text-secondary-foreground hover:bg-secondary/80',
      ghost: 'hover:bg-accent hover:text-accent-foreground',
    }

    const sizes = {
      default: 'h-10 px-4 py-2',
      sm: 'h-9 rounded-md px-3',
      lg: 'h-11 rounded-md px-8',
    }

    return (
      <button
        className={cn(
          'inline-flex items-center justify-center whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 disabled:pointer-events-none disabled:opacity-50',
          variants[variant],
          sizes[size],
          className
        )}
        ref={ref}
        {...props}
      />
    )
  }
)
Button.displayName = "Button"

export { Button }
```

### `components/ui/card.tsx`

```typescript
import * as React from "react"
import { cn } from "@/lib/utils"

const Card = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn("rounded-lg border bg-card text-card-foreground shadow-sm", className)}
      {...props}
    />
  )
)
Card.displayName = "Card"

const CardHeader = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn("flex flex-col space-y-1.5 p-6", className)} {...props} />
  )
)
CardHeader.displayName = "CardHeader"

const CardTitle = React.forwardRef<HTMLParagraphElement, React.HTMLAttributes<HTMLHeadingElement>>(
  ({ className, ...props }, ref) => (
    <h3 ref={ref} className={cn("text-2xl font-semibold leading-none tracking-tight", className)} {...props} />
  )
)
CardTitle.displayName = "CardTitle"

const CardDescription = React.forwardRef<HTMLParagraphElement, React.HTMLAttributes<HTMLParagraphElement>>(
  ({ className, ...props }, ref) => (
    <p ref={ref} className={cn("text-sm text-muted-foreground", className)} {...props} />
  )
)
CardDescription.displayName = "CardDescription"

const CardContent = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn("p-6 pt-0", className)} {...props} />
  )
)
CardContent.displayName = "CardContent"

export { Card, CardHeader, CardTitle, CardDescription, CardContent }
```

### `components/ui/input.tsx`

```typescript
import * as React from "react"
import { cn } from "@/lib/utils"

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {}

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type, ...props }, ref) => {
    return (
      <input
        type={type}
        className={cn(
          "flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50",
          className
        )}
        ref={ref}
        {...props}
      />
    )
  }
)
Input.displayName = "Input"

export { Input }
```

### `components/ui/label.tsx`

```typescript
import * as React from "react"
import { cn } from "@/lib/utils"

const Label = React.forwardRef<HTMLLabelElement, React.LabelHTMLAttributes<HTMLLabelElement>>(
  ({ className, ...props }, ref) => (
    <label
      ref={ref}
      className={cn("text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70", className)}
      {...props}
    />
  )
)
Label.displayName = "Label"

export { Label }
```

### `components/ui/use-toast.ts`

```typescript
import * as React from "react"

export interface Toast {
  id: string
  title?: string
  description?: string
  variant?: "default" | "destructive"
}

type ToasterToast = Toast

let count = 0
function genId() {
  count = (count + 1) % Number.MAX_VALUE
  return count.toString()
}

const listeners: Array<(state: { toasts: ToasterToast[] }) => void> = []
let memoryState: { toasts: ToasterToast[] } = { toasts: [] }

function dispatch(toast: Omit<ToasterToast, "id">) {
  const id = genId()
  const newToast = { ...toast, id, open: true }
  memoryState.toasts = [newToast, ...memoryState.toasts].slice(0, 1)

  listeners.forEach((listener) => {
    listener(memoryState)
  })

  setTimeout(() => {
    memoryState.toasts = memoryState.toasts.filter((t) => t.id !== id)
    listeners.forEach((listener) => listener(memoryState))
  }, 3000)

  return { id, dismiss: () => {} }
}

export function toast(props: Omit<Toast, "id">) {
  return dispatch(props)
}

export function useToast() {
  const [state, setState] = React.useState(memoryState)

  React.useEffect(() => {
    listeners.push(setState)
    return () => {
      const index = listeners.indexOf(setState)
      if (index > -1) {
        listeners.splice(index, 1)
      }
    }
  }, [])

  return {
    ...state,
    toast,
  }
}
```

### `components/ui/toaster.tsx`

```typescript
"use client"

import { useToast } from "./use-toast"

export function Toaster() {
  const { toasts } = useToast()

  return (
    <div className="fixed top-0 right-0 z-[100] flex max-h-screen w-full flex-col-reverse p-4 sm:flex-col md:max-w-[420px]">
      {toasts.map(({ id, title, description, variant }) => (
        <div
          key={id}
          className={`group pointer-events-auto relative flex w-full items-center justify-between space-x-4 overflow-hidden rounded-md border p-6 pr-8 shadow-lg transition-all ${
            variant === 'destructive'
              ? 'border-destructive bg-destructive text-destructive-foreground'
              : 'border bg-background'
          }`}
        >
          <div className="grid gap-1">
            {title && <div className="text-sm font-semibold">{title}</div>}
            {description && <div className="text-sm opacity-90">{description}</div>}
          </div>
        </div>
      ))}
    </div>
  )
}
```

## Installation Commands

```bash
cd /Users/mohammad.torkashvand/www/saz/frontend

# Install dependencies
npm install

# Create .env.local
echo "NEXT_PUBLIC_API_BASE_URL=http://localhost:8000" > .env.local

# Copy all the code above into their respective files

# Start dev server
npm run dev
```

## File Checklist

- [x] package.json
- [x] next.config.js
- [x] tsconfig.json
- [x] tailwind.config.ts
- [x] postcss.config.js
- [x] .env.local.example
- [x] lib/utils.ts
- [x] lib/types.ts
- [x] lib/api.ts
- [x] lib/hooks.ts
- [x] app/globals.css
- [x] app/providers.tsx
- [x] app/layout.tsx
- [x] app/page.tsx
- [ ] app/register/page.tsx (copy from above)
- [ ] app/runs/new/page.tsx (copy from above)
- [ ] app/runs/[id]/page.tsx (copy from above)
- [ ] components/ui/button.tsx (copy from above)
- [ ] components/ui/card.tsx (copy from above)
- [ ] components/ui/input.tsx (copy from above)
- [ ] components/ui/label.tsx (copy from above)
- [ ] components/ui/use-toast.ts (copy from above)
- [ ] components/ui/toaster.tsx (copy from above)
