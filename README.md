<h1 align="center">Clark</h1>

<p align="center">
  <strong>An all-in-one Discord bot for moderation, onboarding, engagement, and support — with an AI chatbot built in.</strong>
</p>

<p align="center">
  <a href="https://github.com/usekiko/Clark-open-sourced">Source</a> · Built with discord.py + PostgreSQL
</p>

<!-- TODO: Add a hero banner or screenshot -->
<!-- <p align="center"><img src="assets/banner.png" alt="Clark" width="800" /></p> -->

---

## What is Clark?

Clark is a general-purpose Discord bot that handles the things most servers need from a fleet of separate bots — moderation, welcome messages, verification, leveling, tickets, and self-roles — in one place. It runs as an `AutoShardedBot`, so it's built to scale across many servers, and stores per-guild configuration in a PostgreSQL database.

Every feature is a self-contained cog that loads at startup, and commands are exposed as Discord slash commands. Clark also ships an AI chatbot (powered by Groq) with switchable personalities, so members can talk to the bot directly in chat.

This is the open-sourced code of Clark, released under the AGPL-3.0 license.

## Features

- **AI Chatbot** — Groq-powered conversational AI with three switchable personalities (friendly, rude, strict) and per-server custom instructions.
- **Moderation** — Standard moderation commands (ban, kick, timeout, purge, and more) backed by persistent case tracking.
- **AutoMod** — Automated rule enforcement for spam, banned words, and unwanted content.
- **Logging** — Detailed event logging for messages, members, moderation actions, and server changes.
- **Verification** — Gate new members behind a verification step before they can access the server.
- **Welcomer & Goodbyer** — Customizable join and leave messages, with image support via Pillow.
- **Leveling** — XP and level progression to reward active members.
- **Self-Roles** — Button- and menu-based self-assignable roles.
- **Tickets** — A full support-ticket system with panels, claims, and transcripts.
- **Forms** — Build and collect structured submissions from members.
- **Introductions** — Guided introduction prompts for new members.
- **Reminders** — Personal reminders that fire back in Discord.
- **Analytics** — Server activity and growth metrics.
- **Fun Commands** — Jokes, facts, memes, roasts, and more from bundled content packs.
- **Customization** — Rebrand Clark's replies, embeds, and behavior per server.
- **Help Menu** — Interactive, category-based slash-command help.

> Note: the economy module (`cogs/economy-underwork.py`) is a work in progress and not production-ready.

## Tech Stack

- **Language:** [Python](https://www.python.org/) 3.14
- **Framework:** [discord.py](https://discordpy.readthedocs.io/) 2.6
- **Database:** [PostgreSQL](https://www.postgresql.org/) via [asyncpg](https://magicstack.github.io/asyncpg/) (connection pool)
- **AI:** [Groq](https://groq.com/) (`groq` async client)
- **Media:** [Pillow](https://python-pillow.org/), [yt-dlp](https://github.com/yt-dlp/yt-dlp), and FFmpeg for image/voice features
- **Deployment:** [Docker](https://www.docker.com/) (Python 3.14 slim, runs as non-root)

## Getting Started

You'll need Python 3.14+, a running PostgreSQL database, a [Discord bot token](https://discord.com/developers/applications), and a [Groq API key](https://console.groq.com/keys).

```bash
# Clone the repo
git clone https://github.com/usekiko/Clark-open-sourced.git
cd Clark-open-sourced

# Create a virtual environment and install dependencies
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Create your .env file (see the Configuration section below)
cp .env.example .env             # Windows: copy .env.example .env

# Run the bot
python clark.py
```

On startup Clark connects to the database, loads every cog in `./cogs`, and syncs its slash commands globally. Global command sync can take up to an hour to propagate the first time — this is a Discord limitation, not a bug.

> FFmpeg must be installed and on your `PATH` for voice and `yt-dlp` features to work. On the Discord Developer Portal, enable the **Server Members**, **Message Content**, and **Presence** privileged intents for your bot.

## Configuration

Clark is configured entirely through environment variables. Create a `.env` file in the project root with the following values:

- **`DISCORD_TOKEN`** — Your bot token from the [Discord Developer Portal](https://discord.com/developers/applications) → your app → **Bot** → **Reset Token**.
- **`GROQ_API_KEY`** — API key for the AI chatbot, from the [Groq Console](https://console.groq.com/keys).
- **`PG_HOST`** — PostgreSQL host (defaults to `localhost`).
- **`PG_PORT`** — PostgreSQL port (defaults to `5432`).
- **`PG_USER`** — PostgreSQL username.
- **`PG_PASSWORD`** — PostgreSQL password.
- **`PG_DATABASE`** — Name of the database Clark should use.

Each cog creates its own tables on first run, so you only need to provide an empty, reachable database — no manual schema setup required.

## Running with Docker

A `Dockerfile` is included. It installs FFmpeg and the native libraries the bot needs, then runs as a non-root user.

```bash
# Build the image
docker build -t clark .

# Run it, mounting your .env read-only
docker run --env-file .env clark
```

Point `PG_HOST` at a database reachable from inside the container (for example a linked Postgres container or your host's address rather than `localhost`).

## Project Structure

```
clark.py        # Entry point: bot setup, DB pool, cog loading, command sync
cogs/           # Feature modules (moderation, tickets, AI, leveling, ...)
utils/          # Shared helpers (colors, logging, reusable views)
json/           # Content packs for fun commands (jokes, facts, memes, roasts)
Dockerfile      # Container build
requirements.txt
```

## License

[AGPL-3.0](LICENSE) — You're free to use, study, and modify Clark, but any public deployment (including running it as a hosted service) must make the corresponding source code available under the same license.

---

<p align="center">
  Built by <a href="https://github.com/usekiko">@usekiko</a>
</p>
