export default {
  async fetch(request) {
    const url = new URL(request.url);
    // Slug from path: /wilma-s → wilma-s.html
    const slug = url.pathname.replace(/^\/+/, "").replace(/\.html$/, "");
    if (!slug || slug.includes("..") || slug.includes("/")) {
      return new Response("Not found", { status: 404 });
    }
    const origin = "https://ycsauzlqsjjbusugshpz.supabase.co/storage/v1/object/public/mockups/" + slug + ".html";
    const resp = await fetch(origin);
    if (!resp.ok) return new Response("Preview not found", { status: 404 });
    const html = await resp.text();
    return new Response(html, {
      headers: {
        "Content-Type": "text/html; charset=utf-8",
        "Cache-Control": "public, max-age=300",
      },
    });
  },
};
