# Worklog

## 2026-09-02 — Public-release privacy scrub

- Replaced user-specific absolute filesystem paths in documentation and tests with portable examples.
- Audited the tracked tree and complete Git history for personal email addresses, local account names, hostnames, IP addresses, credentials, private keys, and stored memory content.
- Rewrote commit author and committer metadata to use a generic contributor identity before public release.
- Verified the resulting tree with the full test suite and a second current-tree and full-history privacy scan.
