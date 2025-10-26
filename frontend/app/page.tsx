import Link from 'next/link'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

export default function HomePage() {
  return (
    <div className="container mx-auto px-4 py-12">
      <div className="max-w-3xl mx-auto space-y-8">
        <div className="text-center space-y-4">
          <h1 className="text-4xl font-bold">Saz</h1>
          <p className="text-xl text-muted-foreground">
            Define forms in YAML, execute workflows, track progress
          </p>
        </div>

        <div className="grid md:grid-cols-2 gap-6">
          <Card>
            <CardHeader>
              <CardTitle>1. Register a Form</CardTitle>
              <CardDescription>
                Define your form fields and optional workflow steps in YAML
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Link href="/register">
                <Button className="w-full">Go to Register</Button>
              </Link>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>2. Create a Run</CardTitle>
              <CardDescription>
                Fill out your form and create a workflow execution
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Link href="/runs/new">
                <Button className="w-full" variant="secondary">
                  Create Run
                </Button>
              </Link>
            </CardContent>
          </Card>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Quick Start</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <p className="text-sm text-muted-foreground">
              1. <strong>Register</strong>: Paste your form YAML and optional workflow
            </p>
            <p className="text-sm text-muted-foreground">
              2. <strong>Preview</strong>: See the generated form live
            </p>
            <p className="text-sm text-muted-foreground">
              3. <strong>Submit</strong>: Create a workflow run with your data
            </p>
            <p className="text-sm text-muted-foreground">
              4. <strong>Advance</strong>: Step through the workflow execution
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
