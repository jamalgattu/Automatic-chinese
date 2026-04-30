// Cloudflare Worker — Bilibili URL Resolver
// Fetches direct video info from Bilibili API using Cloudflare's trusted IPs

export default {
  async fetch(request, env) {

    // Only allow GET requests
    if (request.method !== "GET") {
      return new Response("Method not allowed", { status: 405 });
    }

    const url = new URL(request.url);
    const bvid = url.searchParams.get("bvid");

    // Simple security — require a secret key so only your pipeline can use it
    const secret = url.searchParams.get("secret");
    if (secret !== env.SECRET_KEY) {
      return new Response("Unauthorized", { status: 401 });
    }

    if (!bvid) {
      return new Response(JSON.stringify({ error: "bvid param required" }), {
        status: 400,
        headers: { "Content-Type": "application/json" }
      });
    }

    try {
      // Step 1: Get video info (cid) from bvid
      const infoResp = await fetch(
        `https://api.bilibili.com/x/web-interface/view?bvid=${bvid}`,
        {
          headers: {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.bilibili.com/",
            "Origin": "https://www.bilibili.com"
          }
        }
      );
      const infoData = await infoResp.json();

      if (infoData.code !== 0) {
        return new Response(JSON.stringify({
          error: "Bilibili API error",
          code: infoData.code,
          message: infoData.message
        }), { status: 500, headers: { "Content-Type": "application/json" } });
      }

      const cid   = infoData.data.cid;
      const title = infoData.data.title;
      const desc  = infoData.data.desc;
      const cover = infoData.data.pic;

      // Step 2: Get playable stream URLs
      const playResp = await fetch(
        `https://api.bilibili.com/x/player/playurl?bvid=${bvid}&cid=${cid}&qn=80&fnval=0&fnver=0&fourk=0`,
        {
          headers: {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.bilibili.com/video/${bvid}",
            "Origin": "https://www.bilibili.com"
          }
        }
      );
      const playData = await playResp.json();

      if (playData.code !== 0) {
        return new Response(JSON.stringify({
          error: "Playurl API error",
          code: playData.code,
          message: playData.message
        }), { status: 500, headers: { "Content-Type": "application/json" } });
      }

      // Extract video URLs (pick best quality available)
      const durl = playData.data.durl;
      if (!durl || durl.length === 0) {
        return new Response(JSON.stringify({ error: "No download URLs found" }), {
          status: 404,
          headers: { "Content-Type": "application/json" }
        });
      }

      // Return the best URL + metadata
      return new Response(JSON.stringify({
        bvid,
        title,
        desc,
        cover,
        cid,
        download_url: durl[0].url,
        backup_urls:  durl[0].backup_url || [],
        size:         durl[0].size,
        duration:     playData.data.timelength
      }), {
        status: 200,
        headers: {
          "Content-Type": "application/json",
          "Access-Control-Allow-Origin": "*"
        }
      });

    } catch (err) {
      return new Response(JSON.stringify({ error: err.message }), {
        status: 500,
        headers: { "Content-Type": "application/json" }
      });
    }
  }
};

