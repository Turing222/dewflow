# Smoke Environment Secrets

This directory contains auto-generated and user-configured secrets for the local compose (`smoke`) environment.

## ⚠️ Security Notice
- **NEVER** commit any files in this directory except for this `README.md` and `.gitkeep`.
- All `.txt` files containing actual API keys or passwords are automatically ignored by Git.

## How to Set API Keys

Do not manually edit files in this directory. Use the provided automated command to securely set your API keys without exposing them to your shell history:

```bash
# Example: Testing with Gemini
make set-llm PROVIDER=gemini

# Example: Testing with OpenAI
make set-llm PROVIDER=openai

# Example: Fallback to Mock
make set-llm PROVIDER=mock
```

The script will prompt you for the key, save it atomically to `secrets/smoke/<provider>_api_key.txt` with `600` permissions, and automatically update your `.env.smoke` configuration.
