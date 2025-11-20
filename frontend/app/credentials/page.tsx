'use client';

import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useToast } from '@/components/ui/use-toast';
import { ErrorState } from '@/components/error-state';
import type {
  CredentialResponse,
  CreateCredentialRequest,
  UpdateCredentialRequest,
} from '@/lib/types';

// Valid credential types (synced with backend)
const CREDENTIAL_TYPES = [
  { value: 'api_token', label: 'API Token', description: 'API keys and bearer tokens' },
  { value: 'password', label: 'Password', description: 'Username/password credentials' },
  { value: 'ssh_key', label: 'SSH Key', description: 'SSH private keys' },
  { value: 'oauth', label: 'OAuth', description: 'OAuth tokens and secrets' },
  { value: 'certificate', label: 'Certificate', description: 'TLS/SSL certificates' },
] as const;

export default function CredentialsPage() {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [isCreating, setIsCreating] = useState(false);
  const [editingCredential, setEditingCredential] = useState<string | null>(null);

  // Form state
  const [name, setName] = useState('');
  const [credentialType, setCredentialType] = useState('api_token');
  const [description, setDescription] = useState('');
  const [dataJson, setDataJson] = useState('{}');

  // Fetch credentials
  const { data: credentials, isLoading, error, isError } = useQuery({
    queryKey: ['credentials'],
    queryFn: () => api.listCredentials(),
  });

  // Create credential mutation with timeout handling
  const createMutation = useMutation({
    mutationFn: (data: CreateCredentialRequest) => api.createCredential(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['credentials'] });
      toast({
        title: 'Success',
        description: 'Credential created successfully',
      });
      resetForm();
    },
    onError: (error: any) => {
      toast({
        title: 'Error',
        description: error.message || 'Failed to create credential',
        variant: 'destructive',
      });
    },
    // Add retry configuration to prevent stuck state
    retry: false,
  });

  // Update credential mutation with timeout handling
  const updateMutation = useMutation({
    mutationFn: ({ name, data }: { name: string; data: UpdateCredentialRequest }) =>
      api.updateCredential(name, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['credentials'] });
      toast({
        title: 'Success',
        description: 'Credential updated successfully',
      });
      resetForm();
    },
    onError: (error: any) => {
      toast({
        title: 'Error',
        description: error.message || 'Failed to update credential',
        variant: 'destructive',
      });
    },
    // Add retry configuration to prevent stuck state
    retry: false,
  });

  // Auto-reset stuck mutations after timeout
  useEffect(() => {
    let timeout: NodeJS.Timeout;

    if (createMutation.isPending || updateMutation.isPending) {
      // If mutation is pending for more than 30 seconds, show warning
      timeout = setTimeout(() => {
        if (createMutation.isPending || updateMutation.isPending) {
          toast({
            title: 'Warning',
            description: 'Request is taking longer than expected. Please check your connection.',
            variant: 'destructive',
          });

          // Auto-reset after 60 seconds total
          setTimeout(() => {
            if (createMutation.isPending || updateMutation.isPending) {
              toast({
                title: 'Timeout',
                description: 'Request timed out. Please try again.',
                variant: 'destructive',
              });
              createMutation.reset();
              updateMutation.reset();
            }
          }, 30000);
        }
      }, 30000);
    }

    return () => clearTimeout(timeout);
  }, [createMutation.isPending, updateMutation.isPending, createMutation, updateMutation, toast]);

  // Delete credential mutation
  const deleteMutation = useMutation({
    mutationFn: (name: string) => api.deleteCredential(name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['credentials'] });
      toast({
        title: 'Success',
        description: 'Credential deleted successfully',
      });
    },
    onError: (error: any) => {
      toast({
        title: 'Error',
        description: error.message || 'Failed to delete credential',
        variant: 'destructive',
      });
    },
  });

  const resetForm = () => {
    setIsCreating(false);
    setEditingCredential(null);
    setName('');
    setCredentialType('api_token');
    setDescription('');
    setDataJson('{}');
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    let data: Record<string, any>;
    try {
      data = JSON.parse(dataJson);
    } catch {
      toast({
        title: 'Error',
        description: 'Invalid JSON in data field',
        variant: 'destructive',
      });
      return;
    }

    if (editingCredential) {
      updateMutation.mutate({
        name: editingCredential,
        data: { data, description },
      });
    } else {
      createMutation.mutate({
        name,
        type: credentialType,
        data,
        description,
      });
    }
  };

  const handleEdit = (credential: CredentialResponse) => {
    setEditingCredential(credential.name);
    setName(credential.name);
    setCredentialType(credential.type);
    setDescription(credential.description || '');
    setDataJson('{}'); // Can't show actual data
    setIsCreating(true);
  };

  const handleDelete = (name: string) => {
    if (confirm(`Are you sure you want to delete credential "${name}"?`)) {
      deleteMutation.mutate(name);
    }
  };

  return (
    <div className="container mx-auto py-8">
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Credentials</h1>
          <p className="text-gray-600 mt-1">Manage encrypted credentials for workflows</p>
        </div>
        <Button onClick={() => setIsCreating(true)}>+ New Credential</Button>
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
                className="w-full border rounded-md p-2 bg-white disabled:opacity-50 disabled:cursor-not-allowed"
                value={credentialType}
                onChange={(e) => setCredentialType(e.target.value)}
                disabled={!!editingCredential}
                required
              >
                {CREDENTIAL_TYPES.map((type) => (
                  <option key={type.value} value={type.value}>
                    {type.label}
                  </option>
                ))}
              </select>
              {!editingCredential && (
                <p className="text-sm text-gray-500 mt-1">
                  {CREDENTIAL_TYPES.find((t) => t.value === credentialType)?.description}
                </p>
              )}
              {editingCredential && (
                <p className="text-sm text-gray-500 mt-1">Type cannot be changed when editing</p>
              )}
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
                {createMutation.isPending || updateMutation.isPending ? (
                  <span className="flex items-center gap-2">
                    <span className="animate-spin">⏳</span>
                    {editingCredential ? 'Updating...' : 'Creating...'}
                  </span>
                ) : (
                  editingCredential ? 'Update' : 'Create'
                )}
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={resetForm}
                disabled={createMutation.isPending || updateMutation.isPending}
              >
                Cancel
              </Button>
            </div>
            {(createMutation.isPending || updateMutation.isPending) && (
              <p className="text-sm text-blue-600">
                Submitting credential... This may take a few seconds.
              </p>
            )}
          </form>
        </Card>
      )}

      {/* Credentials List */}
      {isError ? (
        <ErrorState
          error={error}
          title="Failed to Load Credentials"
          onRetry={() => window.location.reload()}
        />
      ) : isLoading ? (
        <div className="text-center py-8">Loading credentials...</div>
      ) : credentials && credentials.items && credentials.items.length > 0 ? (
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
                  <Button variant="outline" size="sm" onClick={() => handleEdit(credential)}>
                    Edit
                  </Button>
                  <Button
                    variant="outline"
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
          <Button onClick={() => setIsCreating(true)}>Create Your First Credential</Button>
        </Card>
      )}
    </div>
  );
}
