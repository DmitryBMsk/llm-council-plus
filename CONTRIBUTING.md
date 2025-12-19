# Contributing to LLM Council

Thank you for your interest in contributing to LLM Council! This document provides guidelines for contributing.

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/YOUR_USERNAME/llm-council.git`
3. Create a feature branch: `git checkout -b feature/your-feature-name`

## Development Setup

### Prerequisites

- Docker and Docker Compose
- Node.js 18+ (for frontend development)
- Python 3.10+ (for backend development)
- [uv](https://docs.astral.sh/uv/) (recommended for Python deps)

### Running Locally

1. Copy the environment template:
   ```bash
   cp .env.example .env
   ```

2. Configure your `.env` file with API keys and settings

3. Start the services:
   ```bash
   docker compose up --build
   ```

4. Access the application:
   - Frontend: http://localhost
   - Backend API: http://localhost:8001

### Development Without Docker

**Backend:**
```bash
uv sync
uv run python -m backend.main
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

### Tests and Lint

**Backend tests:**
```bash
uv run pytest backend/tests
```

**Frontend lint:**
```bash
cd frontend
npm run lint
```

## Code Style

### Python (Backend)
- Follow PEP 8 guidelines
- Use type hints for function parameters and return values
- Write docstrings for public functions and classes

### JavaScript/React (Frontend)
- Use functional components with hooks
- Follow React best practices for state management
- Use descriptive variable and function names

## Pull Request Process

1. Ensure your code follows the project's style guidelines
2. Update documentation if you're adding new features
3. Test your changes locally
4. Create a pull request with a clear description of changes
5. Link any related issues

## Reporting Issues

When reporting issues, please include:
- A clear description of the problem
- Steps to reproduce the issue
- Expected vs actual behavior
- Environment details (OS, browser, etc.)

## Security

If you discover a security vulnerability, please do NOT open a public issue. Instead, email the maintainers directly.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
