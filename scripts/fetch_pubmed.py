#!/usr/bin/env python3
"""
Fetch recent surgical research from PubMed (NCBI E-utilities) and write a
static data file (intelligence/evidence.json) for the Haarks Intelligence
"Live Surgical Evidence" feed.

- No API key required and none is used; NCBI E-utilities is a public service.
- We store only citation METADATA (title, authors, journal, date, PMID, DOI)
  plus a short neutral Haarks-written line. We do NOT copy abstracts or
  article text. Every item links to its original PubMed record.
- Runs on GitHub Actions (stdlib only) or locally. If the fetch fails or
  returns nothing, the existing evidence.json is left untouched.
"""
import json, sys, time, urllib.parse, urllib.request, datetime, os

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
TOOL = "haarksclinic-site"
EMAIL = "support@haarksclinic.com"
OUT = os.path.join(os.path.dirname(__file__), "..", "intelligence", "evidence.json")

# Category -> PubMed query. Categories align with Haarks' verified specialty
# structure plus the Haarks Intelligence coverage areas. Not every specialty.
CATEGORIES = [
    ("Surgical AI",            "artificial intelligence surgery"),
    ("Robotics",               "robotic surgery"),
    ("Orthopaedics",           "arthroplasty outcomes"),
    ("General Surgery",        "laparoscopic surgery outcomes"),
    ("Surgical Oncology",      "surgical oncology"),
    ("Neurosurgery",           "neurosurgery outcomes"),
    ("Cardiovascular Surgery", "cardiac surgery outcomes"),
    ("Urology",                "urologic surgery"),
]
PER_CATEGORY = 2


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": TOOL})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def esearch(term):
    q = urllib.parse.urlencode({
        "db": "pubmed", "term": term, "sort": "date", "retmax": PER_CATEGORY,
        "retmode": "json", "tool": TOOL, "email": EMAIL,
    })
    return _get(f"{EUTILS}/esearch.fcgi?{q}").get("esearchresult", {}).get("idlist", [])


def esummary(ids):
    q = urllib.parse.urlencode({
        "db": "pubmed", "id": ",".join(ids), "retmode": "json",
        "tool": TOOL, "email": EMAIL,
    })
    return _get(f"{EUTILS}/esummary.fcgi?{q}").get("result", {})


def first_author(rec):
    auth = [a.get("name") for a in rec.get("authors", []) if a.get("name")]
    if not auth:
        return ""
    return auth[0] + (" et al." if len(auth) > 1 else "")


def doi_of(rec):
    for x in rec.get("articleids", []):
        if x.get("idtype") == "doi":
            return x.get("value")
    return ""


def build():
    id_to_cat, order = {}, []
    for cat, term in CATEGORIES:
        try:
            for pmid in esearch(term):
                if pmid not in id_to_cat:
                    id_to_cat[pmid] = cat
                    order.append(pmid)
        except Exception as e:
            print(f"esearch failed for {cat}: {e}", file=sys.stderr)
        time.sleep(0.4)  # stay well under NCBI rate limits

    if not order:
        print("No PubMed IDs fetched; leaving evidence.json unchanged.", file=sys.stderr)
        return None

    try:
        res = esummary(order)
    except Exception as e:
        print(f"esummary failed: {e}", file=sys.stderr)
        return None

    items = []
    for pmid in order:
        rec = res.get(pmid)
        if not rec or rec.get("error"):
            continue
        journal = rec.get("fulljournalname") or rec.get("source") or ""
        pubdate = rec.get("pubdate") or rec.get("epubdate") or ""
        fa = first_author(rec)
        title = (rec.get("title") or "").rstrip(".")
        cat = id_to_cat.get(pmid, "Surgery")
        summary = f"Published in {journal} ({pubdate})." if journal else ""
        if fa:
            summary = (f"{fa} " if summary else fa) + summary
        summary = (summary + " Read the abstract and full citation on PubMed.").strip()
        items.append({
            "title": title,
            "authors": fa,
            "journal": journal,
            "pubdate": pubdate,
            "pmid": pmid,
            "doi": doi_of(rec),
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "category": cat,
            "summary": summary,
        })

    if not items:
        return None

    return {
        "source": "PubMed / NCBI (E-utilities)",
        "note": "Citation metadata only; summaries are short neutral Haarks lines. No abstracts or article text are reproduced. Each item links to its PubMed record.",
        "updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "items": items,
    }


def main():
    data = build()
    if not data:
        print("No data produced; not writing.", file=sys.stderr)
        sys.exit(1)
    path = os.path.abspath(OUT)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"Wrote {len(data['items'])} items to {path}")


if __name__ == "__main__":
    main()
