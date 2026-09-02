# Security Policy

## Supported Versions

| Version | Supported |
| ------- | --------- |
| 0.1.x   | ✅        |

## Reporting a Vulnerability

Please **do not** open a public issue for security vulnerabilities.

Instead, email **dev@yuanxu.tech** with:

- A description of the vulnerability and its impact
- Steps to reproduce
- Any suggested mitigation

We aim to acknowledge reports within 72 hours and provide a fix or mitigation
plan within 14 days for confirmed issues.

## Scope notes

- The FastAPI server (`yaf_api/`) currently ships **without authentication**
  and is intended for local development only. Do not expose it to the public
  internet — multi-user auth is on the roadmap (`docs/next-steps.md`, Phase D3).
- Solver adapters execute external binaries (`nec2c`, openEMS) via subprocess
  with user-supplied geometry. Treat untrusted design files accordingly.
