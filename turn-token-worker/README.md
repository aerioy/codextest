# TURN Token Worker (Cloudflare)

This Worker returns ICE server config at `GET /turn` so TURN credentials stay out of the frontend source.

## 1. Authenticate Wrangler

```bash
cd turn-token-worker
wrangler login
```

## 2. Configure Worker vars (non-secret)

Edit `wrangler.toml` as needed:
- `ALLOWED_ORIGIN` (your site origin)
- `TURN_URLS`
- `STUN_URLS`

## 3. Set secrets (recommended)

Use one of these modes:

- Static credentials mode:
  - `TURN_USERNAME`
  - `TURN_CREDENTIAL`

- REST-HMAC mode (if your TURN provider supports shared-secret auth):
  - `TURN_SHARED_SECRET`
  - optional `TURN_USERNAME_PREFIX`

Set secrets:

```bash
wrangler secret put TURN_USERNAME
wrangler secret put TURN_CREDENTIAL
```

Or shared-secret mode:

```bash
wrangler secret put TURN_SHARED_SECRET
wrangler secret put TURN_USERNAME_PREFIX
```

## 4. Deploy

```bash
wrangler deploy
```

Copy the deployed URL and append `/turn`, for example:

`https://ink-soccer-turn-token.<subdomain>.workers.dev/turn`

## 5. Wire frontend

In both files, set:
- `index.html`
- `webgl_ink_soccer_webrtc.html`

Set:

```js
const TURN_TOKEN_ENDPOINT = "https://...workers.dev/turn";
```

Then push to GitHub Pages.
