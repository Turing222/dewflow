# Bifrost Gateway

Dewflow calls Bifrost as an OpenAI-compatible LLM gateway:

```text
Dewflow api/worker -> Bifrost -> official model providers
```

## Start

Bifrost is included in `docker-compose.db.yml` under the `bifrost` profile.
Set these environment variables in your compose env file or shell:

```env
BIFROST_API_KEY=sk-bf-change-me
BIFROST_ENCRYPTION_KEY=change-me-to-a-long-random-passphrase
DEEPSEEK_API_KEY=sk-your-official-deepseek-key
```

Or use the automated command:

```bash
make set-llm PROVIDER=bifrost
```

Then start the stack with the bifrost profile:

```bash
docker compose --profile bifrost --env-file .env.smoke -f docker-compose.db.yml up -d
```

`LLM_PROVIDER` defaults to `bifrost` in the compose file when the profile is
active. To use a direct-connect provider instead, set `LLM_PROVIDER=deepseek`
(or `gemini`) in your env file — no bifrost profile needed.

## Configuration

`config.json` is the single source of truth. It is mounted read-only into
Bifrost's app directory, while the `bifrost_data` volume remains writable for
runtime data such as logs and the SQLite config store. The config enables the
Bifrost config store because Bifrost v1.4.11 requires it while initializing the
governance routes. The SQLite database is stored at `./config.db` relative to
Bifrost's app directory, which maps to the `bifrost_data` Docker volume.

Provider credentials are referenced with `env.*`; do not commit raw provider
keys. The first gateway profile uses DeepSeek through Bifrost's
OpenAI-compatible custom provider support.

## Key Ownership

Dewflow receives `BIFROST_API_KEY` as its OpenAI-compatible client key when
calling the gateway. Bifrost requires a virtual key on inference requests,
validates `BIFROST_API_KEY` as the `dewflow-platform` virtual key, and only
allows that key to use the `deepseek-chat` model through the DeepSeek provider.
Additional Bifrost authentication is disabled for inference traffic.
The key must start with `sk-bf-`; Bifrost v1.4.11 generates a replacement key
when a configured virtual key value does not use that prefix.

Official provider keys such as `DEEPSEEK_API_KEY` belong to Bifrost and should
not be used directly by Dewflow chat traffic in gateway mode.

## Logging And Privacy

The default config keeps request logging enabled but sets
`client.disable_content_logging=true`, blocks per-request content logging
overrides, and blocks raw request/response overrides. Recheck Bifrost release
notes before changing these settings because prompt and response content may
contain user data.
