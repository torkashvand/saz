'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useToast } from '@/hooks/use-toast'
import type { CredentialResponse, CreateCredentialRequest, UpdateCredentialRequest } from '@/lib/types'

export default function CredentialsPage() {
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const [isCreating, setIsCreating] = useState(false)
  const [editingCredential, setEditingCredential] = useState<string | null>(null)

  // Form state
  const [name, setName] = useState('')
  const [credentialType, setCredentialType] = useState('api_token')
  const [description, setDescription] = useState('')
  const [dataJson, setDataJson] = useState('{}')

  // Fetch credentials
  const { data: credentials, isLoading } = useQuery({
    queryKey: ['credentials'],
    queryFn: () => api.listCredentials(),
  })

  // Create credential mutation
  const createMutation = useMutation({
    mutationFn: (data: CreateCredentialRequest) => api.createCredential(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['credentials'] })
      toast({
        title: 'Success',
        description: 'Credential created successfully',
      })
      resetForm()
    },
    onError: (error: any) => {
      toast({
        title: 'Error',
        description: error.message || 'Failed to create credential',
        variant: 'destructive',
      })
    },
  })

  // Update credential mutation
  const updateMutation = useMutation({
    mutationFn: ({ name, data }: { name: string; data: UpdateCredentialRequest }) =>
      api.updateCredential(name, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['credentials'] })
      toast({
        title: 'Success',
        description: 'Credential updated successfully',
      })
      resetForm()
    },
    onError: (error: any) => {
      toast({
        title: 'Error',
        description: error.message || 'Failed to update credential',
        variant: 'destructive',
      })
    },
  })

  // Delete credential mutation
  const deleteMutation = useMutation({
    mutationFn: (name: string) => api.deleteCredential(name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['credentials'] })
      toast({
        title: 'Success',
        description: 'Credential deleted successfully',
      })
    },
    onError: (error: any) => {
      toast({
        title: 'Error',
        description: error.message || 'Failed to delete credential',
        variant: 'destructive',
      })
    },
  })

  const resetForm = () => {
    setIsCreating(false)
    setEditingCredential(null)
    setName('')
    setCredentialType('api_token')
    setDescription('')
    setDataJson('{}')
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()

    let data: Record<string, any>
    try {
      data = JSON.parse(dataJson)
    } catch {
      toast({
        title: 'Error',
        description: 'Invalid JSON in data field',
        variant: 'destructive',
      })
      return
    }

    if (editingCredential) {
      updateMutation.mutate({
        name: editingCredential,
        data: { data, description },
      })
    } else {
      createMutation.mutate({
        name,
        credential_type: credentialType,
        data,
        description,
      })
    }
  }

  const handleEdit = (credential: CredentialResponse) => {
    setEditingCredential(credential.name)
    setName(credential.name)
    setCredentialType(credential.type)
    setDescription(credential.description || '')
    setDataJson('{}') // Can't show actual data
    setIsCreating(true)
  }

  const handleDelete = (name: string) => {
    if (confirm(`Are you sure you want to delete credential "${name}"?`)) {
      deleteMutation.mutate(name)
    }
  }

  return (
    <div className="container mx-auto py-8">
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Credentials</h1>
          <p className="text-gray-600 mt-1">
            Manage encrypted credentials for workflows
          </p>
        </div>
        <Button onClick={() => setIsCreating(true)}>
          + New Credential
        </Button>
      </div>

      {/* Create/Edit Form */}
      {isCreating && (
        <Card className="mb-8 p-6">
          <h2 className="text-xl font-semibold mb-4">
            {editingCredential ? 'Update Credential' : 'Create Credential'}
          </h2>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <Label htmlFor="name">Name</Label>
              <Input
                id="name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="my-api-key"
                disabled={!!editingCredential}
                required
              />
            </div>

            <div>
              <Label htmlFor="type">Type</Label>
              <select
                id="type"
                className="w-full border rounded-md p-2"
                value={credentialType}
                onChange={(e) => setCredentialType(e.target.value)}
                disabled={!!editingCredential}
                required
              >
                <option value="api_token">API Token</option>
                <option value="password">Password</option>
                <option value="ssh_key">SSH Key</option>
                <option value="oauth">OAuth</option>
                <option value="certificate">Certificate</option>
              </select>
            </div>

            <div>
              <Label htmlFor="description">Description (optional)</Label>
              <Input
                id="description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="OpenAI API key for production"
              />
            </div>

            <div>
              <Label htmlFor="data">Data (JSON)</Label>
              <textarea
                id="data"
                className="w-full border rounded-md p-2 font-mono text-sm"
                value={dataJson}
                onChange={(e) => setDataJson(e.target.value)}
                placeholder='{"token": "sk-..."}'
                rows={6}
                required
              />
              <p className="text-sm text-gray-500 mt-1">
                Example: {`{"token": "sk-...", "endpoint": "https://..."}`}
              </p>
            </div>

            <div className="flex gap-2">
              <Button type="submit" disabled={createMutation.isPending || updateMutation.isPending}>
                {editingCredential ? 'Update' : 'Create'}
              </Button>
              <Button type="button" variant="outline" onClick={resetForm}>
                Cancel
              </Button>
            </div>
          </form>
        </Card>
      )}

      {/* Credentials List */}
      {isLoading ? (
        <div className="text-center py-8">Loading credentials...</div>
      ) : credentials && credentials.items.length > 0 ? (
        <div className="grid gap-4">
          {credentials.items.map((credential) => (
            <Card key={credential.name} className="p-6">
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <div className="flex items-center gap-3">
                    <h3 className="text-lg font-semibold">{credential.name}</h3>
                    <span className="px-2 py-1 text-xs rounded-full bg-blue-100 text-blue-800">
                      {credential.type}
                    </span>
                  </div>
                  {credential.description && (
                    <p className="text-gray-600 mt-1">{credential.description}</p>
                  )}
                  <div className="flex gap-4 mt-2 text-sm text-gray-500">
                    <span>Created: {new Date(credential.created_at).toLocaleDateString()}</span>
                    <span>Updated: {new Date(credential.updated_at).toLocaleDateString()}</span>
                  </div>
                </div>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => handleEdit(credential)}
                  >
                    Edit
                  </Button>
                  <Button
                    variant="destructive"
                    size="sm"
                    onClick={() => handleDelete(credential.name)}
                    disabled={deleteMutation.isPending}
                  >
                    Delete
                  </Button>
                </div>
              </div>
            </Card>
          ))}
        </div>
      ) : (
        <Card className="p-12 text-center">
          <p className="text-gray-500 mb-4">No credentials yet</p>
          <Button onClick={() => setIsCreating(true)}>
            Create Your First Credential
          </Button>
        </Card>
      )}
    </div>
  )
}