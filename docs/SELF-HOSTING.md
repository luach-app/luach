# Running luach for your household

This guide takes you from nothing to a luach your whole family uses: on a computer you
control, at an address of your own, over HTTPS, with the web app, the iPhone app and a
kitchen screen. It assumes you have never run a server before. Every command is meant to be
copied as it is; where you must put in something of your own, it says so.

Plan on an hour or two for the first six steps. The optional ones (a Google calendar, Gmail,
outgoing mail, voice, web search and the rest) can each be added later, one at a time.

Commands are typed in a terminal on the machine that runs luach (over SSH if it is a server
somewhere else), inside the `luach` folder you will make in step 2. Every setting is a line
in the `.env` file in that folder; [.env.example](../.env.example) lists them all with their
defaults, and `src/luach/config.py` is where luach reads them.

- [What you need, and what it costs](#what-you-need-and-what-it-costs)
- [Step 1: install Docker](#step-1-install-docker)
- [Step 2: get luach](#step-2-get-luach)
- [Step 3: a model](#step-3-a-model)
- [Step 4: start it](#step-4-start-it)
- [Step 5: HTTPS and a reverse proxy](#step-5-https-and-a-reverse-proxy)
- [Step 6: invite the family](#step-6-invite-the-family)
- Optional: [the calendar](#the-calendar-luachs-own-or-google) ·
  [Gmail](#gmail) · [outgoing mail](#outgoing-mail) · [single sign-on](#single-sign-on-oidc) ·
  [voice](#voice) · [web search](#web-search) · [push](#push-notifications) ·
  [About and Privacy pages](#the-about-and-privacy-pages) ·
  [booking links and Zoom](#booking-links-and-zoom) · [more about models](#more-about-models) ·
  [memory](#memory)
- [Living with it](#living-with-it): backups, upgrades, monitoring, security
- [Troubleshooting](#troubleshooting)
- [Without Docker Compose](#without-docker-compose)

## What you need, and what it costs

### A computer that stays on

luach is a small web server and a database. It needs a machine that is on all the time and
that runs Docker. Any of these works:

| | good for | what to know |
|---|---|---|
| **A small home server or mini PC** (an Intel NUC or similar, an old laptop) | most families | the electricity, and opening two ports on your router (step 5) |
| **A NAS that runs Docker** (Synology with Container Manager, QNAP with Container Station) | a family that already has one | the NAS's own web pages usually hold ports 80 and 443 (step 5 says what to do) |
| **A cloud VPS** (any provider's smallest Linux server) | no hardware at home, no router to configure | about 5–10 US dollars a month |

What it uses, measured: luach about 300 MB of memory, its database about 50 MB, Caddy (the
HTTPS front door) and SearXNG (web search) a little more. So:

- **Memory:** 2 GB is enough; 4 GB leaves room. (A local model needs far more: see below.)
- **Disk:** about 3 GB for the images, then very little: a family's calendar, conversations
  and memory are megabytes. 20 GB is plenty, and leaves room for backups.
- **Processor:** any 64-bit machine: **x86** (also called amd64 or x86-64) or **ARM** (arm64
  or aarch64: a Raspberry Pi 4 or 5 with the 64-bit Raspberry Pi OS, a Mac with Apple silicon,
  many NASes). The published image is built for both, and Docker pulls the one that fits.
  32-bit ARM (an older Raspberry Pi OS, armv7) is not supported.

### A domain name

The iPhone app, passkeys, push notifications and Google sign-in all need luach at an
`https://` address with a real certificate. So you need a name, such as `calendar.` in front
of a domain of yours. This guide writes `calendar.example.com`: put your own name wherever it
appears. If you own a domain, a subdomain of it is free. If not, a domain costs about 10–20 US
dollars a year from any registrar. You only need to be able to add a DNS record to it. Step 5
does the rest.

You can try luach on the machine itself, at `http://localhost:8004`, without a domain.

### An AI model

luach brings no model of its own. It talks to any server that speaks OpenAI's chat API, and
the model must support **tool calling** (it calls tools to read and change the calendar).
Two ways to get one:

- **A cloud model, through [OpenRouter](https://openrouter.ai)** (or any other
  OpenAI-compatible provider). Nothing to install, and cheap. Measured on a real luach with
  DeepSeek V4 Flash: a question that adds an event, and one that searches the web, cost about
  a tenth of a US cent together. A family asking 40 things a day spends around 1 US dollar a
  month. The email scan, if members turn it on, is one model turn per new email, which can
  add a few dollars. Bigger models cost 5 to 20 times more. You pay the provider directly,
  and can cap what a key may spend. The trade-off is privacy: what members ask, and the
  calendar context the model needs to answer, go to the provider.
- **A local model**, with [Ollama](https://ollama.com) or [vLLM](https://docs.vllm.ai) on
  your own hardware. Nothing leaves the house. luach was developed against Qwen3.6 35B-A3B,
  which needs about 24 GB of GPU memory (a graphics card with 24 GB or more, or a Mac with
  32 GB or more of unified memory). Smaller models run on less, but have not been measured:
  the owner's **Try it** button scores any model on luach's own cases before anyone relies on
  it (step 3).

### Optional extras

None of these is needed to start. Each has its own section below.

| | needs | costs |
|---|---|---|
| [A Google calendar](#the-calendar-luachs-own-or-google) instead of luach's own | a Google account and a free Google Cloud project | free |
| [Gmail](#gmail): members connect their mailbox, read-only | a Google Cloud project with an OAuth client | free |
| [Outgoing mail](#outgoing-mail): invitations, password resets, reminders by email | a [Resend](https://resend.com) account and your domain | free plan covers a household |
| [Voice](#voice): the microphone in the web app | a speech-to-text server, local or cloud | free locally; cents a month in the cloud |
| [Web search](#web-search) for the assistant | the SearXNG container in `compose.search.yml` | free; a Brave Search API key improves answers |
| [Push notifications](#push-notifications) | one command | free |
| [Single sign-on](#single-sign-on-oidc) | an OpenID Connect provider you already run | free |
| [Zoom links](#booking-links-and-zoom) for booked meetings | a Zoom account | your Zoom plan |

## Step 1: install Docker

luach runs in containers, started by Docker Compose. Install Docker with Compose on the machine
that will run luach.

### Linux (Ubuntu, Debian, and most others)

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
```

Log out and back in (or reboot), so the second line takes effect. Then install git, if it is
missing: `sudo apt install -y git` on Ubuntu or Debian.

### A Synology NAS

1. In DSM, open **Package Center**, find **Container Manager**, and install it (DSM 7.2 or
   later). An ARM model works as an x86 one does, if its processor is 64-bit (Synology's
   product page says which).
2. In **Control Panel › Terminal & SNMP**, tick **Enable SSH service** and apply.
3. From your computer, `ssh <your-dsm-user>@<the-nas-address>`. Every command in this guide
   then runs there, with `sudo` in front of `docker`: `sudo docker compose up -d`.
4. Put luach in a shared folder, for example `cd /volume1/docker` before step 2.

(Container Manager's **Project** screen can also start a compose project from that folder. The
commands are the same thing, and this guide uses them.)

### A QNAP NAS

1. In the **App Center**, install **Container Station**.
2. In **Control Panel › Network & File Services › Telnet / SSH**, allow SSH.
3. `ssh admin@<the-nas-address>`, and run the commands in this guide there.

### macOS

1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and start it.
2. git comes with Apple's command line tools: run `git --version` in Terminal and accept the
   offer to install them.

### Check it

```bash
docker compose version
```

It should print a version, 2.20 or later. If it says `docker: 'compose' is not a docker
command`, your Docker is too old: install it again as above.

## Step 2: get luach

```bash
git clone https://github.com/luach-app/luach.git
cd luach
cp .env.example .env
chmod 600 .env
```

`.env` is where everything luach needs to know goes, including passwords and keys, so the last
line makes it readable only by you. Open it in an editor (`nano .env` on a server: save with
Ctrl+O, Enter, and leave with Ctrl+X).

### The lines you must set

Everything under **Required** at the top:

- **`POSTGRES_PASSWORD`**: the database's password. Make a random one and paste it in:

  ```bash
  openssl rand -hex 24
  ```

  Set it before the first start. The database is created with this password; if you change
  it here later, luach can no longer open the database.

- **`LUACH_APP_URL`**: the address people open luach at. Leave it as
  `http://localhost:8004` for now; step 5 changes it to your `https://` address.

- **`LUACH_TIMEZONE`**: your household's time zone, as a name from the
  [tz database](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones), for example
  `Europe/Madrid` or `America/Chicago`. Each member can also have their own (they pick it when
  they make their account).

- **`OPENAI_BASE_URL`**, **`OPENAI_API_KEY`** and **`LUACH_MODEL`**: the model. Step 3.

### Optional lines that matter first

- **`LUACH_HOUSEHOLD_NAME`**: your family's name, as in "the Rivera household calendar". It
  appears on the sign-in screen and in mail.
- **`LUACH_TRUSTED_PROXIES`**: already set to the right value for the HTTPS setup in step 5.
  Leave it.
- **`LUACH_VERSION`**: which build of luach to run. Leave it unset to run the latest; see
  [Upgrades](#upgrades) to pin one.
- **`COMPOSE_FILE`**: which extra pieces to run beside luach, such as HTTPS (step 5) and web
  search. Leave it for now.

Everything else is off until you set it, and each optional section below says which lines it
needs.

### To build the image yourself

You do not need to: the published image (`ghcr.io/luach-app/luach`) runs on x86 and 64-bit ARM
alike. To run luach from the source you cloned instead, with changes of your own, uncomment
`COMPOSE_FILE` in `.env` and make it:

```
COMPOSE_FILE=docker-compose.yml:compose.build.yml
```

and add `--build` to the first `docker compose up` in step 4. The build takes a few minutes and
about 2 GB of memory. When step 5 adds more files to `COMPOSE_FILE`, keep `compose.build.yml` in
the list.

## Step 3: a model

Pick one of the two paths. You can change your mind later, and add more models for members to
choose from, in the app.

### (a) A cloud model through OpenRouter

1. Go to [openrouter.ai](https://openrouter.ai) and sign up.
2. Open **Settings › Credits** (openrouter.ai/settings/credits) and add a few dollars. 5 US
   dollars lasts a family months.
3. Open **Settings › API Keys** (openrouter.ai/settings/keys) and choose **Create API Key**.
   Name it `luach`. You can give it a credit limit, so it can never spend more than that.
   Copy the key (it starts with `sk-or-`); OpenRouter shows it only once.
4. In `.env`:

   ```
   OPENAI_BASE_URL=https://openrouter.ai/api/v1
   OPENAI_API_KEY=sk-or-...your key...
   LUACH_MODEL=deepseek/deepseek-v4-flash-0731
   ```

**Which model.** It must call tools reliably: a model that answers in prose where it should
call a tool will say it added an event it never added. `deepseek/deepseek-v4-flash-0731` is
the one this guide was tested with: it scored 12 of 12 on luach's own trial, and costs about
0.12 US dollars per million tokens in and 0.24 out. To see others, filter
[openrouter.ai/models](https://openrouter.ai/models) by **Tools** in its supported parameters.
An id is written as `provider/model`, exactly as OpenRouter shows it. Ids that start with `~`
(such as `~deepseek/deepseek-v4-flash-latest`) always point to the provider's newest version,
so a retired version can never break them; pinned ids behave the same every day. Either kind
works.

Later, once luach is running, the owner manages models in the app, under
**Settings › Household › Models**:

- **Add a model**: search OpenRouter's catalogue by name (it shows each model's context
  length, whether it takes tools, and its price), choose **Add**, or type an id under
  **Or by its id**. A new model is added off the members' menu, and luach starts **Try it** on
  it straight away.
- **Try it** runs twelve of luach's own cases against the model, in English, Spanish and
  Hebrew, on a fake calendar and a throwaway database, and shows a score: *good* is every case,
  *fair* is 80% or more. It takes a couple of minutes and costs about the same as a dozen
  questions (half a US cent with the model above). At most 6 runs a day
  (`LUACH_MODEL_TRIALS_PER_DAY`).
- **On the menu** lets members pick it in their own settings; **Make default** makes it the
  one that answers anyone who has not picked. Once you choose a default here, it wins over
  `LUACH_MODEL` in `.env`.
- **Edit** sets the name and description members see, and who runs it, for the privacy page.

With OpenRouter there is nothing else to set: the catalogue is the endpoint's own list. The
catalogue settings are for routers that cannot list their models (see
[More about models](#more-about-models)).

### (b) A local model with Ollama, on the same machine

You need the hardware for it (see [An AI model](#an-ai-model)); a model that runs too slowly
makes every answer wait.

**On Linux:**

1. Install Ollama:

   ```bash
   curl -fsSL https://ollama.com/install.sh | sh
   ```

2. Let containers reach it, and give models room. Ollama listens only on `127.0.0.1` at
   first, and luach's container comes from Docker's network, not from `127.0.0.1`, so it
   cannot connect until you change that. And Ollama's context window can be as small as 4096
   tokens (it is on a machine without a large GPU), less than luach's instructions and tools
   (about 4,200 tokens before a word of the conversation): Ollama cuts the beginning off, and
   the model answers without its instructions. Run `sudo systemctl edit ollama` and add, in the space the editor leaves for
   it:

   ```
   [Service]
   Environment="OLLAMA_HOST=0.0.0.0:11434"
   Environment="OLLAMA_CONTEXT_LENGTH=32768"
   ```

   then `sudo systemctl restart ollama`. Ollama has no password: if this machine's firewall
   lets the internet reach port 11434, close it. With `ufw`, which also stands between
   containers and the machine, allow luach's network in and nothing else:

   ```bash
   sudo ufw allow from 172.31.208.0/24 to any port 11434 proto tcp
   ```

**On a Mac:** install the Ollama app from [ollama.com](https://ollama.com). Docker Desktop
reaches it as it is. In the app's **Settings**, move **Context length** to 32k (4k is smaller
than luach's instructions).

**Then, on either:**

3. Download a model that calls tools:

   ```bash
   ollama pull qwen3.6:35b-a3b
   ```

4. In `.env`, with the model's name as Ollama gives it, colon and all:

   ```
   OPENAI_BASE_URL=http://host.docker.internal:11434/v1
   OPENAI_API_KEY=ollama
   LUACH_MODEL=qwen3.6:35b-a3b
   ```

   `host.docker.internal` is the machine itself, as luach's container sees it
   (`docker-compose.yml` sets that up). Ollama checks no key, but luach needs the line to have
   something in it.

Once luach is running, open **Settings › Household › Models**, choose **Edit** on the model,
and tick **Runs on our own computer (nothing leaves the house)**: the privacy page then says
so, the iPhone app does not ask members before sending their questions to it, and luach
asks the model not to think out loud (below). Use **Try it** to see how it scores. Add other
models from the list Ollama gives, by the name `ollama pull` used.

Qwen3 models think before they answer unless asked not to, which makes every answer slower.
Ollama does not hear the switch luach sends vLLM; it hears `reasoning_effort: "none"`, which
luach sends to a model marked **Runs on our own computer**. Measured with `qwen3:1.7b` on a
computer without a GPU, "dentist next Tuesday at 3pm" took 38 seconds with it and 74 without,
and "what is on next week?" 26 and 127. Even so, without a suitable GPU a model is slow, and
small models are not good at luach's tools: **Try it** shows both the score and how long it
took.
`LUACH_REASONING_EFFORT_NONE=always` sends it to every model (for an Ollama behind another
name), `never` to none.

**vLLM** (or LiteLLM, LocalAI, or any other OpenAI-compatible server) works the same way: put
its address, ending in `/v1`, in `OPENAI_BASE_URL`, and its name for the model in
`LUACH_MODEL`. For vLLM, start the model with tool calling on (`--enable-auto-tool-choice`
and the `--tool-call-parser` its model card names). luach asks Qwen-style models served by
vLLM not to think out loud (`chat_template_kwargs`), which on the models tested made tool calls
more reliable and answers faster; `LUACH_ENABLE_THINKING=1` turns that around.

## Step 4: start it

```bash
docker compose up -d
```

(With `compose.build.yml` in `COMPOSE_FILE`: `docker compose up -d --build`.)

The first time, Docker downloads the images (about 1 GB). Compose starts three services:

- **db**: Postgres 16 with pgvector, its data in a volume named `db`;
- **migrate**: brings the database to the version this luach expects, then exits;
- **luach**: the app, on `127.0.0.1:8004`, started once `migrate` has finished. Its volume,
  `state`, holds the mail key and the assistant's conversation state.

Check that it is up:

```bash
docker compose ps
curl http://localhost:8004/api/health
```

`db` and `luach` should say `Up`, and the health check should answer
`{"ok":true,"version":"0.1.0","build":"..."}`. If it does not answer yet, wait ten seconds and
try again: luach needs a moment to start.

### The setup code

The first account becomes the household's **owner**, and making it needs a one-time **setup
code**, so that whoever finds a new server first cannot take it over. luach prints the code
to its log when it starts with no accounts:

```bash
docker compose logs luach | grep -A4 "setup code"
```

```
luach-1  |   browser and enter this setup code on the "Set up the household" screen:
luach-1  |
luach-1  |       K7QD-M2XP-9WRT
luach-1  |
luach-1  |   It is also in /var/lib/luach/setup-code.
```

It is also kept in a file, if the log has scrolled away:

```bash
docker compose exec luach cat /var/lib/luach/setup-code
```

### Make the owner account

1. Open **http://localhost:8004** in a browser on the same machine. If luach runs on a server
   or NAS, you are not on its screen, so open a tunnel from your own computer first, and then
   open the same address on your computer:

   ```bash
   ssh -L 8004:127.0.0.1:8004 <you>@<the-server>
   ```

   (Or skip ahead to step 5 and make the account at your `https://` address.)

2. The page says **Set up the household**. Fill in:
   - **Setup code**: the code from the log (capitals, spaces and dashes do not matter);
   - **Username**, **Email**, **Display name** and **Password** (8 characters or more) for
     yourself;
   - the time zone, which is your browser's, unless you change it.

3. Choose **Create owner account**. You are signed in as the owner. The code is now spent,
   and the file is deleted; registration is closed for good, and everyone else joins by
   invitation (step 6).

### Check the assistant

In the **Ask luach** box beside the agenda, type something: "Dentist next Tuesday at 3pm".
luach should answer "Added: Dentist, ..." and the event appears in the **Agenda**. If it answers that no AI model
is set up, or something fails, see [Troubleshooting](#troubleshooting).

Signed in, `http://localhost:8004/api/health/details` shows how luach is wired: the calendar
in use, the model, and whether memory works.

## Step 5: HTTPS and a reverse proxy

So far luach answers only on the machine itself. For the family to use it, from their phones,
anywhere, it needs to be on the internet at your `https://` address. That is not optional:

- the session cookie is marked `Secure`, so browsers send it back only over HTTPS (or to
  `localhost`);
- passkeys and push notifications work only on a secure page;
- the iPhone app connects to `https://` addresses only, with a certificate the phone trusts;
- Google, and most single sign-on providers, accept only `https://` addresses to send people
  back to.

luach does not do HTTPS itself. A **reverse proxy** does: a program in front of it that holds
the certificate, answers on ports 80 and 443, and passes requests to luach. luach comes with
one ready, Caddy, which gets and renews a free certificate from Let's Encrypt by itself.

### With the Caddy that comes with luach

1. **Point your name at the machine.** At your domain's DNS provider, add a record for the
   name you chose:
   - type `A`, name `calendar` (for `calendar.example.com`), value: the machine's public
     IPv4 address. On a VPS, the provider shows it. At home, it is your internet connection's
     address: search "what is my IP" from a device at home. Add an `AAAA` record too if you
     have IPv6.
   - At home, if your address changes from time to time, use your router's or your DNS
     provider's dynamic DNS feature to keep the record current.

2. **Let the internet reach ports 80 and 443.**
   - At home: in your router's settings, find **port forwarding** and forward TCP 80, TCP 443
     and UDP 443 to the luach machine's address on your home network. (If your router's own
     internet address is not the one "what is my IP" shows, your provider shares one address
     among many homes, and port forwarding cannot work: use a
     [tunnel](#with-a-tunnel-instead-of-open-ports) instead.)
   - On a VPS: if the provider has a firewall in its control panel, allow 80 and 443 there.
   - On the machine itself, with `ufw`: `sudo ufw allow 80/tcp && sudo ufw allow 443`.

3. **Tell luach its address and turn Caddy on.** In `.env`:

   ```
   LUACH_APP_URL=https://calendar.example.com
   COMPOSE_FILE=docker-compose.yml:compose.caddy.yml
   ```

   (Building the image yourself: `COMPOSE_FILE=docker-compose.yml:compose.build.yml:compose.caddy.yml`.)
   `LUACH_APP_URL` is exactly what people will type, with no slash at the end. luach builds
   every link in its mail from it, checks that changes come from it, and ties passkeys to it.
   `LUACH_TRUSTED_PROXIES` stays as `.env.example` set it.

4. **Start it:**

   ```bash
   docker compose up -d
   docker compose logs caddy | grep -i certificate
   ```

   Within a minute Caddy should log `certificate obtained successfully`. Open your address in
   a browser: luach, with a padlock.

That is all of it: [compose.caddy.yml](../compose.caddy.yml) runs Caddy on ports 80 and 443,
and the [Caddyfile](../Caddyfile) beside it is the whole site:

```
{$LUACH_APP_URL} {
	reverse_proxy luach:8004
}
```

Caddy reads the address from `LUACH_APP_URL`, so there is nothing to edit in it. It redirects
`http://` to `https://`, renews the certificate before it expires, and keeps it in the
`caddy_data` volume.

**Why `LUACH_TRUSTED_PROXIES` matters.** luach locks an account for 5 minutes after 8 wrong
passwords from one address (`LUACH_LOGIN_MAX_ATTEMPTS`, `LUACH_LOGIN_LOCKOUT_SECS`). Behind a
proxy, every request reaches luach from the proxy, so luach must be told to believe the
proxy's `X-Forwarded-For` header about who is really asking, and only the proxy's. The
`docker-compose.yml` network has a fixed subnet, `172.31.208.0/24`, which is where Caddy
connects from (and where a proxy on the host connects from: the network's gateway,
`172.31.208.1`), and `.env.example` trusts exactly that:

```
LUACH_TRUSTED_PROXIES=127.0.0.1/32,::1/128,172.31.208.0/24
```

Without it, every member appears to come from one address, and anyone who mistypes a
member's password eight times locks that member out for everyone. If `docker compose up` says
the subnet overlaps another network on your machine, pick another private `/24` in the
`networks:` block at the end of `docker-compose.yml`, and the same one here.

### If you already run a reverse proxy

Point it at `http://127.0.0.1:8004` (from the same machine) and keep `compose.caddy.yml` out of
`COMPOSE_FILE`. Whatever the proxy, luach needs:

- **`LUACH_APP_URL`** set to the public `https://` address. luach refuses a change (a 403,
  `this request came from another site`) when the browser says it came from an address that is
  neither `LUACH_APP_URL` nor the host the request was sent to.
- **The `Host` header passed through**, or `X-Forwarded-Host` set to it.
- **`X-Forwarded-For`** with the client's address, and **`X-Forwarded-Proto`** with `https`.
- **`LUACH_TRUSTED_PROXIES`** listing the address the proxy connects from, as luach sees it. A
  proxy on the host reaches luach from the compose network's gateway, `172.31.208.1`, which the
  default value already covers. A proxy in another container on another Docker network needs
  that network's subnet added (`docker network inspect <network>` shows it).
- **No buffering of `text/event-stream`**, where the assistant's replies stream. luach sends
  `X-Accel-Buffering: no` and a keepalive line every 15 seconds, so nginx needs nothing more.
- **Uploads up to 12 MB**, for voice recordings.

**nginx**, on the host, with a certificate you already have (for example from certbot):

```nginx
server {
    listen 443 ssl;
    http2 on;
    server_name calendar.example.com;
    ssl_certificate     /etc/letsencrypt/live/calendar.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/calendar.example.com/privkey.pem;

    client_max_body_size 13m;            # voice recordings are up to 12 MB

    location / {
        proxy_pass http://127.0.0.1:8004;
        proxy_set_header Host              $http_host;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host  $http_host;
        proxy_read_timeout 300s;         # a long answer streams for a while
    }
}
```

**Traefik:** a router for your host whose service is `luach:8004`, on a Docker network the
luach container also joins, with that network's subnet added to `LUACH_TRUSTED_PROXIES`.
Traefik passes `Host` through and sets the `X-Forwarded-*` headers by default.

**A Synology NAS's own reverse proxy** (DSM holds ports 80 and 443, so Caddy cannot have them):
get a certificate in **Control Panel › Security › Certificate › Add › Get a certificate from
Let's Encrypt**; then in **Control Panel › Login Portal › Advanced › Reverse Proxy ›
Create**, set the source to `HTTPS`, your host name and port `443`, and the destination to
`HTTP`, `localhost`, port `8004`. Back in **Certificate › Settings**, give that entry your
certificate.

**Check it worked:** sign in once through the proxy, then

```bash
docker compose logs luach | grep "POST /api/auth/login" | tail -1
```

The address at the start of that line should be your own device's public address (or your
home's), not the proxy's. If luach printed a warning that a request `carries X-Forwarded-For,
but ... is not in LUACH_TRUSTED_PROXIES`, it names the address to add.

### With a tunnel instead of open ports

A tunnel service carries traffic from its own servers to yours over a connection your server
opens, so nothing needs forwarding at home, and it works where your provider shares one
address among many homes. Cloudflare Tunnel is one (your domain's DNS must be at Cloudflare):

1. In Cloudflare's dashboard, under **Zero Trust › Networks › Tunnels**, create a tunnel of
   type **Cloudflared**, and copy its token.
2. Give it a **public hostname**: your name (`calendar.example.com`), with the service
   `HTTP` and `luach:8004`.
3. Add the connector to luach's compose project, in a file `compose.tunnel.yml`:

   ```yaml
   services:
     cloudflared:
       image: cloudflare/cloudflared:2026.10.5
       restart: unless-stopped
       command: tunnel --no-autoupdate run
       environment:
         TUNNEL_TOKEN: ${CLOUDFLARE_TUNNEL_TOKEN:?set CLOUDFLARE_TUNNEL_TOKEN in .env}
   ```

4. In `.env`: `CLOUDFLARE_TUNNEL_TOKEN=<the token>`,
   `COMPOSE_FILE=docker-compose.yml:compose.tunnel.yml` and
   `LUACH_APP_URL=https://calendar.example.com`; then `docker compose up -d`.

The connector reaches luach from the compose subnet, which is trusted, and Cloudflare sends
the visitor's address in `CF-Connecting-IP`, which luach reads. Cloudflare decrypts the
traffic on its servers on the way through.

### More than one address

`LUACH_EXTRA_ORIGINS` (comma separated) adds origins a passkey may be used from, if luach is
reached under more than one name. `LUACH_RP_ID` sets the passkey relying party, which is the
host name in `LUACH_APP_URL` by default. Passkeys belong to one name: if you change
`LUACH_APP_URL` to a new host, members add their passkeys again.

`LUACH_COOKIE_SECURE=0` exists only to try luach over plain `http://` at an address other than
`localhost`. Never leave it on a server people use.

## Step 6: invite the family

### Invitations

Only the owner sees **Members**. There, type a family member's email address under **Invite by
email** and choose **Send invitation**.

- If [outgoing mail](#outgoing-mail) is set up, luach mails them a link.
- If it is not, luach shows the link, with **Copy**: send it to them yourself, by message or
  however you like. **Members** says which happened (mail is not set up, or it is and the send
  failed, and then the log says why).

The link opens luach, where they choose a username and password and start in their own time
zone. Each member sees the shared calendar, and their own conversations, which no one else
can read. The owner cannot be removed; anyone else can, from **Members**.

The link is built from `LUACH_APP_URL`. If that is still `http://localhost:8004`, luach uses
the address you are using instead, and **Members** reminds you to set `LUACH_APP_URL`.

Children who will not have accounts can still have events and tasks: the owner adds them to
the family in **Members**, or lists them in `.env` for the first start:
`LUACH_FAMILY=Robin; Sam:kid; Noa:kid`.

### The iPhone app

1. On the iPhone, install **luach** from the App Store.
2. Open it. Under **Your luach's address**, type your address, `calendar.example.com` (the
   app adds `https://`). The app checks that a luach answers there and shows your household's
   name.
3. Sign in with the username and password from the invitation. Accept the invitation in the
   browser first: the app signs in to existing accounts.

The app talks only to your server. It refuses plain `http://` addresses, even at home: an
address like `192.168.1.20` means a different machine on every network, and `https` with a
real certificate is what proves it is your luach. A certificate from Caddy, a tunnel or
Let's Encrypt is what it needs; one you made yourself is not trusted by the phone.

Not in the app yet: single sign-on, signing in with a passkey, and accepting invitations.
Those are in the web app, which also installs on a phone's home screen (Share › Add to Home
Screen in Safari).

### A screen in the kitchen

The wall board is `/board` on your address: everyone's day side by side, on a touch screen
that stays on.

1. On the screen's browser, open `https://calendar.example.com/board`. It shows a
   six-character code.
2. On your phone, signed in as the owner, open **Members › House boards**, type the code, name
   the board ("Kitchen"), and choose **Pair**. Codes last ten minutes.

The board never holds anyone's session; what is done on it is recorded as the board's. Which
screen to buy, how to mount it, and how to lock a tablet to the board:
[WALL-BOARD.md](WALL-BOARD.md).

---

The rest of this guide is optional. Add what you want, when you want it; each part says which
lines of `.env` it needs. After changing `.env`, apply it with `docker compose up -d`, which
restarts what changed.

## The calendar: luach's own, or Google

`LUACH_CALENDAR` chooses where events live:

| value | events live in |
|---|---|
| `local` (the default) | luach's own database. Nothing else is needed, and backing up the database backs up the calendar. |
| `google` | a Google calendar, through a service account or the owner's own Google grant (below). Without the credential, luach refuses to start and says which setting is missing. |
| `fake` | memory only, for tests: every event is lost when luach restarts, and the log says so at every start. Never for a household. |

The log's startup line names the calendar in use: `luach 0.1.0 up: calendar=local (luach's own
database) ...`.

Choose Google if the family already lives in Google Calendar and wants to keep seeing events
there. Otherwise `local` is simpler, and needs no Google account at all.

### Google, through a service account (simplest)

A service account is a robot Google account that your calendar is shared with. It can read and
change events, but cannot send invitations to other people's addresses.

1. Go to [console.cloud.google.com](https://console.cloud.google.com), sign in, and create a
   project: the project picker at the top › **New project**, name it `luach`, **Create**.
2. Enable the Calendar API: **APIs & Services › Library**, search **Google Calendar API**,
   open it, **Enable**.
3. Create the service account: **IAM & Admin › Service Accounts › Create service account**.
   Name it `luach`, choose **Create and continue**, skip the optional roles, and **Done**.
4. Make its key: open the new service account, then **Keys › Add key › Create new key ›
   JSON › Create**. A `.json` file downloads. (If Google says key creation is disabled by an
   organization policy, your account belongs to an organization that forbids keys: use the
   OAuth way below.) Copy the service account's email address, `luach@<project>.iam.gserviceaccount.com`.
5. Share the calendar with it: in [Google Calendar](https://calendar.google.com), hover over
   the family calendar, **⋮ › Settings and sharing › Share with specific people › Add people**,
   paste that address, choose **Make changes to events**, **Send**.
6. On the same settings page, under **Integrate calendar**, copy the **Calendar ID**.
7. Put the key beside luach and let the container read it:

   ```bash
   mkdir -p credentials
   mv ~/Downloads/<the-key>.json credentials/google-sa.json    # or however it reaches the server
   sudo chown -R 10001:10001 credentials
   sudo chmod 600 credentials/*
   ```

   luach runs as user 10001 in its container, so the file must belong to that user. (On a Mac,
   Docker Desktop handles this; skip the two `sudo` lines.)

8. In `docker-compose.yml`, uncomment the line `- ./credentials:/run/luach:ro`. In `.env`:

   ```
   LUACH_CALENDAR=google
   LUACH_GOOGLE_SA_KEY=/run/luach/google-sa.json
   LUACH_GOOGLE_CALENDAR_ID=<the calendar id>
   ```

9. `docker compose up -d`, and check the startup line:
   `docker compose logs luach | grep " up: "` should say `calendar=google (<the id>, sa)`.

A service account cannot list the calendars it was shared, so `LUACH_GOOGLE_CALENDAR_ID` is the
one it uses. Events with guests are saved without the invitations, and the event says so.

### Google, through the owner's own grant

With a grant from the owner's own Google account, luach can list their calendars (the owner
picks which ones it reads, and where new events go, in **Settings › Household**) and send
invitations to guests. It takes an OAuth client and a refresh token:

1. In your Google Cloud project, enable the **Google Calendar API** as above.
2. Set up the consent screen: **Google Auth Platform** (in the menu, or search for it) ›
   **Get started**. App name `luach`, your email as support email, **Next**; audience
   **External**, **Next**; your email as contact, **Next**; agree, **Create**.
3. **Publish it**: **Audience › Publish app › Confirm**. An app left in **Testing** gets
   refresh tokens that Google expires after seven days, which would stop the calendar every
   week. Published but not verified by Google is fine for a family: Google shows a warning
   page once, when you grant access ("Google hasn't verified this app": choose **Advanced ›
   Go to luach**).
4. Create the client: **Clients › Create client**, type **Web application**, name `luach`.
   Under **Authorized redirect URIs**, add `https://developers.google.com/oauthplayground`
   (for the next step). **Create**, and copy the client id and secret.
5. Get a refresh token, with Google's OAuth 2.0 Playground:
   [developers.google.com/oauthplayground](https://developers.google.com/oauthplayground).
   Open the ⚙ settings, tick **Use your own OAuth credentials**, and paste the client id and
   secret. In **Step 1**, type the scope `https://www.googleapis.com/auth/calendar` (add
   `https://www.googleapis.com/auth/gmail.modify`, separated by a space, if you also want the
   [email door](#the-email-door-a-household-gmail-label)), and **Authorize APIs**; sign in as
   the owner and allow. In **Step 2**, **Exchange authorization code for tokens**, and copy
   the **Refresh token**.
6. Write the two files luach reads. The client file is a flat object, not the JSON Google
   offers for download:

   ```bash
   mkdir -p credentials
   cat > credentials/google-oauth-client.json <<'EOF'
   {"client_id": "<client id>", "client_secret": "<client secret>"}
   EOF
   cat > credentials/google-oauth-tokens.json <<'EOF'
   {"refresh_token": "<refresh token>"}
   EOF
   sudo chown -R 10001:10001 credentials && sudo chmod 600 credentials/*
   ```

7. Uncomment `- ./credentials:/run/luach:ro` in `docker-compose.yml`, and in `.env`:

   ```
   LUACH_CALENDAR=google
   LUACH_GOOGLE_OAUTH_CLIENT=/run/luach/google-oauth-client.json
   LUACH_GOOGLE_OAUTH_TOKENS=/run/luach/google-oauth-tokens.json
   LUACH_GOOGLE_CALENDAR_ID=<the calendar id>
   ```

8. `docker compose up -d`. The startup line says `calendar=google (<the id>, oauth)`. Then, as
   the owner, choose the calendars in **Settings › Household**.

`LUACH_CALENDAR_AUTH` picks the credential when both kinds are configured: `auto` (the
default) uses the grant when both of its files are set, and the service account otherwise;
`oauth` or `sa` force one.

## Gmail

There are two separate ways in.

### Each member's own Gmail

A member connects their own Gmail, read-only, from **Settings › You** (**Connect my Gmail**).
luach can then answer questions about their mail ("when is our flight?"), and, if they turn it
on, scan new mail every `LUACH_MAIL_SCAN_MIN` minutes (10; `0` switches the scan off for
everyone) for things that belong on the calendar. The scan only proposes: everything it finds
waits for that member's approval, and nobody else sees it. Mail whose sender Gmail could not
authenticate is skipped.

To offer it, you need a Google OAuth client of your own. In the same Google Cloud project as
above, or a new one:

1. **APIs & Services › Library**: search **Gmail API**, open it, **Enable**.
2. **Google Auth Platform › Get started** (if you have not done it above): app name `luach`,
   support email, audience **External**, contact email, **Create**.
3. **Branding**: add your [About and Privacy pages](#the-about-and-privacy-pages) as the
   home page (`https://calendar.example.com/about`) and privacy policy
   (`https://calendar.example.com/privacy`), and your domain under **Authorized domains**.
4. **Data Access › Add or remove scopes**: add
   `https://www.googleapis.com/auth/gmail.readonly`, **Update**, **Save**.
5. **Clients › Create client**, type **Web application**, name `luach mail`. Under
   **Authorized redirect URIs** add exactly `https://calendar.example.com/api/mail/callback`
   (your `LUACH_APP_URL` followed by `/api/mail/callback`). **Create**, then download the
   client's JSON (**⬇** beside it). Google's own format is fine here.
6. Put it in `credentials/` as `mail-oauth-client.json`, owned by 10001 as above, with the
   `./credentials:/run/luach:ro` line uncommented, and in `.env`:

   ```
   LUACH_MAIL_OAUTH_CLIENT=/run/luach/mail-oauth-client.json
   ```

   `LUACH_APP_URL` must be your `https://` address. Then `docker compose up -d`.

**Testing or published.** `gmail.readonly` is a scope Google calls *restricted*. You can leave
the app in **Testing** and add each member's address under **Audience › Test users**, but then
Google expires each member's connection **after seven days**: luach notices, tells the member
by a push (and an email, when mail is set up) that "Gmail disconnected — reconnect", and
**Settings** shows the button until they do. To stop that weekly round, publish the app
(**Audience › Publish app**). A published, unverified app works for up to 100 accounts; each
member sees Google's "this app isn't verified" page once, and chooses **Advanced › Go to
luach**. Google's verification of restricted scopes involves a paid security assessment and
is not needed for a family.

**On Google Workspace**, make the app **Internal** (in **Audience**) instead and set
`LUACH_MAIL_DOMAIN` to your domain: no warning page, no expiry, only that domain's accounts
can connect, and Google's account chooser offers those accounts with the member's own address
first.

Each member's grant is stored encrypted with `LUACH_MAIL_KEY` (a Fernet key). Unset, luach
creates `mail.key` in the `state` volume, outside the database and so outside database
backups: a copy of either alone opens no one's mail. Back it up with the state volume (see
[Backups](#backups)), or set the key yourself:

```bash
docker compose run --rm --no-deps luach \
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Losing the key leaks nothing; members connect their mail again.

### The email door: a household Gmail label

The household's own Gmail can feed luach directly: every `LUACH_GMAIL_POLL_MIN` minutes (`0`,
off, by default) luach reads unread messages labelled `LUACH_GMAIL_LABEL` (`luach`), runs each
one as a request from the member whose confirmed address sent it, and moves it to
`luach/done`. Family members forward an email to that mailbox, and a Gmail filter labels it.
A message from anyone else is read for the owner but can only propose: everything it would
add or change waits in **Pending** for a member's approval. Only messages Gmail authenticated
for their From: domain are acted on (Gmail's own `Authentication-Results`: DMARC passing for
that domain, or a DKIM signature or SPF sender aligned with it), and each is read once.

It uses the household grant from [the owner's own grant](#google-through-the-owners-own-grant)
(`LUACH_GOOGLE_OAUTH_CLIENT` and `LUACH_GOOGLE_OAUTH_TOKENS`), made with the extra scope
`https://www.googleapis.com/auth/gmail.modify` so luach can create the label and move handled
messages. Then set `LUACH_GMAIL_POLL_MIN=5`, for example.

## Outgoing mail

luach sends invitations, password resets, address confirmations, booking confirmations and
emailed reminders through [Resend](https://resend.com):

1. Sign up at Resend.
2. **Domains › Add Domain**: your domain, or a subdomain for mail such as
   `mail.example.com`. Resend lists a few DNS records (TXT and MX); add them at your DNS
   provider exactly as shown, then choose **Verify DNS Records**. It can take a few minutes.
3. **API Keys › Create API Key**, permission **Sending access**, and copy the key (it starts
   with `re_`).
4. In `.env`:

   ```
   RESEND_API_KEY=re_...
   LUACH_MAIL_FROM=luach <calendar@mail.example.com>
   LUACH_MAIL_REPLY_TO=you@example.com
   ```

   The sender must be on the domain you verified. Without `LUACH_MAIL_FROM`, Resend's shared
   test sender is used, which delivers only to your own Resend account's address.

Mail whose point is a link (an invitation, a password reset) is sent only when `LUACH_APP_URL`
is set. **Members** shows what mail can and cannot do on this server, and so does the
sign-in screen's **Forgot your password?**.

### A forgotten password, without mail

Without outgoing mail, nobody can be sent a reset link, and the sign-in screen says so instead
of promising one. Whoever runs the server sets a new password:

```bash
docker compose exec luach python -m luach.passwd <username>
```

It asks for the new password twice, and signs that member out everywhere. It works with mail
configured too, for the owner's own account, say.

## Single sign-on (OIDC)

Members can sign in through an OpenID Connect provider you already run (Authentik, Keycloak,
Authelia and others) beside their password and passkeys. It never creates accounts: it admits
a member already in luach, matched by the email claim against any of their confirmed
addresses, whose provider account holds the required group. The provider must say it verified
that address (`email_verified: true`; Authentik's stock mapping says false, so give the client
a mapping that asserts it for accounts you provision). The first sign-in links the provider
account (its `sub`) to the member; after that the account decides, not the address, and
another account showing that member's address is refused. A member whose provider account is
replaced (a new `sub`, as a renamed user is under Authentik's `user_username` subject mode) is
refused until their row in `oidc_links` is deleted; removing a member removes it too.

Register a confidential client at the provider with the redirect URI
`<LUACH_APP_URL>/api/auth/oidc/callback`, then set:

- `LUACH_OIDC_ISSUER`: the issuer exactly as the provider publishes it, trailing slash
  included. luach reads `<issuer>.well-known/openid-configuration` and checks its `issuer`.
- `LUACH_OIDC_CLIENT_ID` and `LUACH_OIDC_CLIENT_SECRET`.
- `LUACH_OIDC_REQUIRED_GROUP` (`admins`): the group a member must hold. Set but empty switches
  single sign-on off; it never means "anyone".
- `LUACH_OIDC_LABEL`: the button's text (`Sign in with single sign-on`).

Single sign-on is offered only when the issuer, client id, secret and group are all set.
`LUACH_OIDC_SCOPES`, `LUACH_OIDC_GROUPS_CLAIM`, `LUACH_OIDC_EMAIL_CLAIM`,
`LUACH_OIDC_REDIRECT_URI` and `LUACH_OIDC_HTTP_TIMEOUT` cover providers that differ from the
defaults; see [API.md](API.md#single-sign-on-oidc).

## Voice

The microphone in the web app records audio and sends it to luach, which passes it to a
speech-to-text service that speaks OpenAI's transcription API. With none set, the microphone
is hidden.

**A cloud service.** With an OpenAI API key, for example:

```
LUACH_TRANSCRIBE_URL=https://api.openai.com/v1/audio/transcriptions
LUACH_TRANSCRIBE_KEY=sk-...
LUACH_TRANSCRIBE_MODEL=whisper-1
```

A family's short voice requests cost cents a month. The recording goes to that provider.

**On your own machine.** Any server that implements OpenAI's `/v1/audio/transcriptions`
works, for example a Whisper server such as [speaches](https://github.com/speaches-ai/speaches)
run by its own instructions. Put its full URL in `LUACH_TRANSCRIBE_URL`
(`http://host.docker.internal:<port>/v1/audio/transcriptions` for one on the same machine,
reached the way [Ollama](#b-a-local-model-with-ollama-on-the-same-machine) is), its key in
`LUACH_TRANSCRIBE_KEY` if it wants one, and its model's name in `LUACH_TRANSCRIBE_MODEL`
(`whisper-1` by default). It must accept WebM and MP4 audio (what browsers record), up to
12 MB.

Alternatively, `LUACH_TRANSCRIBE_CMD` is a command inside luach's container that takes one
audio file path and prints the transcript; the URL wins when both are set.

## Web search

With web search, the assistant can look things up: opening hours, an address, a match's
kick-off time, the weather. luach asks a [SearXNG](https://docs.searxng.org), a search engine
you run that asks the big ones for you. luach comes with one ready, in `compose.search.yml`:

1. Make its settings file from the example:

   ```bash
   cp searxng/settings.example.yml searxng/settings.yml
   ```

2. In `.env`, give it a secret, point luach at it, and add the file to `COMPOSE_FILE`:

   ```
   SEARXNG_SECRET=<the output of: openssl rand -hex 32>
   LUACH_SEARCH_URL=http://searxng:8080
   COMPOSE_FILE=docker-compose.yml:compose.caddy.yml:compose.search.yml
   ```

3. `docker compose up -d`. Then ask luach something it has to look up: "What time does the
   public library open on Saturday? Look it up."

The SearXNG publishes no port: only luach reaches it, on the compose network. Its log shows
some errors about engines it could not load at start (`ahmia`, `torch`, `wikidata`); those are
normal. Results reach the model as quoted text, never as instructions.

**Engine weights.** luach reads the six results SearXNG scores highest, so its engine weights
decide what the model sees. The example settings work with no keys, using SearXNG's default
engines, and keep Bing low if you turn it on (it reads many queries by their first word). The
best answers came from Brave's Search API: weighted 4 against Bing's 0.25, it took a set of
real family questions from 0 of 6 answered to 5 of 6. It needs a key from
[brave.com/search/api](https://brave.com/search/api/) (see their plans); paste it into the
commented `braveapi` lines at the end of `searxng/settings.yml`, uncomment them, and
`docker compose up -d --force-recreate searxng` (a plain restart can keep reading the old
file). `searxng/settings.yml` is ignored by git, so the key stays
out of the repository.

Search engines sometimes refuse a server's automated searches (SearXNG's log then says
`CAPTCHA` or `too many requests` for an engine); a home connection is refused less often than
a data centre's, and the API engines never are.

A question about the weather also asks [Open-Meteo](https://open-meteo.com) for the coming
week's forecast at the place it names (the household's time zone city when it names none);
only the place name is sent.

Any SearXNG works, not only this one: `LUACH_SEARCH_URL` is its address, and its
`settings.yml` must allow the JSON format (`search: formats: [html, json]`).

## Push notifications

Web push tells members about held actions and reminders, on their phones and computers. Make a
key pair once:

```bash
docker compose run --rm --no-deps -T luach python - < scripts/gen_vapid.py >> .env
docker compose up -d
```

That appends `LUACH_VAPID_PUBLIC` and `LUACH_VAPID_PRIVATE` to `.env`. Keep them: a new pair
invalidates every member's subscription. `LUACH_VAPID_SUBJECT` tells push services how to reach
you (`mailto:` or `https:`); unset, it is `LUACH_APP_URL`. Each member then turns
**Notifications** on in **Settings › Reminders**. Push needs HTTPS. On an iPhone, web push works for the
web app added to the home screen.

## The About and Privacy pages

`/about` and `/privacy` are public pages, readable without signing in. Google's consent screen
asks for links to both before members can connect Gmail through your client, and they tell a
visitor who runs the server. They are filled in from:

- `LUACH_HOUSEHOLD_NAME`: the household's name.
- `LUACH_OPERATOR_NAME`: who runs this luach. Unset: "the person who runs this luach".
- `LUACH_CONTACT_EMAIL`: where questions and requests to delete an account go. Unset: no
  address is shown.
- `LUACH_PRIVACY_MODELS`: a plain-text paragraph on which models see what members ask, and
  where they run. Unset, the page names each model on the menu and who runs it, worked out
  from the menu ("Google, through OpenRouter" for `openrouter/google/...`; the owner can say it
  in their own words in each model's **Who runs it**).

## Booking links and Zoom

Members publish booking pages from **Settings › Meetings**: others pick a time inside the hours
they set, when every household calendar is free, and get an invitation. They need nothing from
the server beyond `LUACH_APP_URL`, and outgoing mail for the confirmations.

To give each booked meeting a Zoom link: at [marketplace.zoom.us](https://marketplace.zoom.us),
**Develop › Build App › Server-to-Server OAuth App**, give it the `meeting:write:admin` scope,
activate it, and copy its account id, client id and client secret into `.env`:

```
LUACH_ZOOM_ACCOUNT_ID=...
LUACH_ZOOM_CLIENT_ID=...
LUACH_ZOOM_CLIENT_SECRET=...
```

## More about models

- **`LUACH_MODELS`** fills an empty menu once, on the first start, as JSON:

  ```
  LUACH_MODELS=[{"id":"qwen3.6:35b-a3b","name":"At home","about":"Runs on our own computer.","local":true},{"id":"deepseek/deepseek-v4-flash-0731","name":"DeepSeek","about":"Sent to DeepSeek, through OpenRouter."}]
  ```

  `local: true` marks a model on your own computer. A value that is not valid JSON of that
  shape is ignored, with a warning. After the first start, changing it changes nothing: the
  menu is the app's.
- **`LUACH_MODEL_CATALOGUE_URL`** and **`LUACH_MODEL_CATALOGUE_PREFIX`**: where the Models
  screen lists models from, when the endpoint's own `/models` lists nothing useful (a LiteLLM
  router with a wildcard `openrouter/*` route, say), and what to put before each id it lists:

  ```
  LUACH_MODEL_CATALOGUE_URL=https://openrouter.ai/api/v1/models
  LUACH_MODEL_CATALOGUE_PREFIX=openrouter/
  ```

  The endpoint's key is only ever sent to the endpoint's own host; a catalogue elsewhere is
  asked without it.
- **`LUACH_EVALS_DATABASE_URL`**: a Postgres server where **Try it** may create a database of
  its own (a role with CREATEDB). Unset, each run uses a schema of its own in luach's database
  instead, dropped when it ends.
- **A model that stops answering** (its provider refuses it, or three turns in a row fail) is
  marked *not answering*; the owner gets a push (and a mail, when mail is set up), members who
  had picked it go back to the default and are told so, and luach asks it again every hour.
  **Check** asks it now.
- `LUACH_ENABLE_THINKING` (off) lets the model reason before answering; on the models tested
  it cost tool calls. `LUACH_MAX_ITERATIONS` (16) caps the model calls in one turn.
- `LUACH_REASONING_EFFORT_NONE` (`local`) is where thinking-off is also sent as
  `reasoning_effort: "none"`, the switch Ollama hears: to models marked as running on your
  own computer (`local`), to every model (`always`), or to none (`never`). Not every provider
  takes a parameter it does not expect, which is why it is not sent everywhere by default.

## Memory

luach keeps what members tell it about themselves ("I only book mornings") in the database,
with a small embedding model that ships in the image; nothing is downloaded at runtime.
`docker-compose.yml` turns it on (`LUACH_MEMORY_DSN`). The log says `memory: ready` at start,
and `/api/health/details` (signed in) reports whether it answers.

## Living with it

### Backups

Two things hold everything a household would miss:

- **The database** (the `db` volume): the calendar in local mode, members, tasks,
  conversations, memory, settings and the audit trail.
- **The state volume** (`state`): `mail.key`, which opens members' Gmail grants (unless you set
  `LUACH_MAIL_KEY`), and the assistant's conversation state. Without it the database is still
  whole, but members connect Gmail again, and an old conversation cannot be continued.

And the files beside `docker-compose.yml` that you made: `.env` (every password and key),
`credentials/` and `searxng/settings.yml`. In Google mode, the events themselves are in Google.

**Make a backup** (from the luach folder):

```bash
mkdir -p backups && chmod 700 backups
docker compose exec -T db pg_dump -U luach -Fc luach > backups/luach-$(date +%F).dump
docker compose exec -T luach tar czf - -C /var/lib/luach . > backups/state-$(date +%F).tgz
```

`.env` holds secrets, and so do the backups (the database holds password hashes, conversations
and encrypted Gmail grants): keep the copies somewhere only you can read, and **off this
machine** (another computer, a NAS, an encrypted cloud drive), or a dead disk takes the backups
with it. `backups/` is ignored by git.

**Every night, by itself:** `crontab -e` and add (with your folder's path; the `%` signs need
their backslashes in a crontab):

```
30 3 * * * cd /home/you/luach && docker compose exec -T db pg_dump -U luach -Fc luach > backups/luach-$(date +\%F).dump && docker compose exec -T luach tar czf - -C /var/lib/luach . > backups/state-$(date +\%F).tgz && find backups -mtime +30 -delete
```

That keeps 30 days. Copy `backups/` elsewhere as well.

**Restore**, onto the same machine or a new one (with luach cloned and the same `.env`):

```bash
docker compose down                     # stops luach; the volumes stay
docker compose up -d --wait db
docker compose exec -T db pg_restore -U luach -d luach --clean --if-exists --no-owner \
  < backups/luach-2026-01-31.dump
docker compose run --rm --no-deps -T luach tar xzf - -C /var/lib/luach \
  < backups/state-2026-01-31.tgz
docker compose up -d
```

On a new machine the volumes start empty, and the same commands fill them. `--clean
--if-exists` replaces what is there; `migrate` then brings the restored database to the
current version.

**Test it once.** A backup you have never restored is a hope. On a spare machine (or a VPS for
an hour), clone luach, copy `.env` and the two files over, run the restore above, sign in, and
check that your events are there.

### Upgrades

**Before you upgrade, take a backup**, and note which build you run:

```bash
docker inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' \
  ghcr.io/luach-app/luach:main
```

Then:

```bash
git pull                     # the compose files and docs of the new version
docker compose pull          # the new image
docker compose up -d         # migrate runs, then the new luach starts
docker image prune -f        # removes the old images
```

Compare your `.env` with `.env.example` for settings that were added or changed
(`git diff HEAD@{1} -- .env.example` shows what the pull changed in it).

**Pin a version.** The image is published for every change to luach's `main` branch, tagged
`main` and with the commit's first seven characters, such as `a1b2c3d`
([the list](https://github.com/luach-app/luach/pkgs/container/luach)). Set `LUACH_VERSION` in
`.env` to one of those to stay on it until you change it; `docker compose up -d` after
changing it.

**Go back.** Migrations only move forward, so an older luach may refuse a database a newer one
upgraded (`luach-migrate` and the app say so in the log). Set `LUACH_VERSION` to the commit you
noted, restore the backup you took before the upgrade, and `docker compose up -d`.

**Building from source** (`compose.build.yml`): `git pull`, then `docker compose up -d --build`.

### Monitoring

- `docker compose ps`: every service `Up` (`migrate` shows `Exited (0)`, which is right).
- `docker compose logs -f luach`: what luach is doing. Ctrl+C stops following.
- `https://calendar.example.com/api/health` answers `{"ok":true,...}` to anyone, without
  signing in: point an uptime monitor at it (any service that checks a web address every few
  minutes and emails you when it fails).
- `/api/health/details`, signed in: the calendar, the model and memory.
- The owner's **Settings › Household › Models** shows a model that has stopped answering.
- The audit trail, in **Settings › Security**: every change the assistant and members made,
  in a chain luach checks at every start (`audit chain does NOT verify` in the log means
  someone edited it in the database).

### Security checklist

- [ ] `POSTGRES_PASSWORD` is random, and `.env` is readable only by you (`chmod 600 .env`).
- [ ] luach is reached only over `https://`; port 8004 stays on `127.0.0.1`, as
      `docker-compose.yml` publishes it. Do not change that to `0.0.0.0`.
- [ ] Only ports 80 and 443 are open to the internet (and 22 for SSH, if you need it, with
      key-based login).
- [ ] `LUACH_TRUSTED_PROXIES` lists only your proxy's network.
- [ ] The owner, and anyone else who wants it, adds a passkey (**Settings › Security**).
- [ ] `LUACH_SETUP_CODE`, if you ever set it, is removed once the owner exists.
- [ ] `LUACH_API_KEY` and `LUACH_TULIP_KEY` stay unset unless a program of yours needs them;
      then each is `openssl rand -hex 32`, and luach refuses to start with anything weaker.
- [ ] `LUACH_COOKIE_SECURE` is not set to `0`.
- [ ] Ollama, or any model server on this machine, is not reachable from the internet.
- [ ] Backups run, are kept off the machine, and you have restored one.
- [ ] You upgrade regularly: security fixes reach you only that way. Watch the repository's
      releases (**Watch › Custom › Releases** on GitHub) to hear about them.

To report a vulnerability in luach itself, see [SECURITY.md](../SECURITY.md).

## Troubleshooting

Most answers start with the log: `docker compose logs luach | tail -50`.

**I can't find the setup code.** `docker compose logs luach | grep -A4 "setup code"`, or
`docker compose exec luach cat /var/lib/luach/setup-code`. A restart before anyone used it
keeps the same code. If the page says **Sign in** instead of **Set up the household**, the
owner already exists (the code is spent and the file gone): sign in, or reset that account's
password with `docker compose exec luach python -m luach.passwd <username>`. The form's errors
say what is wrong: `that setup code is wrong`, or `the setup code is required`. Wrong codes
are throttled like wrong passwords: `too many attempts; try again later`.

**`docker compose up` says `set POSTGRES_PASSWORD in .env`.** `.env` is missing, not in this
folder, or has no `POSTGRES_PASSWORD` line.

**`docker compose up` says `service "migrate" didn't complete successfully`.**
`docker compose logs migrate` says why. `password authentication failed` means
`POSTGRES_PASSWORD` changed after the database was created. Put the old one back. (On a test
install with nothing to keep, `docker compose down -v` deletes the database so it is made
again with the new password. That deletes everything.)

**`Pool overlaps with other one on this address space`.** Another Docker network already uses
`172.31.208.0/24`. Pick another private `/24` (say `172.31.209.0/24`) in the `networks:` block
at the end of `docker-compose.yml`, and in `LUACH_TRUSTED_PROXIES`.

**Changes fail with 403, `this request came from another site`.** The browser is on an address
luach does not know as its own. The log says which: `refused a change sent from
https://...; if that address is luach itself, set LUACH_APP_URL to it`. Set `LUACH_APP_URL` to
exactly what is in the browser's address bar (scheme, name, and port if there is one; no
slash at the end), then `docker compose up -d`. Behind a proxy that rewrites `Host`, also make
it send `X-Forwarded-Host`.

**Changes fail with 415, `send the body as application/json`.** Something between the browser
and luach changed the request. Look at the proxy's configuration.

**Members get locked out, or wrong passwords from anyone lock someone out for everyone.** luach
cannot see members' real addresses behind your proxy. The log names the fix: `a request from
172.31.208.4 carries X-Forwarded-For, but 172.31.208.4 is not in LUACH_TRUSTED_PROXIES ...
add it: LUACH_TRUSTED_PROXIES=...`. Use the `LUACH_TRUSTED_PROXIES` line from `.env.example`
(the compose subnet), or the one the warning gives. A member locked out waits 5 minutes, or
signs in with a passkey or single sign-on, which the lock does not stop.

**The log says `LUACH_MODEL is not a model id luach can send`.** The id has a space, a
character outside letters, digits and `. _ ~ / @ + - :`, two colons together, or more than 128
characters. Copy the name exactly as the model server lists it (`ollama list`).

**Ollama's answers ignore what luach told the model, or its log says `truncating input
prompt`.** Ollama's context window is smaller than luach's instructions: set
`OLLAMA_CONTEXT_LENGTH`, as in [Ollama](#b-a-local-model-with-ollama-on-the-same-machine).

**The assistant says `No AI model is set up for this luach yet`.** `OPENAI_BASE_URL` or
`LUACH_MODEL` is empty. The log says at start: `no model is configured: the assistant will say so until
OPENAI_BASE_URL and LUACH_MODEL are set, or the owner picks one in Settings > Household >
Models`. Set them in `.env` and `docker compose up -d`, or add a model and **Make default** in
**Settings › Household › Models**.

**The assistant fails, or a model is marked *not answering*.** Use **Check** on the model in
**Settings › Household › Models**: it sends one tiny request and shows the provider's own
reason. The usual ones: the key is wrong or has run out of credit (OpenRouter's 401 or 402),
the id is misspelt (404), or a local server is not reachable from the container. To test that
last one:

```bash
docker compose exec luach python -c "import urllib.request; print(urllib.request.urlopen('http://host.docker.internal:11434/v1/models').read()[:200])"
```

`Connection refused` means the model server listens only on `127.0.0.1`
(`OLLAMA_HOST`, above) or a firewall stops containers reaching it.

**The assistant says it added something that is not on the calendar.** The model answered in
prose where it should have called a tool. Run **Try it** on it; pick a model that scores
*good*.

**The iPhone app says `Use an https:// address`.** It signs in only over `https://`. Use your
public address from step 5, not `http://` or a home network address. If it says the address
cannot be reached or is not a luach, open the same address in Safari on the phone: a
certificate warning there means the certificate is not one the phone trusts.

**Gmail disconnects every week.** The Google OAuth app is in **Testing**, and Google expires
its grants after seven days. Publish it (see [Gmail](#each-members-own-gmail)); members then
reconnect once. The log says `mail: Google refused member 3's grant (invalid_grant); it is
forgotten` when it happens, and the member is told.

**The calendar does not keep events.**

- The log says `calendar: LUACH_CALENDAR=fake keeps events in memory only, and every one is
  LOST when luach restarts`: set `LUACH_CALENDAR=local` (or remove the line), and
  `docker compose up -d`.
- luach will not start, with `luach cannot start: LUACH_CALENDAR=google, but no Google
  credential is set`: the key files are not where `.env` says, or the `./credentials` volume
  line is still commented in `docker-compose.yml`.
- `Permission denied` on `/run/luach/...`: the files are not readable by uid 10001
  (`sudo chown -R 10001:10001 credentials`).
- With a service account, creating events fails and the log shows Google's `HttpError 403`,
  `You need to have writer access to this calendar`: share the calendar with the service
  account's address with **Make changes to events**. A `404` means `LUACH_GOOGLE_CALENDAR_ID`
  is wrong.
- With the owner's grant, the agenda stops loading after a week and the log shows
  `invalid_grant`: the Google app is in **Testing**. Publish it, make a new refresh token
  (step 5 of that section), and replace `google-oauth-tokens.json`.

**Web search: the assistant says it cannot search.** `docker compose logs searxng | tail`:
if every engine says `CAPTCHA` or `too many requests`, the engines are refusing this server's
address for now; a Brave Search API key avoids that. If luach's log says
`the search engine answered HTTP 403`, the JSON format is not enabled in
`searxng/settings.yml`.

**The page is blank, or old, after an upgrade.** Reload it once; the web app updates itself,
and a paired wall board reloads by itself after a minute nobody touches it.

## Without Docker Compose

The image runs anywhere containers do (Kubernetes, Nomad, Podman, a NAS's own container UI).
It runs as uid 10001 and listens on port 8004. It needs:

- a Postgres 16 with the `vector` extension available, in `LUACH_DATABASE_URL`
  (`postgresql://user:password@host:5432/dbname`). The role must own the database. For memory,
  point `LUACH_MEMORY_DSN` at the same database; on first use luach runs
  `CREATE EXTENSION IF NOT EXISTS vector` and creates its table, so the role needs the right
  to do that, or the extension created beforehand;
- `luach-migrate` run with the same `LUACH_DATABASE_URL` before each start of a new version
  (an init container, a pre-start hook, or by hand). The app refuses to start on a schema it
  does not know, and says so in its log;
- a writable volume at `/var/lib/luach`, owned by uid 10001;
- a writable `/tmp`. The root filesystem may be read-only;
- `LUACH_TRUSTED_PROXIES` listing the network your ingress or proxy connects from.

Run one copy of the app per database. The background loops (reminders, mail, busy feeds) run
in one copy at a time, guarded by a lock file in `/var/lib/luach`, so nothing is gained by
running more.

Secrets can be plain environment variables, or files: if `CREDENTIALS_DIRECTORY` is set, luach
reads `KEY=value` lines from a `secrets.env` there (values already in the environment win), and
uses `google-sa.json`, `google-oauth-client.json` and `google-oauth-tokens.json` from the same
directory for `LUACH_GOOGLE_SA_KEY`, `LUACH_GOOGLE_OAUTH_CLIENT` and
`LUACH_GOOGLE_OAUTH_TOKENS` when those are unset. This is systemd's credentials directory, and
works the same with a mounted secret.
