# WolfPack Analyst Console

Minimal React + TypeScript + Vite frontend for the WolfPack SOC multi-agent system.

## Getting Started

```bash
cd console
npm install
npm run dev
```

The dev server starts on `http://localhost:3000` and proxies API calls to the FastAPI backend at `http://localhost:8000`.

## Environment Variables

Create a `.env` file inside `console/`:

```env
VITE_API_TOKEN=dev-token-do-not-use-in-production
```

## Build for Production

```bash
npm run build
```

The output is written to `console/dist/` which can be served by FastAPI as static files.
