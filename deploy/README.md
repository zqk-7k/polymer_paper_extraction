# Production deployment

Repository ownership and upstream synchronization are documented in [REPOSITORY_WORKFLOW.md](REPOSITORY_WORKFLOW.md).

The complete manual-sync, CI, data-publication, and server-release process is documented in [AUTOMATION_FLOW.md](AUTOMATION_FLOW.md).

The public pilot runs as three containers: frontend, FastAPI/pipeline, and a Caddy gateway on host port 18120. PoLyInfo data and web task outputs are mounted from the host and are not stored in container layers.

Static demo results and source PDFs are also mounted from `/srv/polymerlit/data`. They are excluded from release archives so ordinary code deployments do not repeatedly transfer unchanged research files.

Required GitHub production environment secrets:

- `DEPLOY_HOST`
- `DEPLOY_USER`
- `DEPLOY_SSH_KEY`

The extraction API accepts DMX and MinerU credentials with each multipart upload. They are passed only to the task subprocess environment and are not persisted in task records or candidate output.

The production endpoint uses a publicly trusted, short-lived Let's Encrypt IP certificate at `https://122.51.104.121:18120`. A domain is optional. The certificate is checked twice daily and renewed automatically; the API continues to reject credential submission over plain HTTP.

After tests and container build checks pass, GitHub Actions sends a small incremental Git bundle from the deployed revision to the exact tested commit. The server verifies those Git objects, generates the release archive locally, unpacks it under `/srv/polymerlit/releases/<sha>`, and exposes it through `/srv/polymerlit/current`.
