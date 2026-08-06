# AI Order Supervisor Frontend

Production-style Next.js 15 App Router frontend for the AI Order Supervisor backend.

## Stack

- Next.js 15 App Router
- TypeScript
- Tailwind CSS
- shadcn/ui-style primitives
- TanStack Query
- React Hook Form
- Zod

## Folder Structure

```text
app/
  page.tsx
  runs/[id]/page.tsx
  runs/new/page.tsx
  supervisors/page.tsx
components/
  layout/
  providers.tsx
  runs/
  supervisors/
  ui/
hooks/
lib/
types/
```

## Environment

Create `.env.local`:

```bash
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

## Install

```bash
cd /Users/anishagupta/Desktop/backend/order-supervisor-frontend
npm install
```

## Run Locally

```bash
npm run dev
```

Open:

```text
http://localhost:3000
```

## Build

```bash
npm run build
```

## Pages

- `/` dashboard with run search, filters, status badges, and next wake times
- `/runs/new` create run form
- `/runs/[id]` live run state, memory summary, timeline, and actions panel
- `/supervisors` supervisor list plus create/edit-draft form

Note: the backend currently exposes create/list/get supervisor endpoints but no update endpoint, so editing a supervisor creates a revised template.
