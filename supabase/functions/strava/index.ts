import { serve } from "https://deno.land/std@0.168.0/http/server.ts";

const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

serve(async (req) => {
  if (req.method === "OPTIONS")
    return new Response("ok", { headers: cors });

  try {
    const body = await req.json();
    const { action, client_id, client_secret, code, refresh_token, access_token, after } =
      body;

    /* ── 1. Exchange auth code for tokens ─────────────── */
    if (action === "exchange") {
      const secret = client_secret || Deno.env.get("STRAVA_CLIENT_SECRET");
      const res = await fetch("https://www.strava.com/oauth/token", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          client_id,
          client_secret: secret,
          code,
          grant_type: "authorization_code",
        }),
      });
      return json(await res.json());
    }

    /* ── 2. Refresh expired access token ──────────────── */
    if (action === "refresh") {
      const secret = client_secret || Deno.env.get("STRAVA_CLIENT_SECRET");
      const res = await fetch("https://www.strava.com/oauth/token", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          client_id,
          client_secret: secret,
          refresh_token,
          grant_type: "refresh_token",
        }),
      });
      return json(await res.json());
    }

    /* ── 3. Fetch recent activities ───────────────────── */
    if (action === "activities") {
      const url = new URL("https://www.strava.com/api/v3/athlete/activities");
      url.searchParams.set("per_page", "30");
      if (after) url.searchParams.set("after", String(after));
      const res = await fetch(url, {
        headers: { Authorization: `Bearer ${access_token}` },
      });
      return json(await res.json());
    }

    /* ── 4. Fetch laps for a single activity ──────────── */
    if (action === "laps") {
      const { activity_id } = body;
      const res = await fetch(
        `https://www.strava.com/api/v3/activities/${activity_id}/laps`,
        { headers: { Authorization: `Bearer ${access_token}` } }
      );
      return json(await res.json());
    }

    return json({ error: "Unknown action" }, 400);
  } catch (e) {
    return json({ error: (e as Error).message }, 500);
  }
});

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { ...cors, "Content-Type": "application/json" },
  });
}
