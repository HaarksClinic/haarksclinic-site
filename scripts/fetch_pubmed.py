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

# Category -> (PubMed query, specialty, why-it-matters). Categories align with
# Haarks' verified specialty structure plus the Haarks Intelligence coverage
# areas. Not every specialty. The why-it-matters line is a neutral,
# category-level note (never a claim about the specific article).
CATEGORIES = [
    ("Surgical AI",            "artificial intelligence surgery", "Cross-specialty",         "AI methods are increasingly studied across surgical workflows and decision-support research."),
    ("Robotics",               "robotic surgery",                 "Cross-specialty",         "Robotic-assisted techniques continue to evolve across surgical specialties."),
    ("Orthopaedics",           "arthroplasty outcomes",           "Orthopaedics",            "Reflects ongoing research into orthopaedic techniques and outcomes."),
    ("General Surgery",        "laparoscopic surgery outcomes",   "General Surgery",         "Relevant to evolving general-surgical techniques and outcomes."),
    ("Surgical Oncology",      "surgical oncology",               "Surgical Oncology",       "Relevant to surgical management and outcomes in oncology."),
    ("Neurosurgery",           "neurosurgery outcomes",           "Neurosurgery",            "Reflects ongoing neurosurgical techniques and outcomes research."),
    ("Cardiovascular Surgery", "cardiac surgery outcomes",        "Cardiovascular Surgery",  "Relevant to cardiovascular surgical techniques and outcomes."),
    ("Urology",                "urologic surgery",                "Urology",                 "Relevant to urologic surgical techniques and outcomes."),
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


REQUIRED_FIELDS = ("title", "pmid", "url", "category", "source")
MIN_ITEMS = 4


def build():
    cat_meta = {c[0]: {"query": c[1], "specialty": c[2], "why": c[3]} for c in CATEGORIES}
    id_to_cat, order = {}, []
    for cat, term, _spec, _why in CATEGORIES:
        try:
            for pmid in esearch(term):
                if pmid not in id_to_cat:          # dedupe across categories
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

    now = datetime.datetime.now(datetime.timezone.utc)
    verified = now.strftime("%Y-%m-%d")
    items, seen = [], set()
    for pmid in order:
        rec = res.get(pmid)
        if not rec or rec.get("error") or pmid in seen:
            continue
        seen.add(pmid)
        journal = rec.get("fulljournalname") or rec.get("source") or ""
        pubdate = rec.get("pubdate") or rec.get("epubdate") or ""
        fa = first_author(rec)
        title = (rec.get("title") or "").rstrip(".")
        if not title:
            continue
        cat = id_to_cat.get(pmid, "Surgery")
        meta = cat_meta.get(cat, {"specialty": "Surgery", "why": ""})
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
            "specialty": meta["specialty"],
            "category": cat,
            "summary": summary,
            "whyItMatters": meta["why"],
            "source": "PubMed / NCBI",
            "lastVerified": verified,
        })

    if not items:
        return None

    return {
        "source": "PubMed / NCBI (E-utilities)",
        "note": "Citation metadata only; summaries are short neutral Haarks lines and 'why it matters' is a category-level note. No abstracts or article text are reproduced. Each item links to its PubMed record.",
        "updated": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "items": items,
    }


def validate(data):
    """Reject malformed or empty datasets so a bad run can't overwrite good data."""
    if not isinstance(data, dict):
        return "not an object"
    items = data.get("items")
    if not isinstance(items, list) or len(items) < MIN_ITEMS:
        return f"too few items (<{MIN_ITEMS})"
    seen = set()
    for i, it in enumerate(items):
        for k in REQUIRED_FIELDS:
            if not it.get(k):
                return f"item {i} missing '{k}'"
        if not str(it["url"]).startswith("https://pubmed.ncbi.nlm.nih.gov/"):
            return f"item {i} bad url"
        if it["pmid"] in seen:
            return f"duplicate pmid {it['pmid']}"
        seen.add(it["pmid"])
    return None


def main():
    data = build()
    if not data:
        print("No data produced; leaving existing evidence.json unchanged.", file=sys.stderr)
        sys.exit(1)
    err = validate(data)
    if err:
        print(f"Validation failed ({err}); leaving existing evidence.json unchanged.", file=sys.stderr)
        sys.exit(1)
    path = os.path.abspath(OUT)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"Wrote {len(data['items'])} items to {path}")


if __name__ == "__main__":
    main()
