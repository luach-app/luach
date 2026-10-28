# Security

luach holds a family's calendar, their conversations with the agent and, if they connect it,
read access to their Gmail. Reports that help keep that safe are welcome.

## Reporting a vulnerability

Report privately through GitHub's private vulnerability reporting: open the repository's
**Security** tab and choose **Report a vulnerability**. Please do not open a public issue,
discussion or pull request for a vulnerability until a fix is released.

Include:

- what an attacker can do, and what they need first (an account, a member's session, the
  service key, network access to the server, nothing);
- the steps to reproduce it, or a proof of concept, against a version or commit you name;
- the settings that matter (for example the calendar backend, single sign-on, or a reverse
  proxy in front);
- anything you know about a fix.

You will get an acknowledgement, a fix developed in a private advisory where you can follow
it, and credit in the advisory unless you would rather not have it.

## Scope

In scope: the code in this repository.

- the server (`src/luach`): authentication, sessions, passkeys and single sign-on; the
  admission gate and the audit trail; the email door and the Gmail connection; the booking
  pages and the wall board's pairing; anything that lets the model or text it reads act
  outside what the gate allows;
- the web app (`web/`);
- the iPhone app (`ios/`);
- the container image, and `docker-compose.yml` with the compose files, `Caddyfile` and
  SearXNG settings beside it, as shipped.

Out of scope: a family's own deployment. Each household runs its own server, and its
configuration, host, reverse proxy, model provider, credentials and data are theirs; nobody
else hosts luach. If you find a problem with someone's server, tell them. Also out of scope:
vulnerabilities in third-party services and dependencies themselves (report those upstream),
and findings that need an already-compromised host or owner account.

## Supported versions

Fixes go into `main` and the next release. Run a current version.
