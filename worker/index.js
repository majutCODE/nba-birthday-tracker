/**
 * Precise scheduler for the NBA birthday tweet.
 *
 * GitHub's own cron is best-effort: measured over 60 runs it delayed the
 * day's later runs by 3 to 6.7 hours, which is how a tweet meant for
 * lunchtime ET went out at 3am UK. Cloudflare cron triggers actually fire
 * on time, so this Worker is the alarm clock and GitHub Actions stays the
 * thing that does the work.
 *
 * It identifies itself with source=cron so the bot applies its normal
 * posting-window and once-per-day guards, rather than treating this as a
 * human pressing "Run workflow".
 */

const OWNER = "majutCODE";
const REPO = "nba-birthday-tracker";
const WORKFLOW = "tweet-birthdays.yml";

async function dispatch(env) {
  const res = await fetch(
    `https://api.github.com/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW}/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        // GitHub rejects API requests without a User-Agent.
        "User-Agent": "nba-birthday-cron",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ ref: "main", inputs: { source: "cron" } }),
    },
  );

  // A successful dispatch is 204 No Content.
  if (res.status !== 204) {
    const body = await res.text();
    throw new Error(`GitHub dispatch failed: ${res.status} ${body}`);
  }
  return "dispatched";
}

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(
      dispatch(env).then(
        (r) => console.log(r),
        (e) => console.error(e.message),
      ),
    );
  },

  // Manual check: visiting the Worker URL triggers the same dispatch, so you
  // can confirm the token works without waiting for the cron.
  async fetch(request, env) {
    try {
      await dispatch(env);
      return new Response("Dispatched workflow.\n");
    } catch (e) {
      return new Response(`${e.message}\n`, { status: 500 });
    }
  },
};
