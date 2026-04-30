export default {
  async fetch(request, env) {

    if (request.method !== "GET") {
      return new Response("Method not allowed", { status: 405 });
    }

    const url    = new URL(request.url);
    const bvid   = url.searchParams.get("bvid");
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

    const biliHeaders = {
      "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
      "Referer":         `https://www.bilibili.com/video/${bvid}`,
      "Origin":          "https://www.bilibili.com",
      "Accept":          "application/json, text/plain, */*",
      "Accept-Language": "zh-CN,zh;q=0.9",
      "Cookie":          "buvid3=ABC123; b_nut=1700000000; CURRENT_FNVAL=4048; buvid4=DEF456",
    };

    try {
      // Get basic video info only (title, cover, cid)
      const infoResp = await fetch(
        `https://api.bilibili.com/x/web-interface/view?bvid=${bvid}`,
        { headers: biliHeaders }
      );

      const infoText = await infoResp.text();

      if (infoText.trim().startsWith("<")) {
        // Still blocked — just return page URL for yt-dlp
        return new Response(JSON.stringify({
          bvid,
          title:        "",
          cover:        "",
          download_url: null,
          fallback:     true,
          page_url:     `https://www.bilibili.com/video/${bvid}`
        }), {
          status: 200,
          headers: { "Content-Type": "application/json" }
        });
      }

      const infoData = JSON.parse(infoText);

      // Even if code != 0, still return page_url so yt-dlp can try
      const title = infoData?.data?.title || "";
      const cover = infoData?.data?.pic   || "";

      return new Response(JSON.stringify({
        bvid,
        title,
        cover,
        download_url: null,
        fallback:     true,
        page_url:     `https://www.bilibili.com/video/${bvid}`
      }), {
        status: 200,
        headers: {
          "Content-Type":                "application/json",
          "Access-Control-Allow-Origin": "*"
        }
      });

    } catch (err) {
      // Always return something so yt-dlp can still try
      return new Response(JSON.stringify({
        bvid,
        title:        "",
        cover:        "",
        download_url: null,
        fallback:     true,
        page_url:     `https://www.bilibili.com/video/${bvid}`
      }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      });
    }
  }
};
