'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ErrorBanner } from '@/components/ui/error-banner';
import { FieldError } from '@/components/ui/field-error';
import { useErrorToast } from '@/lib/use-error-toast';
import { useAuth } from '@/lib/auth';
import { getFieldError } from '@/lib/errors';
import type { AppError } from '@/lib/errors';
import type {
  CredentialResponse,
  CreateCredentialRequest,
  UpdateCredentialRequest,
} from '@/lib/types';
import { ArrowLeft } from 'lucide-react';

// Valid credential types (synced with backend)
const CREDENTIAL_TYPES = [
  { value: 'api_token', label: 'API Token', description: 'API keys and bearer tokens' },
  { value: 'password', label: 'Password', description: 'Username/password credentials' },
  { value: 'ssh_key', label: 'SSH Key', description: 'SSH private keys' },
  { value: 'oauth', label: 'OAuth', description: 'OAuth tokens and secrets' },
  { value: 'certificate', label: 'Certificate', description: 'TLS/SSL certificates' },
] as const;

type ViewMode = 'list' | 'create' | 'edit';

export default function CredentialsPage() {
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useErrorToast();
  const { canWrite } = useAuth();

  // View mode state
  const [viewMode, setViewMode] = useState<ViewMode>('list');
  const [selectedCredential, setSelectedCredential] = useState<CredentialResponse | null>(null);

  // Form mode: simple (guided) or json (raw)
  const [mode, setMode] = useState<'simple' | 'json'>('simple');

  // Form state
  const [name, setName] = useState('');
  const [credentialType, setCredentialType] = useState('api_token');
  const [description, setDescription] = useState('');
  const [dataJson, setDataJson] = useState('{}');

  // Simple mode field states (type-specific)
  const [simpleFields, setSimpleFields] = useState<Record<string, string>>({
    // api_token
    token: '',
    endpoint: '',
    // password
    username: '',
    password: '',
    // ssh_key
    private_key: '',
    host: '',
    port: '',
    // oauth
    access_token: '',
    refresh_token: '',
    client_id: '',
    client_secret: '',
    // certificate
    cert_pem: '',
    key_pem: '',
    ca_bundle: '',
  });

  // Track mutation error for field-level validation
  const [mutationError, setMutationError] = useState<AppError | null>(null);

  // Track JSON validation error
  const [jsonError, setJsonError] = useState<string | null>(null);

  // Fetch credentials
  const {
    data: credentials,
    isLoading,
    error,
    isError,
  } = useQuery({
    queryKey: ['credentials'],
    queryFn: () => api.listCredentials(),
  });

  // Create credential mutation
  const createMutation = useMutation({
    mutationFn: (data: CreateCredentialRequest) => api.createCredential(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['credentials'] });
      showSuccess('Credential created successfully');
      resetForm();
    },
    onError: (error: AppError) => {
      setMutationError(error);
      if (!error.validationErrors) {
        showError(error);
      }
    },
  });

  // Update credential mutation
  const updateMutation = useMutation({
    mutationFn: ({ name, data }: { name: string; data: UpdateCredentialRequest }) =>
      api.updateCredential(name, data),
    onSuccess: async () => {
      // Force refetch of credentials list
      await queryClient.invalidateQueries({
        queryKey: ['credentials'],
        refetchType: 'active',
      });
      showSuccess('Credential updated successfully');
      resetForm();
    },
    onError: (error: AppError) => {
      setMutationError(error);
      if (!error.validationErrors) {
        showError(error);
      }
    },
  });

  // Delete credential mutation
  const deleteMutation = useMutation({
    mutationFn: (name: string) => api.deleteCredential(name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['credentials'] });
      showSuccess('Credential deleted successfully');
    },
    onError: showError,
  });

  const resetForm = () => {
    setViewMode('list');
    setSelectedCredential(null);
    setMode('simple');
    setName('');
    setCredentialType('api_token');
    setDescription('');
    setDataJson('{}');
    setSimpleFields({
      token: '',
      endpoint: '',
      username: '',
      password: '',
      private_key: '',
      host: '',
      port: '',
      access_token: '',
      refresh_token: '',
      client_id: '',
      client_secret: '',
      cert_pem: '',
      key_pem: '',
      ca_bundle: '',
    });
    setMutationError(null);
    setJsonError(null);
  };

  // Build data object from simple fields based on credential type
  const buildDataFromSimpleFields = (): Record<string, any> => {
    const data: Record<string, any> = {};

    switch (credentialType) {
      case 'api_token':
        if (simpleFields.token) data.token = simpleFields.token;
        if (simpleFields.endpoint) data.endpoint = simpleFields.endpoint;
        break;
      case 'password':
        if (simpleFields.username) data.username = simpleFields.username;
        if (simpleFields.password) data.password = simpleFields.password;
        break;
      case 'ssh_key':
        if (simpleFields.username) data.username = simpleFields.username;
        if (simpleFields.private_key) data.private_key = simpleFields.private_key;
        if (simpleFields.host) data.host = simpleFields.host;
        if (simpleFields.port) data.port = simpleFields.port;
        break;
      case 'oauth':
        if (simpleFields.access_token) data.access_token = simpleFields.access_token;
        if (simpleFields.refresh_token) data.refresh_token = simpleFields.refresh_token;
        if (simpleFields.client_id) data.client_id = simpleFields.client_id;
        if (simpleFields.client_secret) data.client_secret = simpleFields.client_secret;
        break;
      case 'certificate':
        if (simpleFields.cert_pem) data.cert_pem = simpleFields.cert_pem;
        if (simpleFields.key_pem) data.key_pem = simpleFields.key_pem;
        if (simpleFields.ca_bundle) data.ca_bundle = simpleFields.ca_bundle;
        break;
    }

    return data;
  };

  // Validate simple mode fields
  const validateSimpleFields = (): boolean => {
    const requiredFields: Record<string, string[]> = {
      api_token: ['token'],
      password: ['password'],
      ssh_key: ['private_key'],
      oauth: ['access_token'],
      certificate: ['cert_pem'],
    };

    const required = requiredFields[credentialType] || [];
    for (const field of required) {
      if (!simpleFields[field]?.trim()) {
        showError(`${field.replace('_', ' ')} is required`);
        return false;
      }
    }
    return true;
  };

  // Fill with example data
  const fillWithExample = () => {
    const examples: Record<string, Record<string, string>> = {
      api_token: {
        token: 'sk-1234567890abcdef',
        endpoint: 'https://api.example.com',
      },
      password: {
        username: 'admin',
        password: 'secure-password-123',
      },
      ssh_key: {
        username: 'deploy',
        private_key:
          '-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----',
        host: 'example.com',
        port: '22',
      },
      oauth: {
        access_token: 'ya29.a0AfH6SMBx...',
        refresh_token: '1//0gK3Z9X...',
        client_id: '1234567890-abcdefg.apps.googleusercontent.com',
        client_secret: 'GOCSPX-abcdefghijklmnop',
      },
      certificate: {
        cert_pem:
          '-----BEGIN CERTIFICATE-----\nMIIDXTCCAkWgAwIBAgIJAKZ...\n-----END CERTIFICATE-----',
        key_pem:
          '-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0...\n-----END PRIVATE KEY-----',
        ca_bundle:
          '-----BEGIN CERTIFICATE-----\nMIIEkjCCA3qgAwIBAgIQCgFB...\n-----END CERTIFICATE-----',
      },
    };

    const example = examples[credentialType];
    if (example) {
      setSimpleFields({ ...simpleFields, ...example });
    }
  };

  const validateJson = (value: string): boolean => {
    if (!value.trim()) {
      setJsonError('JSON data is required');
      return false;
    }
    try {
      JSON.parse(value);
      setJsonError(null);
      return true;
    } catch (e) {
      setJsonError('Invalid JSON format');
      return false;
    }
  };

  const handleJsonChange = (value: string) => {
    setDataJson(value);
    validateJson(value);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    // Edit mode with the secret left untouched → metadata-only update. The
    // stored value can't be displayed, so an empty form means "keep it"; the
    // PUT omits `data` and the backend preserves the existing payload
    // (sending {} would REPLACE the secret with an empty object).
    if (viewMode === 'edit' && selectedCredential) {
      const secretUntouched =
        mode === 'simple'
          ? Object.keys(buildDataFromSimpleFields()).length === 0
          : dataJson.trim() === '' || dataJson.trim() === '{}';
      if (secretUntouched) {
        updateMutation.mutate({
          name: selectedCredential.name,
          data: { description },
        });
        return;
      }
    }

    let data: Record<string, any>;

    if (mode === 'simple') {
      // Validate simple fields
      if (!validateSimpleFields()) {
        return;
      }
      data = buildDataFromSimpleFields();
    } else {
      // Validate JSON
      if (!validateJson(dataJson)) {
        showError('Please fix the JSON format error');
        return;
      }
      try {
        data = JSON.parse(dataJson);
      } catch {
        showError('Invalid JSON in data field');
        return;
      }
    }

    if (viewMode === 'edit' && selectedCredential) {
      updateMutation.mutate({
        name: selectedCredential.name,
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
    setSelectedCredential(credential);
    setViewMode('edit');
    setName(credential.name);
    setCredentialType(credential.type);
    setDescription(credential.description || '');
    setDataJson('{}'); // Can't show actual data
    setJsonError(null); // Clear any JSON validation errors
    setMutationError(null); // Clear any mutation errors
    setMode('simple'); // Reset to simple mode for editing
  };

  const handleDelete = (name: string) => {
    if (confirm(`Are you sure you want to delete credential "${name}"?`)) {
      deleteMutation.mutate(name);
    }
  };

  const handleStartCreate = () => {
    resetForm();
    setViewMode('create');
  };

  // EDIT MODE: Show only the form with back button
  if (viewMode === 'edit') {
    return (
      <div className="container mx-auto py-8">
        {/* Back button */}
        <button
          onClick={resetForm}
          className="flex items-center gap-2 text-sm text-gray-600 hover:text-gray-900 mb-6 transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to credentials
        </button>

        <Card className="p-6">
          <h2 className="text-xl font-semibold mb-4">
            Update Credential: {selectedCredential?.name}
          </h2>

          {/* Show general error banner if not a validation error */}
          {mutationError && !mutationError.validationErrors && (
            <ErrorBanner
              error={mutationError}
              title="Failed to Update Credential"
              onDismiss={() => setMutationError(null)}
            />
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <Label htmlFor="name">Name</Label>
              <Input
                id="name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="my-api-key"
                disabled
                required
              />
              <FieldError message={getFieldError(mutationError, 'name')} />
            </div>

            <div>
              <Label htmlFor="type">Type</Label>
              <select
                id="type"
                className="w-full border rounded-md p-2 bg-white disabled:opacity-50 disabled:cursor-not-allowed"
                value={credentialType}
                onChange={(e) => setCredentialType(e.target.value)}
                disabled
                required
              >
                {CREDENTIAL_TYPES.map((type) => (
                  <option key={type.value} value={type.value}>
                    {type.label}
                  </option>
                ))}
              </select>
              <p className="text-sm text-gray-500 mt-1">Type cannot be changed when editing</p>
              <FieldError message={getFieldError(mutationError, 'type')} />
            </div>

            <div>
              <Label htmlFor="description">Description (optional)</Label>
              <Input
                id="description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="OpenAI API key for production"
              />
              <FieldError message={getFieldError(mutationError, 'description')} />
            </div>

            {/* Mode toggle and data entry */}
            <div>
              <div className="flex items-center justify-between mb-3">
                <Label>Credential Data</Label>
                {/* Mode toggle */}
                <div className="flex items-center gap-2 border rounded-lg p-1 bg-gray-50">
                  <button
                    type="button"
                    onClick={() => setMode('simple')}
                    className={`px-3 py-1 text-sm rounded transition-colors ${
                      mode === 'simple'
                        ? 'bg-white text-gray-900 shadow-sm font-medium'
                        : 'text-gray-600 hover:text-gray-900'
                    }`}
                  >
                    Simple
                  </button>
                  <button
                    type="button"
                    onClick={() => setMode('json')}
                    className={`px-3 py-1 text-sm rounded transition-colors ${
                      mode === 'json'
                        ? 'bg-white text-gray-900 shadow-sm font-medium'
                        : 'text-gray-600 hover:text-gray-900'
                    }`}
                  >
                    JSON
                  </button>
                </div>
              </div>

              <div className="mb-3 p-2 bg-blue-50 border border-blue-200 rounded text-sm text-blue-800">
                ⓘ For security, existing credential data cannot be displayed. Enter new credential
                data to update.
              </div>

              {mode === 'simple' ? (
                <>
                  {/* Type-specific simple fields */}
                  {credentialType === 'api_token' && (
                    <div className="space-y-3 p-4 border rounded-lg bg-gray-50">
                      <div>
                        <Label htmlFor="token">Token *</Label>
                        <Input
                          id="token"
                          type="password"
                          value={simpleFields.token}
                          onChange={(e) =>
                            setSimpleFields({ ...simpleFields, token: e.target.value })
                          }
                          placeholder="sk-1234567890abcdef"
                          required={mode === 'simple'}
                        />
                      </div>
                      <div>
                        <Label htmlFor="endpoint">Endpoint (optional)</Label>
                        <Input
                          id="endpoint"
                          value={simpleFields.endpoint}
                          onChange={(e) =>
                            setSimpleFields({ ...simpleFields, endpoint: e.target.value })
                          }
                          placeholder="https://api.example.com"
                        />
                      </div>
                    </div>
                  )}

                  {credentialType === 'password' && (
                    <div className="space-y-3 p-4 border rounded-lg bg-gray-50">
                      <div>
                        <Label htmlFor="username">Username (optional)</Label>
                        <Input
                          id="username"
                          value={simpleFields.username}
                          onChange={(e) =>
                            setSimpleFields({ ...simpleFields, username: e.target.value })
                          }
                          placeholder="admin"
                        />
                      </div>
                      <div>
                        <Label htmlFor="password">Password *</Label>
                        <Input
                          id="password"
                          type="password"
                          value={simpleFields.password}
                          onChange={(e) =>
                            setSimpleFields({ ...simpleFields, password: e.target.value })
                          }
                          placeholder="secure-password-123"
                          required={mode === 'simple'}
                        />
                      </div>
                    </div>
                  )}

                  {credentialType === 'ssh_key' && (
                    <div className="space-y-3 p-4 border rounded-lg bg-gray-50">
                      <div>
                        <Label htmlFor="username">Username (optional)</Label>
                        <Input
                          id="username"
                          value={simpleFields.username}
                          onChange={(e) =>
                            setSimpleFields({ ...simpleFields, username: e.target.value })
                          }
                          placeholder="deploy"
                        />
                      </div>
                      <div>
                        <Label htmlFor="private_key">Private Key *</Label>
                        <textarea
                          id="private_key"
                          className="w-full border rounded-md p-2 font-mono text-sm"
                          value={simpleFields.private_key}
                          onChange={(e) =>
                            setSimpleFields({ ...simpleFields, private_key: e.target.value })
                          }
                          placeholder="-----BEGIN RSA PRIVATE KEY-----&#10;...&#10;-----END RSA PRIVATE KEY-----"
                          rows={4}
                          required={mode === 'simple'}
                        />
                      </div>
                      <div className="grid grid-cols-2 gap-3">
                        <div>
                          <Label htmlFor="host">Host (optional)</Label>
                          <Input
                            id="host"
                            value={simpleFields.host}
                            onChange={(e) =>
                              setSimpleFields({ ...simpleFields, host: e.target.value })
                            }
                            placeholder="example.com"
                          />
                        </div>
                        <div>
                          <Label htmlFor="port">Port (optional)</Label>
                          <Input
                            id="port"
                            value={simpleFields.port}
                            onChange={(e) =>
                              setSimpleFields({ ...simpleFields, port: e.target.value })
                            }
                            placeholder="22"
                          />
                        </div>
                      </div>
                    </div>
                  )}

                  {credentialType === 'oauth' && (
                    <div className="space-y-3 p-4 border rounded-lg bg-gray-50">
                      <div>
                        <Label htmlFor="access_token">Access Token *</Label>
                        <Input
                          id="access_token"
                          type="password"
                          value={simpleFields.access_token}
                          onChange={(e) =>
                            setSimpleFields({ ...simpleFields, access_token: e.target.value })
                          }
                          placeholder="ya29.a0AfH6SMBx..."
                          required={mode === 'simple'}
                        />
                      </div>
                      <div>
                        <Label htmlFor="refresh_token">Refresh Token (optional)</Label>
                        <Input
                          id="refresh_token"
                          type="password"
                          value={simpleFields.refresh_token}
                          onChange={(e) =>
                            setSimpleFields({ ...simpleFields, refresh_token: e.target.value })
                          }
                          placeholder="1//0gK3Z9X..."
                        />
                      </div>
                      <div>
                        <Label htmlFor="client_id">Client ID (optional)</Label>
                        <Input
                          id="client_id"
                          value={simpleFields.client_id}
                          onChange={(e) =>
                            setSimpleFields({ ...simpleFields, client_id: e.target.value })
                          }
                          placeholder="1234567890-abcdefg.apps.googleusercontent.com"
                        />
                      </div>
                      <div>
                        <Label htmlFor="client_secret">Client Secret (optional)</Label>
                        <Input
                          id="client_secret"
                          type="password"
                          value={simpleFields.client_secret}
                          onChange={(e) =>
                            setSimpleFields({ ...simpleFields, client_secret: e.target.value })
                          }
                          placeholder="GOCSPX-abcdefghijklmnop"
                        />
                      </div>
                    </div>
                  )}

                  {credentialType === 'certificate' && (
                    <div className="space-y-3 p-4 border rounded-lg bg-gray-50">
                      <div>
                        <Label htmlFor="cert_pem">Certificate PEM *</Label>
                        <textarea
                          id="cert_pem"
                          className="w-full border rounded-md p-2 font-mono text-sm"
                          value={simpleFields.cert_pem}
                          onChange={(e) =>
                            setSimpleFields({ ...simpleFields, cert_pem: e.target.value })
                          }
                          placeholder="-----BEGIN CERTIFICATE-----&#10;...&#10;-----END CERTIFICATE-----"
                          rows={3}
                          required={mode === 'simple'}
                        />
                      </div>
                      <div>
                        <Label htmlFor="key_pem">Private Key PEM (optional)</Label>
                        <textarea
                          id="key_pem"
                          className="w-full border rounded-md p-2 font-mono text-sm"
                          value={simpleFields.key_pem}
                          onChange={(e) =>
                            setSimpleFields({ ...simpleFields, key_pem: e.target.value })
                          }
                          placeholder="-----BEGIN PRIVATE KEY-----&#10;...&#10;-----END PRIVATE KEY-----"
                          rows={3}
                        />
                      </div>
                      <div>
                        <Label htmlFor="ca_bundle">CA Bundle (optional)</Label>
                        <textarea
                          id="ca_bundle"
                          className="w-full border rounded-md p-2 font-mono text-sm"
                          value={simpleFields.ca_bundle}
                          onChange={(e) =>
                            setSimpleFields({ ...simpleFields, ca_bundle: e.target.value })
                          }
                          placeholder="-----BEGIN CERTIFICATE-----&#10;...&#10;-----END CERTIFICATE-----"
                          rows={3}
                        />
                      </div>
                    </div>
                  )}

                  {/* Fill with example button */}
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={fillWithExample}
                    className="mt-2"
                  >
                    Fill with example
                  </Button>
                </>
              ) : (
                <>
                  {/* JSON mode */}
                  <textarea
                    id="data"
                    className={`w-full border rounded-md p-2 font-mono text-sm ${
                      jsonError ? 'border-red-500 bg-red-50' : 'border-gray-300'
                    }`}
                    value={dataJson}
                    onChange={(e) => handleJsonChange(e.target.value)}
                    placeholder='{"token": "sk-..."}'
                    rows={8}
                    required={mode === 'json'}
                  />
                  <p className="text-sm text-gray-500 mt-1">
                    Example: {`{"token": "sk-...", "endpoint": "https://..."}`}
                  </p>
                  {jsonError && <FieldError message={jsonError} />}
                </>
              )}

              <FieldError message={getFieldError(mutationError, 'data')} />
            </div>

            <div className="flex gap-2">
              <Button type="submit" disabled={updateMutation.isPending || !!jsonError}>
                {updateMutation.isPending ? (
                  <span className="flex items-center gap-2">
                    <span className="animate-spin">⏳</span>
                    Updating...
                  </span>
                ) : (
                  'Update'
                )}
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={resetForm}
                disabled={updateMutation.isPending}
              >
                Cancel
              </Button>
            </div>
            {updateMutation.isPending && (
              <p className="text-sm text-blue-600">
                Submitting credential... This may take a few seconds.
              </p>
            )}
          </form>
        </Card>
      </div>
    );
  }

  // LIST/CREATE MODE: Show header + optional create form + credential list
  return (
    <div className="container mx-auto py-8">
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Credentials</h1>
          <p className="text-gray-600 mt-1">Manage encrypted credentials for workflows</p>
        </div>
        {viewMode === 'list' && canWrite && (
          <Button onClick={handleStartCreate}>+ New Credential</Button>
        )}
      </div>

      {/* Create Form (only in create mode) */}
      {viewMode === 'create' && (
        <Card className="mb-8 p-6">
          <h2 className="text-xl font-semibold mb-4">Create Credential</h2>

          {/* Show general error banner if not a validation error */}
          {mutationError && !mutationError.validationErrors && (
            <ErrorBanner
              error={mutationError}
              title="Failed to Create Credential"
              onDismiss={() => setMutationError(null)}
            />
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <Label htmlFor="name">Name</Label>
              <Input
                id="name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="my-api-key"
                required
              />
              <FieldError message={getFieldError(mutationError, 'name')} />
            </div>

            <div>
              <Label htmlFor="type">Type</Label>
              <select
                id="type"
                className="w-full border rounded-md p-2 bg-white"
                value={credentialType}
                onChange={(e) => setCredentialType(e.target.value)}
                required
              >
                {CREDENTIAL_TYPES.map((type) => (
                  <option key={type.value} value={type.value}>
                    {type.label}
                  </option>
                ))}
              </select>
              <p className="text-sm text-gray-500 mt-1">
                {CREDENTIAL_TYPES.find((t) => t.value === credentialType)?.description}
              </p>
              <FieldError message={getFieldError(mutationError, 'type')} />
            </div>

            <div>
              <Label htmlFor="description">Description (optional)</Label>
              <Input
                id="description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="OpenAI API key for production"
              />
              <FieldError message={getFieldError(mutationError, 'description')} />
            </div>

            {/* Mode toggle and data entry */}
            <div>
              <div className="flex items-center justify-between mb-3">
                <Label>Credential Data</Label>
                {/* Mode toggle */}
                <div className="flex items-center gap-2 border rounded-lg p-1 bg-gray-50">
                  <button
                    type="button"
                    onClick={() => setMode('simple')}
                    className={`px-3 py-1 text-sm rounded transition-colors ${
                      mode === 'simple'
                        ? 'bg-white text-gray-900 shadow-sm font-medium'
                        : 'text-gray-600 hover:text-gray-900'
                    }`}
                  >
                    Simple
                  </button>
                  <button
                    type="button"
                    onClick={() => setMode('json')}
                    className={`px-3 py-1 text-sm rounded transition-colors ${
                      mode === 'json'
                        ? 'bg-white text-gray-900 shadow-sm font-medium'
                        : 'text-gray-600 hover:text-gray-900'
                    }`}
                  >
                    JSON
                  </button>
                </div>
              </div>

              {mode === 'simple' ? (
                <>
                  {/* Type-specific simple fields */}
                  {credentialType === 'api_token' && (
                    <div className="space-y-3 p-4 border rounded-lg bg-gray-50">
                      <div>
                        <Label htmlFor="token">Token *</Label>
                        <Input
                          id="token"
                          type="password"
                          value={simpleFields.token}
                          onChange={(e) =>
                            setSimpleFields({ ...simpleFields, token: e.target.value })
                          }
                          placeholder="sk-1234567890abcdef"
                          required={mode === 'simple'}
                        />
                      </div>
                      <div>
                        <Label htmlFor="endpoint">Endpoint (optional)</Label>
                        <Input
                          id="endpoint"
                          value={simpleFields.endpoint}
                          onChange={(e) =>
                            setSimpleFields({ ...simpleFields, endpoint: e.target.value })
                          }
                          placeholder="https://api.example.com"
                        />
                      </div>
                    </div>
                  )}

                  {credentialType === 'password' && (
                    <div className="space-y-3 p-4 border rounded-lg bg-gray-50">
                      <div>
                        <Label htmlFor="username">Username (optional)</Label>
                        <Input
                          id="username"
                          value={simpleFields.username}
                          onChange={(e) =>
                            setSimpleFields({ ...simpleFields, username: e.target.value })
                          }
                          placeholder="admin"
                        />
                      </div>
                      <div>
                        <Label htmlFor="password">Password *</Label>
                        <Input
                          id="password"
                          type="password"
                          value={simpleFields.password}
                          onChange={(e) =>
                            setSimpleFields({ ...simpleFields, password: e.target.value })
                          }
                          placeholder="secure-password-123"
                          required={mode === 'simple'}
                        />
                      </div>
                    </div>
                  )}

                  {credentialType === 'ssh_key' && (
                    <div className="space-y-3 p-4 border rounded-lg bg-gray-50">
                      <div>
                        <Label htmlFor="username">Username (optional)</Label>
                        <Input
                          id="username"
                          value={simpleFields.username}
                          onChange={(e) =>
                            setSimpleFields({ ...simpleFields, username: e.target.value })
                          }
                          placeholder="deploy"
                        />
                      </div>
                      <div>
                        <Label htmlFor="private_key">Private Key *</Label>
                        <textarea
                          id="private_key"
                          className="w-full border rounded-md p-2 font-mono text-sm"
                          value={simpleFields.private_key}
                          onChange={(e) =>
                            setSimpleFields({ ...simpleFields, private_key: e.target.value })
                          }
                          placeholder="-----BEGIN RSA PRIVATE KEY-----&#10;...&#10;-----END RSA PRIVATE KEY-----"
                          rows={4}
                          required={mode === 'simple'}
                        />
                      </div>
                      <div className="grid grid-cols-2 gap-3">
                        <div>
                          <Label htmlFor="host">Host (optional)</Label>
                          <Input
                            id="host"
                            value={simpleFields.host}
                            onChange={(e) =>
                              setSimpleFields({ ...simpleFields, host: e.target.value })
                            }
                            placeholder="example.com"
                          />
                        </div>
                        <div>
                          <Label htmlFor="port">Port (optional)</Label>
                          <Input
                            id="port"
                            value={simpleFields.port}
                            onChange={(e) =>
                              setSimpleFields({ ...simpleFields, port: e.target.value })
                            }
                            placeholder="22"
                          />
                        </div>
                      </div>
                    </div>
                  )}

                  {credentialType === 'oauth' && (
                    <div className="space-y-3 p-4 border rounded-lg bg-gray-50">
                      <div>
                        <Label htmlFor="access_token">Access Token *</Label>
                        <Input
                          id="access_token"
                          type="password"
                          value={simpleFields.access_token}
                          onChange={(e) =>
                            setSimpleFields({ ...simpleFields, access_token: e.target.value })
                          }
                          placeholder="ya29.a0AfH6SMBx..."
                          required={mode === 'simple'}
                        />
                      </div>
                      <div>
                        <Label htmlFor="refresh_token">Refresh Token (optional)</Label>
                        <Input
                          id="refresh_token"
                          type="password"
                          value={simpleFields.refresh_token}
                          onChange={(e) =>
                            setSimpleFields({ ...simpleFields, refresh_token: e.target.value })
                          }
                          placeholder="1//0gK3Z9X..."
                        />
                      </div>
                      <div>
                        <Label htmlFor="client_id">Client ID (optional)</Label>
                        <Input
                          id="client_id"
                          value={simpleFields.client_id}
                          onChange={(e) =>
                            setSimpleFields({ ...simpleFields, client_id: e.target.value })
                          }
                          placeholder="1234567890-abcdefg.apps.googleusercontent.com"
                        />
                      </div>
                      <div>
                        <Label htmlFor="client_secret">Client Secret (optional)</Label>
                        <Input
                          id="client_secret"
                          type="password"
                          value={simpleFields.client_secret}
                          onChange={(e) =>
                            setSimpleFields({ ...simpleFields, client_secret: e.target.value })
                          }
                          placeholder="GOCSPX-abcdefghijklmnop"
                        />
                      </div>
                    </div>
                  )}

                  {credentialType === 'certificate' && (
                    <div className="space-y-3 p-4 border rounded-lg bg-gray-50">
                      <div>
                        <Label htmlFor="cert_pem">Certificate PEM *</Label>
                        <textarea
                          id="cert_pem"
                          className="w-full border rounded-md p-2 font-mono text-sm"
                          value={simpleFields.cert_pem}
                          onChange={(e) =>
                            setSimpleFields({ ...simpleFields, cert_pem: e.target.value })
                          }
                          placeholder="-----BEGIN CERTIFICATE-----&#10;...&#10;-----END CERTIFICATE-----"
                          rows={3}
                          required={mode === 'simple'}
                        />
                      </div>
                      <div>
                        <Label htmlFor="key_pem">Private Key PEM (optional)</Label>
                        <textarea
                          id="key_pem"
                          className="w-full border rounded-md p-2 font-mono text-sm"
                          value={simpleFields.key_pem}
                          onChange={(e) =>
                            setSimpleFields({ ...simpleFields, key_pem: e.target.value })
                          }
                          placeholder="-----BEGIN PRIVATE KEY-----&#10;...&#10;-----END PRIVATE KEY-----"
                          rows={3}
                        />
                      </div>
                      <div>
                        <Label htmlFor="ca_bundle">CA Bundle (optional)</Label>
                        <textarea
                          id="ca_bundle"
                          className="w-full border rounded-md p-2 font-mono text-sm"
                          value={simpleFields.ca_bundle}
                          onChange={(e) =>
                            setSimpleFields({ ...simpleFields, ca_bundle: e.target.value })
                          }
                          placeholder="-----BEGIN CERTIFICATE-----&#10;...&#10;-----END CERTIFICATE-----"
                          rows={3}
                        />
                      </div>
                    </div>
                  )}

                  {/* Fill with example button */}
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={fillWithExample}
                    className="mt-2"
                  >
                    Fill with example
                  </Button>
                </>
              ) : (
                <>
                  {/* JSON mode */}
                  <textarea
                    id="data"
                    className={`w-full border rounded-md p-2 font-mono text-sm ${
                      jsonError ? 'border-red-500 bg-red-50' : 'border-gray-300'
                    }`}
                    value={dataJson}
                    onChange={(e) => handleJsonChange(e.target.value)}
                    placeholder='{"token": "sk-..."}'
                    rows={8}
                    required={mode === 'json'}
                  />
                  <p className="text-sm text-gray-500 mt-1">
                    Example: {`{"token": "sk-...", "endpoint": "https://..."}`}
                  </p>
                  {jsonError && <FieldError message={jsonError} />}
                </>
              )}

              <FieldError message={getFieldError(mutationError, 'data')} />
            </div>

            <div className="flex gap-2">
              <Button type="submit" disabled={createMutation.isPending || !!jsonError}>
                {createMutation.isPending ? (
                  <span className="flex items-center gap-2">
                    <span className="animate-spin">⏳</span>
                    Creating...
                  </span>
                ) : (
                  'Create'
                )}
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={resetForm}
                disabled={createMutation.isPending}
              >
                Cancel
              </Button>
            </div>
            {createMutation.isPending && (
              <p className="text-sm text-blue-600">
                Submitting credential... This may take a few seconds.
              </p>
            )}
          </form>
        </Card>
      )}

      {/* Credentials List */}
      {error ? (
        <ErrorBanner
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
                {canWrite && (
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
                )}
              </div>
            </Card>
          ))}
        </div>
      ) : (
        <Card className="p-12 text-center">
          <p className="text-gray-500 mb-4">No credentials yet</p>
          {canWrite && <Button onClick={handleStartCreate}>Create Your First Credential</Button>}
        </Card>
      )}
    </div>
  );
}
