"""Agents (claudecodeui) native Python backend.

This package replaces the external Node service that used to run on :3002.
It reimplements the claudecodeui backend contract as ops-native FastAPI,
mounted under ``/api/agents`` and sharing ops' cookie auth (``ivyea_ops_session``).

Layout:
  db.py        SQLite connection + schema (projects/sessions metadata index
               over Claude's native JSONL transcripts).
  router.py    Aggregates the REST sub-routers and the WebSocket endpoints,
               exposing a single ``router`` for main.py to mount.
  routers/     One module per domain (auth shim, projects, sessions, files,
               git, taskmaster, user, ...).
"""
