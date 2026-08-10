# Production deployment

Repository ownership and upstream synchronization are documented in [REPOSITORY_WORKFLOW.md](REPOSITORY_WORKFLOW.md).

The public pilot runs as three containers: frontend, FastAPI/pipeline, and a Caddy gateway on host port 18120. PoLyInfo data and web task outputs are mounted from the host and are not stored in container layers.

Static demo results and source PDFs are also mounted from `/srv/polymerlit/data`. They are excluded from release archives so ordinary code deployments do not repeatedly transfer unchanged research files.

Required GitHub production environment secrets:

- `DEPLOY_HOST`
- `DEPLOY_USER`
- `DEPLOY_SSH_KEY`

The extraction API accepts DMX and MinerU credentials with each multipart upload. They are passed only to the task subprocess environment and are not persisted in task records or candidate output.

The default production configuration rejects credential submission over plain HTTP. The IP-and-port pilot can be used to inspect existing results, but a domain with HTTPS is required before public extraction uploads are enabled.

After tests and container build checks pass, GitHub Actions sends an archive of the exact tested commit to the server. The release is unpacked under `/srv/polymerlit/releases/<sha>` and exposed through `/srv/polymerlit/current`; the server does not need to clone the full Git history.
