# Saz Frontend

Modern Next.js 14 frontend for YAML forms & workflow engine.

## Prerequisites

- Node.js 18+ (recommend 20+)
- npm
- Backend API running on `http://localhost:8000`

## Quick Setup

```bash
# 1. Install dependencies
npm install

# 2. Start development server
npm run dev
```

Open http://localhost:3000

**Note:** All component files are now in place. The `.env.local` file has been created with the default API URL.

## Project Structure

```
frontend/
├── app/
│   ├── layout.tsx              # Root layout
│   ├── page.tsx                # Home page
│   ├── providers.tsx           # React Query
│   ├── globals.css             # Tailwind
│   ├── register/
│   │   └── page.tsx           # Register forms
│   └── runs/
│       ├── new/page.tsx       # Create run
│       └── [id]/page.tsx      # Run detail
├── components/
│   ├── ui/                    # shadcn/ui
│   ├── YAMLPanel.tsx
│   ├── SchemaForm.tsx
│   ├── StateCard.tsx
│   ├── Timeline.tsx
│   └── FlowBadge.tsx
├── lib/
│   ├── api.ts                 # API client
│   ├── hooks.ts               # React Query
│   ├── types.ts               # TypeScript
│   └── utils.ts               # Utilities
└── package.json
```

## Available Scripts

- `npm run dev` - Start development server (port 3000)
- `npm run build` - Build for production
- `npm run start` - Start production server
- `npm run lint` - Lint code

## Environment Variables

Create `.env.local`:

```bash
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

## Usage

### 1. Register a Form

1. Go to http://localhost:3000/register
2. Click "Load Example" to see sample YAML
3. Click "Register & Preview"
4. See live form on right side

### 2. Create a Run

1. Click "Create Run →" or go to /runs/new
2. Fill the form with valid data
3. Click "Create Run"
4. Redirects to /runs/[id]

### 3. Advance Workflow

1. On run detail page, see current status
2. Click "Advance Workflow"
3. Watch state update in real-time

## Backend API

Expects these endpoints:

- `POST /register_forms`
- `POST /runs`
- `GET /runs/{id}`
- `POST /runs/{id}/advance`

## Development Notes

- Auto-polls running workflows every 2s
- LocalStorage saves last form/workflow
- Toast notifications for errors
- Form validation from JSON Schema

## Troubleshooting

**Components not found:**
Run the setup script or manually create component files.

**API errors:**

1. Check backend is running on port 8000
2. Verify `.env.local` has correct URL
3. Check browser console for CORS errors

**Monaco editor blank:**
Monaco loads async, try refreshing.

## Next Steps

After setup works:

1. Test with backend running
2. Try example forms
3. Create custom workflows
