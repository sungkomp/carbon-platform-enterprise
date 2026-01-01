# Using the demo flow from ChatGPT

When you want ChatGPT to see what the application does without running the web
UI, use the SQLite demo workflow helper. The script seeds the default org/admin
and executes the emission-factor/activity/run flow, then prints a ChatGPT-ready
summary plus raw JSON you can paste back into the conversation.

## Quick start
```bash
# from repo root
PYTHONPATH=backend python backend/scripts/chatgpt_demo.py
```

The output has two sections:
- **ChatGPT summary** – compact, human-friendly lines with the DB path, emission
  factor, activity, run totals, and dashboard counts.
- **Raw payloads/responses** – JSON suitable for quoting or copying into a
  ChatGPT reply when asked for evidence or example payloads.

If you also want to expose the API for a browser, run the seeded server in a
second terminal:
```bash
PYTHONPATH=backend python backend/scripts/serve_demo_app.py
```
Then point the frontend (Vite) at `http://127.0.0.1:8000` with org header
`X-Org-Slug: kmutt`.
