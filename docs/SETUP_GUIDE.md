# Shifty - Setup & Development Guide

This guide explains how to set up the development environment for Shifty on Windows.

## 📋 Prerequisites

- **Python 3.14.6**
- **Node.js 26.5.0**
- **npm 11.17.0**
- **uv 0.11.29**
- **PostgreSQL 16+**
- **Memurai** (Native Redis for Windows)

## 🔧 Backend Setup

1. **Environment Variables**:
   Copy `.env.example` to the repository root `.env` and configure your database credentials.
   ```bash
   cp .env.example .env
   ```

2. **Docker-first startup**:
   Build and run the stack with Docker Compose. This is the primary path for local setup.
   ```bash
   docker compose up --build
   ```

3. **uv-first local backend workflow**:
   If you want to run the backend directly on the host, use `uv` from the `backend` directory.
   ```bash
   cd backend
   uv sync --frozen
   uv run python run_migrations.py
   uv run python main.py
   ```
   The API will be available at `http://localhost:8000`.

## 🎨 Frontend Setup

1. **Installation**:
   ```bash
   cd frontend
   npm ci
   ```

2. **Development Mode**:
   ```bash
   npm run dev
   ```
   The application will be available at `http://localhost:3000`.

   CI also keeps a temporary Node.js 24.18.0/npm 11.16.0 compatibility lane until Node.js 26 reaches LTS in October 2026.

## 🛠️ Common Commands

- **Run Tests**: `pytest` inside the `backend` folder.
- **Check Linting**: `npm run lint:strict` inside the `frontend` folder.
- **Build Frontend**: `npm run build`.

## ⚠️ Windows Specific Notes

- Always use `run_migrations.py` instead of `alembic upgrade head` to handle the `WinError 64` bug.
- Ensure Memurai service is running before starting the backend directly on Windows.
- Keep `.env` at the repository root so Docker and the `uv` workflow resolve the same configuration.
