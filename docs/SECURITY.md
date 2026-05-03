# Security

## Scope

This project is designed for local-only use on a single machine.

- The HTTP server binds to `127.0.0.1`.
- There is no authentication layer.
- The repository should not be deployed on a public host or exposed through port forwarding.

## Built-in guardrails

- Input validation before any state write.
- Request rate limiting on `POST /api/state`.
- Request body size limit on the local API.
- Directory listing disabled on the embedded HTTP server.

## Reporting

If you find a vulnerability:

- do not publish secrets, tokens, or private machine details in a public issue;
- open an issue with clear reproduction steps and the affected version or commit.
