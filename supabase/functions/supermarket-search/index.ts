import { serve } from "https://deno.land/std@0.168.0/http/server.ts";

const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

interface Product {
  name: string;
  brand: string;
  store: string;
  serve: number;
  kcal: number;
  prot: number;
  carb: number;
  fat: number;
  img: string;
  url: string;
}

serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });

  try {
    const { query, stores } = await req.json();
    if (!query) return json({ error: "Missing query" }, 400);

    const storeList: string[] = stores || ["woolworths", "coles"];
    const results: Product[] = [];

    const promises: Promise<void>[] = [];

    if (storeList.includes("woolworths")) {
      promises.push(searchWoolworths(query).then((r) => results.push(...r)));
    }
    if (storeList.includes("coles")) {
      promises.push(searchColes(query).then((r) => results.push(...r)));
    }

    await Promise.allSettled(promises);
    return json({ results });
  } catch (e) {
    return json({ error: (e as Error).message }, 500);
  }
});

/* ── Woolworths ──────────────────────────────────── */
async function searchWoolworths(query: string): Promise<Product[]> {
  try {
    const res = await fetch(
      "https://www.woolworths.com.au/apis/ui/Search/products",
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "User-Agent":
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
          Accept: "application/json",
        },
        body: JSON.stringify({
          SearchTerm: query,
          PageNumber: 1,
          PageSize: 8,
          SortType: "TraderRelevance",
          Location: `/shop/search/products?searchTerm=${encodeURIComponent(query)}`,
        }),
      }
    );

    if (!res.ok) {
      console.error("Woolworths API error:", res.status);
      return [];
    }

    const data = await res.json();
    const products: Product[] = [];

    for (const item of data.Products || []) {
      const p = item.Products?.[0] || item;
      if (!p.Name) continue;

      // Try to extract nutrition from the product's additional attributes
      const nutrition = parseWoolworthsNutrition(p);

      products.push({
        name: p.Name || "",
        brand: p.Brand || "",
        store: "Woolworths",
        serve: nutrition.serve || p.PackageSize ? parsePackageSize(p.PackageSize) : 100,
        kcal: nutrition.kcal,
        prot: nutrition.prot,
        carb: nutrition.carb,
        fat: nutrition.fat,
        img: p.MediumImageFile || p.SmallImageFile || "",
        url: p.Stockcode
          ? `https://www.woolworths.com.au/shop/productdetails/${p.Stockcode}`
          : "",
      });
    }

    return products;
  } catch (e) {
    console.error("Woolworths search error:", e);
    return [];
  }
}

function parseWoolworthsNutrition(p: any) {
  const result = { serve: 100, kcal: 0, prot: 0, carb: 0, fat: 0 };

  // Woolworths sometimes includes AdditionalAttributes with nutrition info
  const attrs = p.AdditionalAttributes || {};
  const ni = attrs.nutritionalinformation || attrs.NutritionalInformation;

  if (ni && typeof ni === "string") {
    try {
      const info = JSON.parse(ni);
      // Parse the NIP (Nutrition Information Panel)
      for (const row of info || []) {
        const name = (row.name || "").toLowerCase();
        const per100 = parseFloat(row.values?.[1]?.value || row.per100g || "0");
        const perServe = parseFloat(row.values?.[0]?.value || row.perServing || "0");

        if (name.includes("energy") && name.includes("kcal")) {
          result.kcal = Math.round(per100 || perServe);
        } else if (name.includes("energy") && !name.includes("kcal")) {
          // kJ → kcal
          const kj = per100 || perServe;
          if (kj > 100) result.kcal = Math.round(kj / 4.184);
        } else if (name.includes("protein")) {
          result.prot = +(per100 || perServe).toFixed(1);
        } else if (
          name.includes("carbohydrate") &&
          !name.includes("sugar")
        ) {
          result.carb = +(per100 || perServe).toFixed(1);
        } else if (name.includes("fat") && !name.includes("saturated")) {
          result.fat = +(per100 || perServe).toFixed(1);
        }
      }
    } catch {
      // not JSON
    }
  }

  // Fallback: try RichDescription HTML parsing
  const rd =
    p.RichDescription || p.AdditionalAttributes?.description || "";
  if (rd && !result.kcal) {
    const extracted = extractNutritionFromHtml(rd);
    if (extracted.kcal) Object.assign(result, extracted);
  }

  return result;
}

/* ── Coles ───────────────────────────────────────── */
async function searchColes(query: string): Promise<Product[]> {
  try {
    // Coles search page returns products; we fetch the HTML and extract
    const searchUrl = `https://www.coles.com.au/search/products?q=${encodeURIComponent(query)}`;
    const res = await fetch(searchUrl, {
      headers: {
        "User-Agent":
          "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        Accept: "text/html",
      },
    });

    if (!res.ok) {
      console.error("Coles search error:", res.status);
      return [];
    }

    const html = await res.text();
    const products: Product[] = [];

    // Extract product data from Next.js __NEXT_DATA__ script tag
    const nextDataMatch = html.match(
      /<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)<\/script>/
    );
    if (nextDataMatch) {
      try {
        const nextData = JSON.parse(nextDataMatch[1]);
        const searchResults =
          nextData?.props?.pageProps?.searchResults?.results ||
          nextData?.props?.pageProps?.results ||
          [];

        for (const item of searchResults.slice(0, 8)) {
          const p = item._source || item;
          if (!p.name) continue;

          // Extract nutrition from the product data if available
          const nutrition = parseColesNutrition(p);
          const sizeMatch = (p.name || "").match(/(\d+)\s*[gG]/);

          products.push({
            name: p.name || "",
            brand: p.brand || "",
            store: "Coles",
            serve: nutrition.serve || (sizeMatch ? parseInt(sizeMatch[1]) : 100),
            kcal: nutrition.kcal,
            prot: nutrition.prot,
            carb: nutrition.carb,
            fat: nutrition.fat,
            img: p.imageUris?.[0]?.uri
              ? `https://shop.coles.com.au${p.imageUris[0].uri}`
              : "",
            url: p.id
              ? `https://www.coles.com.au/product/${p.slug || p.id}`
              : "",
          });
        }
      } catch (e) {
        console.error("Coles NEXT_DATA parse error:", e);
      }
    }

    // Fallback: parse product links from HTML
    if (products.length === 0) {
      const productRegex =
        /href="\/product\/([^"]+)"[^>]*>[\s\S]*?<h2[^>]*>([^<]+)<\/h2>/g;
      let match;
      let count = 0;
      while ((match = productRegex.exec(html)) !== null && count < 8) {
        const slug = match[1];
        const name = match[2].trim();
        const sizeMatch = name.match(/(\d+)\s*[gG]/);

        products.push({
          name,
          brand: "",
          store: "Coles",
          serve: sizeMatch ? parseInt(sizeMatch[1]) : 100,
          kcal: 0,
          prot: 0,
          carb: 0,
          fat: 0,
          img: "",
          url: `https://www.coles.com.au/product/${slug}`,
        });
        count++;
      }
    }

    return products;
  } catch (e) {
    console.error("Coles search error:", e);
    return [];
  }
}

function parseColesNutrition(p: any) {
  const result = { serve: 100, kcal: 0, prot: 0, carb: 0, fat: 0 };

  const nip = p.nutritionalInformation || p.nutritionInformation || [];
  if (Array.isArray(nip)) {
    for (const row of nip) {
      const name = (row.name || "").toLowerCase();
      const val = parseFloat(row.per100g || row.values?.[1] || "0");

      if (name.includes("energy")) {
        result.kcal = val > 400 ? Math.round(val / 4.184) : Math.round(val);
      } else if (name.includes("protein")) {
        result.prot = +val.toFixed(1);
      } else if (name.includes("carbohydrate") && !name.includes("sugar")) {
        result.carb = +val.toFixed(1);
      } else if (name.includes("fat") && !name.includes("saturated")) {
        result.fat = +val.toFixed(1);
      }
    }
  }

  return result;
}

/* ── Utilities ───────────────────────────────────── */
function parsePackageSize(s: string | undefined): number {
  if (!s) return 100;
  const match = s.match(/(\d+)\s*[gG]/);
  return match ? parseInt(match[1]) : 100;
}

function extractNutritionFromHtml(html: string) {
  const result = { kcal: 0, prot: 0, carb: 0, fat: 0, serve: 100 };
  const text = html.replace(/<[^>]+>/g, " ").replace(/&nbsp;/g, " ");

  // Try to find energy in kJ and convert
  const energyMatch = text.match(
    /energy[:\s]*(\d[\d,.]*)\s*kj/i
  );
  if (energyMatch) {
    result.kcal = Math.round(
      parseFloat(energyMatch[1].replace(",", "")) / 4.184
    );
  }

  const protMatch = text.match(/protein[:\s]*(\d[\d,.]*)\s*g/i);
  if (protMatch) result.prot = parseFloat(protMatch[1].replace(",", ""));

  const carbMatch = text.match(/carbohydrate[s]?[:\s]*(\d[\d,.]*)\s*g/i);
  if (carbMatch) result.carb = parseFloat(carbMatch[1].replace(",", ""));

  const fatMatch = text.match(
    /(?:total\s+)?fat[:\s]*(\d[\d,.]*)\s*g/i
  );
  if (fatMatch) result.fat = parseFloat(fatMatch[1].replace(",", ""));

  return result;
}

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { ...cors, "Content-Type": "application/json" },
  });
}
