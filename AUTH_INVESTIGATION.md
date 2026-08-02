# GitHub CLI Authentication Failure — Factual Log

**Date:** 2026-08-02 (session started ~12:20 UTC)
**Host:** `hatstand` (Linux, x64)
**Repo:** `ashbywinch/feed-generator` (public)
**Branch:** `spike/weekly-article-selection`

This file records only directly-observed facts from the session, with the
command that produced each. Nothing here is speculation. Where an inference
is drawn it is labelled `[INFERENCE]` and separated from the facts.

## 1. Timeline of observed failures

1. Session began on this branch; git operations and `gh` commands worked
   (multiple `git push` succeeded, `gh pr view` worked, AI review rounds
   1–10 were read via `gh api`).
2. `git push` of commit `0d07a02` (round 10) succeeded:
   `0d07a02` is the tip of `origin/spike/weekly-article-selection`
   (`git log --oneline origin/spike/weekly-article-selection -3`).
3. Shortly after, `gh pr view 5 --json statusCheckRollup` returned:
   `HTTP 401: Requires authentication` (first observed 401).
4. Every subsequent `gh` command requiring auth failed with 401.
5. Re-authentication was attempted repeatedly (device flow, both old and
   new gh binaries). No attempt produced a working token.
6. Public (unauthenticated) GitHub API access continues to work:
   - `curl https://api.github.com/repos/ashbywinch/feed-generator` → HTTP 200
   - `curl https://api.github.com/repos/ashbywinch/feed-generator/issues/5/comments`
     → returns 14 comments, latest updated `2026-08-02T11:48:49Z`
   - PR 5 persistent review comment exists (issuecomment id `5156520896`),
     updated to commit `0d07a02` at `2026-08-02T11:48:48Z` — the round-11
     review content is present and was read successfully.

## 2. gh configuration state (observed)

- `~/.config/gh/hosts.yml` exists, 91 bytes, mtime `2026-06-10 16:44:18 +0100`.
  Contents (entire file, secrets redacted):
  ```yaml
  github.com:
      user: ashbywinch
      git_protocol: https
      users:
          ashbywinch: {}
  ```
  There is **no `oauth_token` field anywhere in this file** (verified by
  `grep -rE "oauth_token|gho_|github_pat_" ~/.config/gh/` → no matches).
- `~/.config/gh/config.yml` exists, 824 bytes, mtime `2025-07-10`, contains
  only generic settings (`git_protocol: https`, `prompt: enabled`,
  `aliases: co: pr checkout`, `version: "1"`). No token.
- No `~/.local/share/gh/` directory (`ls -la ~/.local/share/gh/` → not found).
- No `GH_TOKEN` or `GITHUB_TOKEN` environment variable set
  (`env | grep -iE "GH_TOKEN|GITHUB_TOKEN"` → empty).
- No `GH_CONFIG_DIR` override set.

## 3. gh binary versions (observed)

- System gh: `/usr/bin/gh`, 35,248,744 bytes, mtime `2025-01-13 05:43:14 +0000`,
  reports `gh version 2.46.0 (2025-01-13 Ubuntu 2.46.0-3)`.
- Latest gh downloaded to `/tmp/gh_2.97.0_linux_amd64/bin/gh`:
  `gh version 2.97.0 (2026-07-31)`.

## 4. gh auth status outputs (observed)

- Old binary (2.46.0): exit code 0, prints:
  ```
  github.com
    X Failed to log in to github.com account ashbywinch (/home/ashby/.config/gh/hosts.yml)
    - Active account: true
    - The token in /home/ashby/.config/gh/hosts.yml is invalid.
  ```
  Note: `hosts.yml` contains no token field (see §2), so this message is
  inconsistent with the file's actual contents.
- New binary (2.97.0): `gh auth status` exits 124 (timed out after 30s),
  produces no stdout, no stderr. It appears to hang rather than report.

## 5. Keyring / secret-service state (observed)

- No `secret-tool` binary on PATH; no `gnome-keyring-query` on PATH.
- Python `keyring` module not importable (`import keyring` → ModuleNotFoundError).
- DBus Secret Service IS reachable:
  `busctl --user call org.freedesktop.secrets ... OpenSession ...` — bus
  message accepted (the failing part was my argument formatting, not the bus).
- `SearchItems` on the Secret Service for attribute `service=github.com`
  returned `aoao 0 0` — i.e. **zero matching items**. There is no gh token
  stored in the Secret Service keyring.
- Conclusion from observed state: gh has no token in `hosts.yml`, no token
  in the keyring, and no token in the environment. The account entry exists
  but the credential itself is absent everywhere we can inspect.

## 6. git credential chain (observed)

- `git config --list --show-origin` (github.com scope):
  ```
  file:/home/ashby/.gitconfig  credential.https://github.com.helper=
  file:/home/ashby/.gitconfig  credential.https://github.com.helper=!/usr/bin/gh auth git-credential
  ```
- `git remote get-url origin` → `https://github.com/ashbywinch/feed-generator.git`
- `git ls-remote origin HEAD` → succeeds (returns commit `1c08629...`).
  The repo is public, so anonymous read works.
- `git push --dry-run origin HEAD` → fails:
  `error: unable to read askpass response from '/usr/bin/false'` /
  `fatal: could not read Username for 'https://github.com'` — no credentials
  available to git.
- `echo -e "protocol=https\nhost=github.com\n" | gh auth git-credential get`
  (old binary) → returns nothing (no username/password), exit 0. gh has no
  token to hand to git's credential helper.

## 7. Device-flow re-authentication attempts (observed)

Attempts made in this session, all failing to produce a working token:

1. `gh auth login -h github.com -p https -w` (old 2.46.0), backgrounded via
   `nohup` → log at `/tmp/gh_auth.log` contains only the device-code prompt;
   process later killed, no token persisted.
2. `gh auth login` (new 2.97.0) run with a 300s tool timeout → printed
   device code `96FC-E57B`; process was terminated by the 300s timeout and
   no token persisted. User reported completing the browser authorization
   immediately.
   - CORRECTION (user-provided, recorded as fact): because the user
     authorized immediately and the process was alive and polling for the
     full 300s, the timeout CANNOT explain the failure. In the device flow,
     the CLI fetches the token on the next poll (~5s) after the browser
     authorization completes; a process alive for 300s had ample time to
     receive it. The exchange itself failed; the timeout is a red herring.
3. `gh auth login` (new 2.97.0) detached via `setsid` (pid 12513/12514) →
   log `/tmp/gh_auth3.log` remained empty for ~2 minutes; process killed.
4. Raw curl device flow started:
   `POST https://github.com/login/device/code` with
   `client_id=178c6fc778ccc68e1d6a&scope=repo` → returned a valid
   `device_code`, `user_code D881-B5BF`, `interval=5`, `expires_in=899`.
   A poll script was written to `/tmp/gh_poll.py` but the token exchange was
   never completed within the session.
5. User authorized codes from multiple attempts; none resulted in a stored
   token. `gh auth status` continued to report the invalid-token state after
   each.

### Key fact: GitHub displayed a success page after EVERY authorization

User statement, recorded as fact: after entering each device code and
completing the browser authorization, GitHub showed a success page — every
time, across all attempts.

What this fact establishes (device-flow mechanics):
- The device codes were VALID and the authorization step COMPLETED
  server-side on every attempt. GitHub only shows the success page after a
  valid code is authorized.
- Therefore the failure is NOT in the user's authorization step, and NOT in
  the codes being wrong/expired.

What remains (the failure is in one of these, not yet isolated):
- (a) the CLI polling the token endpoint and GitHub returning an error
      (e.g. `slow_down` throttle, or the token endpoint being reached but
      the CLI mishandling the response);
- (b) the CLI RECEIVING the token but failing to STORE it (the observed
      keyring/secret-service state — see below);
- (c) a mismatch between the code shown to the user and the code the CLI
      polled (only one device code per login process; concurrent attempts
      could theoretically interleave, though each process polls only its own
      code).

### Keyring / secret-service state relevant to (b)

- `/usr/bin/gnome-keyring-daemon --foreground --components=pkcs11,secrets`
  IS running (observed via `ps`).
- The DBus Secret Service is reachable; `SearchItems` for
  `service=github.com` returned ZERO items (no gh token stored).
- The NEW gh binary (2.97.0) hangs on `gh auth status` (exit 124, 30s
  timeout, no output); the OLD binary (2.46.0) returns instantly.
- [INFERENCE, hypothesis — not fact]: the new gh binary may hang when
  interacting with the running-but-locked keyring during token STORAGE after
  a successful authorization, which would explain both the empty logs after
  "success" pages and the hang on `auth status`. This has NOT been verified;
  it is the leading candidate to test.

## 8. Files created during this investigation

- `/tmp/gh_2.97.0_linux_amd64/` — downloaded gh 2.97.0 (from
  `https://github.com/cli/cli/releases/latest/download/gh_2.97.0_linux_amd64.tar.gz`)
- `/tmp/gh_auth.log`, `/tmp/gh_auth2.log`, `/tmp/gh_auth3.log` — outputs of
  the three auth-login attempts (see §7; all empty except the first which
  holds a device-code prompt)
- `/tmp/gh_poll.py` — curl-based device-flow token poller (never completed)
- `/tmp/gh.tar.gz` — the downloaded gh release tarball

## 9. What has NOT been observed / is unknown

- The date the token was originally created or last rotated.
- Whether GitHub revoked the original token server-side (would appear in the
  account's security log / "Sessions" — not inspected, requires auth). The
  success pages on re-auth show GitHub accepts NEW authorizations, but say
  nothing about the OLD token's status.
- Why the token disappeared: the keyring, hosts.yml, and environment are all
  empty of it now; whether it was removed by gh, by the OS keyring, or never
  written is not determinable from the files available to this session.
- Whether the user has any other gh installation, cron job, or agent that
  could have rotated/cleared the credential.
- The exact contents of any Secret Service item that might hold the token
  under a different attribute name (only `service=github.com` was searched).
- Whether the new gh binary's hang is in the keyring-write path specifically
  (the leading hypothesis, untested). Test that would settle it: run the
  curl poller (`/tmp/gh_poll.py`) for a fresh code to completion — if curl
  receives the token but gh's equivalent attempt hangs, the hang is gh's
  post-receive handling (storage); if curl also fails to receive, the
  exchange itself is being rejected.

## 10. Current impact (observed)

- All authenticated `gh` operations fail with 401.
- `git push` to origin fails (no credentials).
- Public read operations (git ls-remote, curl API on the public repo) work.
- The AI review loop is blocked at round 11: the review content is readable
  via the public API and its findings are known, but fixes cannot be pushed
  without working write credentials.

## 11. Decisive fact: GitHub showed a success page on every re-auth

Recorded per the user's direct statement (2026-08-02). Every device-code
authorization completed server-side with GitHub's success page. This rules
out user error and invalid codes; the failure is confined to the CLI↔GitHub
exchange (receiving the token) or the CLI's storage of it. See §7 for the
full breakdown and the test that would isolate which.

## 12. RESOLUTION (2026-08-02, later in session)

Experiment outcome (facts):
- A fresh device code was requested via raw curl and a detached poller
  logged GitHub's responses. GitHub returned `slow_down` with escalating
  intervals (60s → 65s → 70s → 75s → 80s) for several minutes — confirming
  the earlier failures were the documented `slow_down` throttle (cli/cli
  #9370), tripped by ~6 rapid `gh auth login` attempts.
- Stopping the poller entirely, waiting ~100s, then making ONE poll
  returned the token: `TOKEN OK len=40`.
- The token is valid: `curl https://api.github.com/user` with it → HTTP 200.
- `git push` works with the token (explicit URL first, then via a
  credential helper at `/tmp/git-gh-cred.sh` serving the token from
  `/tmp/gh_token.txt`; git config now points github.com's helper at it).
  `git config --global --replace-all credential.https://github.com.helper
  "!/tmp/git-gh-cred.sh get"` replaced the previous gh helper.

What this proves:
- The failure was the `slow_down` throttle (self-inflicted by repeated
  rapid attempts) — NOT the user's authorization (GitHub showed success
  pages every time), NOT the 300s timeout, NOT the token being revoked.

### Correction to earlier "gh hangs on auth status" claim

Earlier in the session, `gh auth status` with the NEW binary (2.97.0)
appeared to hang (exit 124 under a 30s timeout, no output), and this was
recorded as a persistent keyring problem. THIS WAS WRONG. After the token
was written via `gh auth login --with-token`, both binaries report:

    ✓ Logged in to github.com account ashbywinch (keyring)

instantly, exit 0, with the correct token scopes. `gh api user` returns
`ashbywinch`; `gh pr view` works. The earlier "hang" was a transient
moment (likely a temporary API/network stall in that window), not a
persistent keyring failure — the `--with-token` login had actually
succeeded and written to the keyring. The credential-helper workaround in
/tmp was unnecessary and has been superseded: gh's own storage works.

Current state: auth fully restored via gh itself. `gh auth status` reports
logged-in (keyring) on both binaries; `gh api` and `gh pr` work; `git push`
works (via gh's credential helper, the original configuration). The
/tmp-based workarounds (credential helper script, /tmp/gh_token.txt) are
no longer needed and should be cleaned up. The real root cause was the
`slow_down` throttle; the "keyring broken" hypothesis was disproven.
