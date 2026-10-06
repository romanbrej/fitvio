# Security and privacy

The Health Wall is made for your home network. Your Garmin login and health data never leave your server, except for the requests to Garmin Connect that GarminDB and the app make on your behalf.

## What stays on your server

Everything under `data/` and `config/users.json` is git-ignored and never built into the Docker image:

| What | Where | Protection |
|---|---|---|
| Garmin password | `data/garmindb/<id>/config/password.txt` | `chmod 600`, directory `700`. Only needed if the cached login tokens expire |
| Garmin login tokens | `data/garmindb/<id>/config/garmin_tokens.json` | `chmod 600` |
| Your health data | `data/garmindb/<id>/HealthData`, `data/app.db` | directory `700`, DB `600` |
| Who is connected | `config/users.json` | `chmod 600`. A real account is never written into `users.example.json` |

## How the web app is protected

- **Home network only.** Garmin logins and settings changes are only accepted from private or loopback addresses. The dashboard speaks plain HTTP, so never forward port 8765 to the internet.
- **DNS rebinding.** The server only answers to IP addresses, `localhost`, bare LAN hostnames and local domains (`.local`, `.lan`, `.home`, `.fritz.box`, …). To use another hostname, set `HEALTHDASH_ALLOWED_HOSTS=myname.example`.
- **Cross-site requests.** State-changing requests from another origin are refused, and non-JSON bodies are rejected.
- **Headers.** A strict Content-Security-Policy, `X-Frame-Options: DENY` (no clickjacking of the login form), `nosniff`, `no-referrer`, and `no-store` on API responses.
- **Input validation.** Lengths and formats are checked (email, password, MFA code, query ranges). Only one account can be connected at a time.
- **No password leaks.** The password is never logged or returned by the API, and the web page clears it from memory right after sending.
- **Updates are pulled, not pushed.** The optional updater only pulls the published image; no CI runner or remote command ever executes on your server.

Not protected, by design: anyone on your home network can *view* the dashboard. It's a wall display, with no user login.

## Reporting a vulnerability

Please report security issues privately via GitHub: *Security → Report a vulnerability* on this repository. Don't open a public issue for them.
