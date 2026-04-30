export default {
  async fetch(request, env) {

    if (request.method !== "GET") {
      return new Response("Method not allowed", { status: 405 });
    }

    const url = new URL(request.url);
    const bvid = url.searchParams.get("bvid");
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

    // Headers that trick Bilibili into thinking this is a real browser
    const biliHeaders = {
      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
      "Referer": `https://www.bilibili.com/video/${bvid}`,
      "Origin": "https://www.bilibili.com",
      "Accept": "application/json, text/plain, */*",
      "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
      "Cookie": "buvid3=random123; b_nut=1234567890; CURRENT_FNVAL=4048",
    };

    try {
      // Step 1: Get video cid from bvid
      const infoResp = await fetch(
        `https://api.bilibili.com/x/web-interface/view?bvid=${bvid}`,
        { headers: biliHeaders }
      );

      const infoText = await infoResp.text();

      // Check if response is HTML (blocked)
      if (infoText.trim().startsWith("<")) {
        return new Response(JSON.stringify({
          error: "Bilibili returned HTML — API blocked",
          raw: infoText.substring(0, 200)
        }), { status: 503, headers: { "Content-Type": "application/json" } });
      }

      const infoData = JSON.parse(infoText);

      if (infoData.code !== 0) {
        return new Response(JSON.stringify({
          error: "Bilibili API error",
          code: infoData.code,
          message: infoData.message
        }), { status: 500, headers: { "Content-Type": "application/json" } });
      }

      const cid   = infoData.data.cid;
      const title = infoData.data.title;
      const cover = infoData.data.pic;

      // Step 2: Get playable stream URL
      const playResp = await fetch(
        `https://api.bilibili.com/x/player/playurl?bvid=${bvid}&cid=${cid}&qn=80&fnval=0&fnver=0&fourk=0`,
        { headers: { ...biliHeaders, "Referer": `https://www.bilibili.com/video/${bvid}` } }
      );

      const playText = await playResp.text();

      if (playText.trim().startsWith("<")) {
        // Fallback — return just the video page URL for yt-dlp to handle
        return new Response(JSON.stringify({
          bvid,
          title,
          cover,
          cid,
          download_url: null,
          fallback: true,
          page_url: `https://www.bilibili.com/video/${bvid}`
        }), { status: 200, headers: { "Content-Type": "application/json" } });
      }

      const playData = JSON.parse(playText);

      if (playData.code !== 0) {
        // Fallback to page URL
        return new Response(JSON.stringify({
          bvid,
          title,
          cover,
          cid,
          download_url: null,
          fallback: true,
          page_url: `https://www.bilibili.com/video/${bvid}`
        }), { status: 200, headers: { "Content-Type": "application/json" } });
      }

      const durl = playData.data?.durl;
      if (!durl || durl.length === 0) {
        return new Response(JSON.stringify({
          bvid,
          title,
          cover,
          cid,
          download_url: null,
          fallback: true,
          page_url: `https://www.bilibili.com/video/${bvid}`
        }), { status: 200, headers: { "Content-Type": "application/json" } });
      }

      return new Response(JSON.stringify({
        bvid,
        title,
        cover,
        cid,
        download_url:  durl[0].url,
        backup_urls:   durl[0].backup_url || [],
        size:          durl[0].size,
        duration:      playData.data.timelength,
        fallback:      false,
        page_url:      `https://www.bilibili.com/video/${bvid}`
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

