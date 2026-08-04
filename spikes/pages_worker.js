// Cloudflare Pages advanced-mode worker (_worker.js): Google OAuth gate for
// /admin/*, everything else served statically via env.ASSETS.
//
// Flow: /admin/auth/login -> Google consent (authorization code + PKCE) ->
// /admin/auth/callback -> session cookie -> guarded /admin/* serves via
// env.ASSETS. Sessions are stateless HMAC-SHA256-signed cookies (expiry inside
// the payload), so there is no KV or database to operate.
//
// Secrets (Pages project secrets, dashboard or wrangler):
//   GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, SESSION_SECRET, ADMIN_EMAILS
// Google OAuth client: authorized redirect URI must be
//   https://<project>.pages.dev/admin/auth/callback
//
// Plain ESM, zero imports: deployable as a raw _worker.js via the Pages
// Direct Upload API with no bundling step.

const AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth";
const TOKEN_URL = "https://oauth2.googleapis.com/token";
const SESSION_COOKIE = "sf_session";
const STATE_COOKIE = "sf_oauth";
const SESSION_TTL_S = 7 * 24 * 3600;
const STATE_TTL_S = 600;
const ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";

// --- pure helpers (exported for the bun smoke test) -------------------------

export function b64url(bytes) {
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function b64urlToBytes(s) {
  const b64 = s.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (s.length % 4)) % 4);
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

export function enc(str) {
  return new TextEncoder().encode(str);
}

export function randomToken(n) {
  const a = new Uint8Array(n);
  crypto.getRandomValues(a);
  let out = "";
  for (const b of a) out += ALPHABET[b % ALPHABET.length];
  return out;
}

export async function sha256B64(str) {
  const digest = await crypto.subtle.digest("SHA-256", enc(str));
  return b64url(new Uint8Array(digest));
}

export async function hmacB64(data, secret) {
  const key = await crypto.subtle.importKey("raw", enc(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", key, enc(data));
  return b64url(new Uint8Array(sig));
}

export async function sign(payload, secret) {
  const body = b64url(enc(JSON.stringify(payload)));
  return `${body}.${await hmacB64(body, secret)}`;
}

export async function verify(packed, secret, nowSec) {
  const dot = packed.indexOf(".");
  if (dot <= 0) return null;
  const body = packed.slice(0, dot);
  const sig = packed.slice(dot + 1);
  if (sig !== (await hmacB64(body, secret))) return null;
  try {
    const payload = JSON.parse(new TextDecoder().decode(b64urlToBytes(body)));
    if (payload.exp && payload.exp < nowSec) return null;
    return payload;
  } catch {
    return null;
  }
}

export function decodeJwtPayload(jwt) {
  const parts = jwt.split(".");
  if (parts.length !== 3) throw new Error("malformed id_token");
  return JSON.parse(new TextDecoder().decode(b64urlToBytes(parts[1])));
}

export function allowedEmail(email, env) {
  const list = (env.ADMIN_EMAILS || "")
    .split(",")
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean);
  return Boolean(email) && list.includes(email.toLowerCase());
}

export function buildLoginUrl({ clientId, redirectUri, state, challenge }) {
  const p = new URLSearchParams({
    client_id: clientId,
    redirect_uri: redirectUri,
    response_type: "code",
    scope: "openid email",
    state,
    code_challenge: challenge,
    code_challenge_method: "S256",
    access_type: "online",
    prompt: "select_account",
  });
  return `${AUTH_URL}?${p}`;
}

export function readCookie(request, name) {
  const header = request.headers.get("cookie") || "";
  for (const part of header.split(";")) {
    const eq = part.indexOf("=");
    if (eq > 0 && part.slice(0, eq).trim() === name) return part.slice(eq + 1).trim();
  }
  return null;
}

export function cookieHeader(name, value, maxAge, path = "/") {
  return `${name}=${value}; Path=${path}; HttpOnly; SameSite=Lax; Max-Age=${maxAge}`;
}

// --- request handling -------------------------------------------------------

function configError(env) {
  if (!env.GOOGLE_CLIENT_ID || !env.GOOGLE_CLIENT_SECRET || !env.SESSION_SECRET || !env.ADMIN_EMAILS) {
    return "worker is missing a required secret: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, SESSION_SECRET, ADMIN_EMAILS";
  }
  return null;
}

export async function handleStatus(request, env) {
  const now = Math.floor(Date.now() / 1000);
  const session = readCookie(request, SESSION_COOKIE);
  const payload = session ? await verify(session, env.SESSION_SECRET, now) : null;
  if (payload && allowedEmail(payload.email, env)) {
    return new Response(JSON.stringify({ logged_in: true, email: payload.email }), {
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
    });
  }
  return new Response(JSON.stringify({ logged_in: false }), {
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
  });
}

export async function handleLogin(request, env) {
  const missing = configError(env);
  if (missing) return new Response(missing, { status: 500 });
  const verifier = randomToken(48);
  const state = randomToken(24);
  const now = Math.floor(Date.now() / 1000);
  const stateCookie = await sign({ v: verifier, s: state, exp: now + STATE_TTL_S }, env.SESSION_SECRET);
  const redirectUri = new URL(request.url).origin + "/admin/auth/callback";
  const location = buildLoginUrl({
    clientId: env.GOOGLE_CLIENT_ID,
    redirectUri,
    state,
    challenge: await sha256B64(verifier),
  });
  return new Response(null, {
    status: 302,
    headers: {
      Location: location,
      "Set-Cookie": cookieHeader(STATE_COOKIE, stateCookie, STATE_TTL_S, "/admin"),
    },
  });
}

export async function handleCallback(request, env) {
  const missing = configError(env);
  if (missing) return new Response(missing, { status: 500 });
  const url = new URL(request.url);
  const state = url.searchParams.get("state") || "";
  const code = url.searchParams.get("code") || "";
  const now = Math.floor(Date.now() / 1000);
  const stateCookie = readCookie(request, STATE_COOKIE);
  const stored = stateCookie ? await verify(stateCookie, env.SESSION_SECRET, now) : null;
  if (!stored || stored.s !== state) {
    return new Response("OAuth state mismatch — start the login again.", { status: 400 });
  }

  const tokenResp = await fetch(TOKEN_URL, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      code,
      client_id: env.GOOGLE_CLIENT_ID,
      client_secret: env.GOOGLE_CLIENT_SECRET,
      redirect_uri: url.origin + "/admin/auth/callback",
      code_verifier: stored.v,
      grant_type: "authorization_code",
    }),
  });
  const tokenJson = await tokenResp.json();
  if (!tokenResp.ok || !tokenJson.id_token) {
    return new Response(`Google token exchange failed (${tokenResp.status}).`, { status: 502 });
  }

  let idPayload;
  try {
    idPayload = decodeJwtPayload(tokenJson.id_token);
  } catch {
    return new Response("Malformed id_token from Google.", { status: 502 });
  }
  if (!idPayload.email_verified) return new Response("Google email is not verified.", { status: 403 });
  if (!allowedEmail(idPayload.email, env)) {
    return new Response(`Access denied for ${idPayload.email || "unknown"} — not in ADMIN_EMAILS.`, { status: 403 });
  }

  const session = await sign(
    { sub: idPayload.sub, email: idPayload.email, exp: now + SESSION_TTL_S },
    env.SESSION_SECRET
  );
return new Response(null, {
      status: 302,
      headers: {
        Location: new URL("/admin/", request.url).href,
        "Set-Cookie": cookieHeader(SESSION_COOKIE, session, SESSION_TTL_S),
      },
    });
}

export async function handleLogout(request, env) {
  return new Response(null, {
    status: 302,
    headers: {
      Location: "/",
      "Set-Cookie": cookieHeader(SESSION_COOKIE, "", 0),
    },
  });
}

export async function handleAdmin(request, env) {
  const now = Math.floor(Date.now() / 1000);
  const session = readCookie(request, SESSION_COOKIE);
  const payload = session ? await verify(session, env.SESSION_SECRET, now) : null;
  if (!payload || !allowedEmail(payload.email, env)) {
    return Response.redirect(new URL("/admin/auth/login", request.url).href, 302);
  }
  return env.ASSETS.fetch(request);
}

export default {
  async fetch(request, env) {
    const pathname = new URL(request.url).pathname;
    if (pathname === "/admin/auth/status") return handleStatus(request, env);
    if (pathname === "/admin/auth/login") return handleLogin(request, env);
    if (pathname === "/admin/auth/logout") return handleLogout(request, env);
    if (pathname === "/admin/auth/callback") return handleCallback(request, env);
    if (pathname.startsWith("/admin/")) return handleAdmin(request, env);
    return env.ASSETS.fetch(request);
  },
};
