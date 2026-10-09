"""Run the unit suite with isolated credentials and an ephemeral local database.

Usage: poetry run python scripts/run_unit_tests.py [-q] [pytest arguments ...]
Live integration testing continues to use `poetry run pytest -m integration`.
"""

import os
import sys


def main() -> int:
    os.environ.update(
        ENVIRONMENT="test",
        RISE_TEST_MODE="0",
        SUPABASE_JWT_SECRET="test-supabase-secret-rise-unit-tests",
        DATABASE_URL="sqlite:///:memory:",
        GITHUB_TOKEN="",
        GITHUB_APP_ID="",
        GITHUB_APP_PRIVATE_KEY="",
        GITHUB_READ_TOKEN="",
        GROQ_API_KEY="",
        GEMINI_API_KEY="",
        OPENAI_API_KEY="",
        SLACK_BOT_TOKEN="",
        SLACK_API_TOKEN="",
        QDRANT_API_KEY="",
        QDRANT_URL="http://127.0.0.1:1",
        RISE_AWS_LIVE="0",
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        OLLAMA_BASE_URL="http://127.0.0.1:1",
        OMP_NUM_THREADS="1",
        MKL_NUM_THREADS="1",
    )
    import pytest

    return pytest.main(sys.argv[1:] or ["-q"])


if __name__ == "__main__":
    raise SystemExit(main())
