# Security and privacy

Fitvio is made for your home network. Your Garmin login and health data never leave your server, except for the requests to Garmin Connect (or Intervals.icu) that the app makes on your behalf. For the weather, [Open-Meteo](https://open-meteo.com) gets a rough position of each outdoor session (a point every 30 minutes, rounded to 0.1°, about 11 km) and its dates, with no account, key or anything about you. It can be switched off per person in the phone's Me screen.

## What stays on your server

Everything under `data/` and `config/users.json` is git-ignored and never built into the Docker image:

| What | Where | Protection |
|---|---|---|
| Garmin password | `data/garmindb/<id>/config/password.txt` | `chmod 600`, directory `700`. Only needed if the cached login tokens expire |
| Garmin login tokens | `data/garmindb/<id>/config/garmin_tokens.json` | `chmod 600` |
| Your health data | `data/garmindb/<id>/HealthData`, `data/app.db` | directory `700`, DB `600` |
| Who is connected | `config/users.json` | `chmod 600`. A real account is never written into `users.example.json` |

## How the web app is protected

- **Home network only.** Garmin logins and settings changes are only accepted from home-network addresses (10.x, 172.16–31.x, 192.168.x, IPv6 ULA and link-local, loopback). The dashboard speaks plain HTTP, so never forward port 8765 to the internet.
- **Docker listens on IPv4 only.** Docker hands IPv6 connections to the container through a proxy, which hides the real client behind a private address. So the published port is IPv4-only; set `FITVIO_BIND` in `.env` to your server's LAN IP to listen on the home network only. With rootless Docker every client looks local, so don't use it for Fitvio.
- **Bad data from a provider can't break the wall.** Numbers that aren't finite (e.g. an infinite speed in a crafted FIT file) are dropped on import, and workouts and downloads have size limits.
- **DNS rebinding.** The server only answers to IP addresses, `localhost`, bare LAN hostnames and local domains (`.local`, `.lan`, `.home`, `.fritz.box`, …). To use another hostname, set `FITVIO_ALLOWED_HOSTS=myname.example`.
- **Cross-site requests.** State-changing requests from another origin are refused, and non-JSON bodies are rejected.
- **Headers.** A strict Content-Security-Policy, `X-Frame-Options: DENY` (no clickjacking of the login form), `nosniff`, `no-referrer`, and `no-store` on API responses.
- **Input validation.** Lengths and formats are checked (email, password, MFA code, query ranges). Only one account can be connected at a time.
- **No password leaks.** The password is never logged or returned by the API, and the web page clears it from memory right after sending.
- **Updates are pulled, not pushed.** The optional updater only pulls the published image; no CI runner or remote command ever executes on your server.

Not protected, by design: anyone on your home network can *view* the dashboard. It's a wall display, with no user login.

## Reporting a vulnerability

Please report security issues privately via GitHub: *Security → Report a vulnerability* on this repository. Don't open a public issue for them.
