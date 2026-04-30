// Cloudflare Worker — Full Bilibili Video Proxy
// Fetches video directly through Cloudflare IP (never blocked)
// and streams it back to GitHub Actions

export default {
  async fetch(request, env) {

    const url    = new URL(request.url);
    const secret = url.searchParams.get("secret");

    if (secret !== env.SECRET_KEY) {
      return new Response("Unauthorized", { status: 401 });
    }

    const biliHeaders = {
      "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
      "Accept-Language": "zh-CN,zh;q=0.9",
      "Accept":          "application/json, text/plain, */*",
    };

    // ── MODE 1: Get trending videos ──────────────────────────────────────────
    const action = url.searchParams.get("action");

    if (action === "trending") {
      const count = url.searchParams.get("count") || "20";
      try {
        const resp = await fetch(
          `https://api.bilibili.com/x/web-interface/popular?ps=${count}&pn=1`,
          { headers: { ...biliHeaders, "Referer": "https://www.bilibili.com/" } }
        );
        const data = await resp.json();
        return new Response(JSON.stringify(data), {
          headers: { "Content-Type": "application/json" }
        });
      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), { status: 500 });
      }
    }

    // ── MODE 2: Get video info + download URL ────────────────────────────────
    const bvid = url.searchParams.get("bvid");
    if (!bvid) {
      return new Response(JSON.stringify({ error: "bvid required" }), { status: 400 });
    }

    try {
      // Get cid
      const infoResp = await fetch(
        `https://api.bilibili.com/x/web-interface/view?bvid=${bvid}`,
        { headers: { ...biliHeaders, "Referer": `https://www.bilibili.com/video/${bvid}` } }
      );
      const infoData = await infoResp.json();

      if (infoData.code !== 0) {
        return new Response(JSON.stringify({
          error: "info API failed", code: infoData.code, msg: infoData.message
        }), { status: 500 });
      }

      const cid   = infoData.data.cid;
      const title = infoData.data.title;
      const cover = infoData.data.pic;

      // Get playurl — try multiple quality levels
      let downloadUrl = null;
      for (const qn of [64, 32, 16]) {
        const playResp = await fetch(
          `https://api.bilibili.com/x/player/playurl?bvid=${bvid}&cid=${cid}&qn=${qn}&fnval=0&fnver=0&fourk=0`,
          { headers: { ...biliHeaders, "Referer": `https://www.bilibili.com/video/${bvid}` } }
        );
        const playData = await playResp.json();

        if (playData.code === 0 && playData.data?.durl?.length > 0) {
          downloadUrl = playData.data.durl[0].url;
          break;
        }
      }

      if (!downloadUrl) {
        return new Response(JSON.stringify({
          bvid, title, cover, cid,
          download_url: null,
          page_url: `https://www.bilibili.com/video/${bvid}`
        }), { headers: { "Content-Type": "application/json" } });
      }

      return new Response(JSON.stringify({
        bvid, title, cover, cid,
        download_url: downloadUrl,
        page_url: `https://www.bilibili.com/video/${bvid}`
      }), {
        headers: {
          "Content-Type":                "application/json",
          "Access-Control-Allow-Origin": "*"
        }
      });

    } catch (err) {
      return new Response(JSON.stringify({ error: err.message }), { status: 500 });
    }
  }
};
