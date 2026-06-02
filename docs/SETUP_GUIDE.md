# Shifty - Setup & Development Guide

This guide explains how to set up the development environment for Shifty on Windows.

## 📋 Prerequisites

- **Python 3.13+**
- **Node.js 18+**
- **PostgreSQL 16+**
- **Memurai** (Native Redis for Windows)

## 🔧 Backend Setup

1. **Environment Variables**:
   Copy `.env.example` to `backend/.env` and configure your database credentials.
   ```bash
   cp .env.example backend/.env
   ```

2. **Installation**:
   Create a virtual environment and install dependencies.
   ```bash
   python -m venv .venv
   source .venv/Scripts/activate
   pip install -r backend/requirements.txt
   ```

3. **Database Migrations**:
   Run the specific migration script for Windows to avoid asyncpg issues.
   ```bash
   python backend/run_migrations.py
   ```

4. **Running the Server**:
   ```bash
   cd backend
   python main.py
   ```
   The API will be available at `http://localhost:8000`.

## 🎨 Frontend Setup

1. **Installation**:
   ```bash
   cd frontend
   npm install
   ```

2. **Development Mode**:
   ```bash
   npm run dev
   ```
   The application will be available at `http://localhost:3000`.

## 🛠️ Common Commands

- **Run Tests**: `pytest` inside the `backend` folder.
- **Check Linting**: `npm run lint` inside the `frontend` folder.
- **Build Frontend**: `npm run build`.

## ⚠️ Windows Specific Notes

- Always use `run_migrations.py` instead of `alembic upgrade head` to handle the `WinError 64` bug.
- Ensure Memurai service is running before starting the backend.
