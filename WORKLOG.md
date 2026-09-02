# Worklog

## 2026-09-02 — Public-release privacy scrub

- Replaced user-specific absolute filesystem paths in documentation and tests with portable examples.
- Audited the tracked tree and complete Git history for personal email addresses, local account names, hostnames, IP addresses, credentials, private keys, and stored memory content.
- Rewrote commit author and committer metadata to use the repository owner's GitHub private noreply identity before public release.
- Verified the resulting tree with the full test suite and a second current-tree and full-history privacy scan.

### Attribution correction

- Corrected the initial generic noreply identity after GitHub mapped it to an unrelated account.
- Verified the rewritten commits resolve to the `JayefBuilds` GitHub account without exposing a personal email address.
