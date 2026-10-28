#!/usr/bin/env python3
"""App Store Connect, from the Mac, with the API key in ~/.appstoreconnect (see ios/README.md).

    python3 asc.py check              # the key works: lists the team's apps and bundle IDs
    python3 asc.py bundle             # registers the app's bundle ID (BUNDLE) if it is not there yet
    python3 asc.py key <KEY_ID>       # tries one key by its ID (when there are several)
    python3 asc.py testers <email>    # puts a team member in the internal group "Family"
    python3 asc.py builds             # the latest uploads and whether Apple has processed them
    python3 asc.py listing <json>     # fills the store listing (ios/AppStore/listing.json); never submits
    python3 asc.py screenshots <dir>  # replaces the 6.9-inch iPhone screenshots with the PNGs in <dir>
    python3 asc.py pricing            # free, available everywhere but the EU
    python3 asc.py submit <build> [--submit]  # put a build on the waiting version; --submit sends it to review

Only Python and openssl, both already on the Mac: the token (ES256) is signed by openssl and its
DER signature rewritten as the r‖s pair JWT wants. Nothing here prints a secret.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

HOME = os.path.expanduser("~/.appstoreconnect")
BUNDLE = "io.github.luach-app.luach"


def env() -> dict[str, str]:
    """~/.appstoreconnect/luach.env. testflight.sh sources it too, so a value with spaces is quoted
    there (LUACH_COPYRIGHT="2026 …"); the quotes are not part of the value."""
    out = {}
    with open(os.path.join(HOME, "luach.env")) as fh:
        for line in fh:
            if "=" in line and not line.startswith("#"):
                k, v = line.strip().split("=", 1)
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                    v = v[1:-1]
                out[k.removeprefix("export ").strip()] = v
    return out


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def der_to_raw(der: bytes) -> bytes:
    """An ECDSA DER signature (SEQUENCE of two INTEGERs) as the 64-byte r‖s JOSE uses."""
    i = 2 if der[1] < 0x80 else 3
    parts = []
    for _ in range(2):
        assert der[i] == 0x02
        n = der[i + 1]
        parts.append(der[i + 2 : i + 2 + n].lstrip(b"\x00").rjust(32, b"\x00"))
        i += 2 + n
    return b"".join(parts)


def token(key_id: str, issuer: str) -> str:
    """A team key signs as its issuer; an individual key (LUACH_ASC_ISSUER_ID=individual) as `user`."""
    header = b64(json.dumps({"alg": "ES256", "kid": key_id, "typ": "JWT"}).encode())
    now = int(time.time())
    claims = {"iat": now, "exp": now + 900, "aud": "appstoreconnect-v1"}
    claims.update({"sub": "user"} if issuer == "individual" else {"iss": issuer})
    payload = b64(json.dumps(claims).encode())
    signing = f"{header}.{payload}".encode()
    key = os.path.join(HOME, "private_keys", f"AuthKey_{key_id}.p8")
    der = subprocess.run(["openssl", "dgst", "-sha256", "-sign", key], input=signing, capture_output=True, check=True).stdout
    return f"{header}.{payload}.{b64(der_to_raw(der))}"


def call(tok: str, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(
        "https://api.appstoreconnect.apple.com" + path,
        method=method,
        data=json.dumps(body).encode() if body else None,
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()  # a relationship PATCH answers 204 with no body
            return r.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except Exception:
            return e.code, {}


def errors(body: dict) -> str:
    return "; ".join(f"{e.get('title')}: {e.get('detail')}" for e in body.get("errors", []))


def check(tok: str) -> bool:
    code, apps = call(tok, "GET", "/v1/apps?limit=20")
    if code != 200:
        print(f"apps: {code} {errors(apps)}")
        return False
    print("apps:", [f"{a['attributes']['name']} ({a['attributes']['bundleId']})" for a in apps["data"]] or "none yet")
    code, ids = call(tok, "GET", "/v1/bundleIds?limit=50")
    print("bundle IDs:", [b["attributes"]["identifier"] for b in ids.get("data", [])] if code == 200 else f"{code} {errors(ids)}")
    return True


def bundle(tok: str) -> None:
    code, ids = call(tok, "GET", f"/v1/bundleIds?filter[identifier]={BUNDLE}")
    if code == 200 and any(b["attributes"]["identifier"] == BUNDLE for b in ids["data"]):
        print(f"{BUNDLE}: already registered")
        return
    code, made = call(tok, "POST", "/v1/bundleIds", {"data": {"type": "bundleIds", "attributes": {
        "identifier": BUNDLE, "name": "luach", "platform": "IOS"}}})
    print(f"{BUNDLE}: registered" if code == 201 else f"{BUNDLE}: {code} {errors(made)}")


def testers(tok: str, email: str) -> None:
    """An internal group ("Family") that gets every build, and `email` in it. Internal testers
    are people on the App Store Connect team; no Beta App Review."""
    code, apps = call(tok, "GET", f"/v1/apps?filter[bundleId]={BUNDLE}")
    if code != 200 or not apps["data"]:
        print(f"no app for {BUNDLE} ({code} {errors(apps)})")
        return
    app = apps["data"][0]["id"]
    code, groups = call(tok, "GET", f"/v1/apps/{app}/betaGroups")
    group = next((g["id"] for g in groups.get("data", []) if g["attributes"]["name"] == "Family"), None)
    if group is None:
        code, made = call(tok, "POST", "/v1/betaGroups", {"data": {"type": "betaGroups",
            "attributes": {"name": "Family", "isInternalGroup": True, "hasAccessToAllBuilds": True},
            "relationships": {"app": {"data": {"type": "apps", "id": app}}}}})
        if code != 201:
            print(f"group: {code} {errors(made)}")
            return
        group = made["data"]["id"]
        print("group Family: made")
    code, added = call(tok, "POST", "/v1/betaTesters", {"data": {"type": "betaTesters",
        "attributes": {"email": email},
        "relationships": {"betaGroups": {"data": [{"type": "betaGroups", "id": group}]}}}})
    print(f"{email}: invited" if code == 201 else f"{email}: {code} {errors(added)}")


def builds(tok: str) -> None:
    code, apps = call(tok, "GET", f"/v1/apps?filter[bundleId]={BUNDLE}")
    app = apps["data"][0]["id"]
    code, got = call(tok, "GET", f"/v1/builds?filter[app]={app}&sort=-uploadedDate&limit=5")
    for b in got.get("data", []):
        a = b["attributes"]
        print(a["version"], a["processingState"], a.get("uploadedDate", "")[:16])


def listing(tok: str, path: str) -> None:
    """Fills the App Store listing from ios/AppStore/listing.json. Never submits."""
    with open(path) as fh:
        L = json.load(fh)
    loc = L["locale"]

    def report(what: str, code: int, body: dict) -> None:
        print(f"{what}: {'ok' if code in (200, 201) else f'{code} {errors(body)}'}")

    _, apps = call(tok, "GET", f"/v1/apps?filter[bundleId]={BUNDLE}")
    app = apps["data"][0]["id"]
    _, infos = call(tok, "GET", f"/v1/apps/{app}/appInfos")
    info = next(i["id"] for i in infos["data"] if i["attributes"].get("appStoreState") != "READY_FOR_SALE")

    _, locs = call(tok, "GET", f"/v1/appInfos/{info}/appInfoLocalizations")
    il = next(x["id"] for x in locs["data"] if x["attributes"]["locale"] == loc)
    report("subtitle and privacy policy", *call(tok, "PATCH", f"/v1/appInfoLocalizations/{il}", {"data": {
        "type": "appInfoLocalizations", "id": il,
        "attributes": {"subtitle": L["subtitle"], "privacyPolicyUrl": L["privacyPolicyUrl"]}}}))
    report("categories", *call(tok, "PATCH", f"/v1/appInfos/{info}", {"data": {"type": "appInfos", "id": info,
        "relationships": {
            "primaryCategory": {"data": {"type": "appCategories", "id": L["primaryCategory"]}},
            "secondaryCategory": {"data": {"type": "appCategories", "id": L["secondaryCategory"]}}}}}))
    _, age = call(tok, "GET", f"/v1/appInfos/{info}/ageRatingDeclaration")
    report("age rating", *call(tok, "PATCH", f"/v1/ageRatingDeclarations/{age['data']['id']}", {"data": {
        "type": "ageRatingDeclarations", "id": age["data"]["id"], "attributes": L["ageRating"]}}))

    _, versions = call(tok, "GET", f"/v1/apps/{app}/appStoreVersions")
    v = next(x for x in versions["data"] if x["attributes"]["appStoreState"] == "PREPARE_FOR_SUBMISSION")
    vid = v["id"]
    # Who publishes it, the review contact and the server App Review signs in to are the publisher's,
    # so they live in luach.env on the Mac, not in the repository.
    e = env()
    if e.get("LUACH_COPYRIGHT"):
        report(f"version {v['attributes']['versionString']} copyright", *call(tok, "PATCH", f"/v1/appStoreVersions/{vid}", {
            "data": {"type": "appStoreVersions", "id": vid, "attributes": {"copyright": e["LUACH_COPYRIGHT"]}}}))
    else:
        print("copyright: not set (LUACH_COPYRIGHT in luach.env)")
    _, vlocs = call(tok, "GET", f"/v1/appStoreVersions/{vid}/appStoreVersionLocalizations")
    vl = next(x["id"] for x in vlocs["data"] if x["attributes"]["locale"] == loc)
    report("description, keywords, URLs", *call(tok, "PATCH", f"/v1/appStoreVersionLocalizations/{vl}", {"data": {
        "type": "appStoreVersionLocalizations", "id": vl, "attributes": {k: L[k] for k in (
            "description", "keywords", "supportUrl", "marketingUrl", "promotionalText")}}}))

    # The review account and its password live on the Mac only (~/.luach/review-account.env); the
    # contact and the server the notes name, in luach.env.
    review = dict(L["review"])
    if "{server}" in review.get("notes", ""):
        if not e.get("LUACH_REVIEW_SERVER"):
            print("review details: not sent; the notes name the server, and LUACH_REVIEW_SERVER in luach.env is not set")
            return
        review["notes"] = review["notes"].replace("{server}", e["LUACH_REVIEW_SERVER"])
    contact = {"contactFirstName": "LUACH_REVIEW_FIRST_NAME", "contactLastName": "LUACH_REVIEW_LAST_NAME",
               "contactEmail": "LUACH_REVIEW_EMAIL", "contactPhone": "LUACH_REVIEW_PHONE"}
    review.update({field: e[key] for field, key in contact.items() if e.get(key)})
    demo = {}
    with open(os.path.expanduser("~/.luach/review-account.env")) as fh:
        for line in fh:
            if "=" in line:
                k, val = line.strip().split("=", 1)
                demo[k] = val
    review.update({"demoAccountName": demo["LUACH_REVIEW_USER"], "demoAccountPassword": demo["LUACH_REVIEW_PASSWORD"],
                   "demoAccountRequired": True})
    code, detail = call(tok, "GET", f"/v1/appStoreVersions/{vid}/appStoreReviewDetail")
    if code == 200 and detail.get("data"):
        rid = detail["data"]["id"]
        report("review details", *call(tok, "PATCH", f"/v1/appStoreReviewDetails/{rid}", {"data": {
            "type": "appStoreReviewDetails", "id": rid, "attributes": review}}))
    else:
        report("review details", *call(tok, "POST", "/v1/appStoreReviewDetails", {"data": {
            "type": "appStoreReviewDetails", "attributes": review,
            "relationships": {"appStoreVersion": {"data": {"type": "appStoreVersions", "id": vid}}}}}))
    missing = [key for key in contact.values() if not e.get(key)]
    if missing:
        print(f"review details: no {', '.join(missing)} in luach.env yet; Apple needs the whole contact to submit")


def screenshots(tok: str, folder: str, kind: str = "APP_IPHONE_67") -> None:
    """Replaces the version's iPhone screenshots with the PNGs in `folder`, in name order
    (ios/AppStore/screenshots.sh makes them). APP_IPHONE_67 is the 6.9-inch slot (1320×2868)."""
    import hashlib
    _, apps = call(tok, "GET", f"/v1/apps?filter[bundleId]={BUNDLE}")
    app = apps["data"][0]["id"]
    _, versions = call(tok, "GET", f"/v1/apps/{app}/appStoreVersions")
    vid = next(x["id"] for x in versions["data"] if x["attributes"]["appStoreState"] == "PREPARE_FOR_SUBMISSION")
    _, vlocs = call(tok, "GET", f"/v1/appStoreVersions/{vid}/appStoreVersionLocalizations")
    vl = next(x["id"] for x in vlocs["data"] if x["attributes"]["locale"] == "en-US")
    _, sets = call(tok, "GET", f"/v1/appStoreVersionLocalizations/{vl}/appScreenshotSets")
    sid = next((x["id"] for x in sets.get("data", []) if x["attributes"]["screenshotDisplayType"] == kind), None)
    if sid is None:
        code, made = call(tok, "POST", "/v1/appScreenshotSets", {"data": {"type": "appScreenshotSets",
            "attributes": {"screenshotDisplayType": kind},
            "relationships": {"appStoreVersionLocalization": {"data": {"type": "appStoreVersionLocalizations", "id": vl}}}}})
        if code != 201:
            print(f"screenshot set: {code} {errors(made)}")
            return
        sid = made["data"]["id"]
    _, old = call(tok, "GET", f"/v1/appScreenshotSets/{sid}/appScreenshots")
    for shot in old.get("data", []):
        call(tok, "DELETE", f"/v1/appScreenshots/{shot['id']}")
    for name in sorted(f for f in os.listdir(folder) if f.endswith(".png")):
        data = open(os.path.join(folder, name), "rb").read()
        code, made = call(tok, "POST", "/v1/appScreenshots", {"data": {"type": "appScreenshots",
            "attributes": {"fileName": name, "fileSize": len(data)},
            "relationships": {"appScreenshotSet": {"data": {"type": "appScreenshotSets", "id": sid}}}}})
        if code != 201:
            print(f"{name}: {code} {errors(made)}")
            continue
        shot = made["data"]
        for op in shot["attributes"]["uploadOperations"]:
            part = data[op["offset"]: op["offset"] + op["length"]]
            req = urllib.request.Request(op["url"], data=part, method=op["method"],
                                         headers={h["name"]: h["value"] for h in op.get("requestHeaders", [])})
            urllib.request.urlopen(req, timeout=60).read()
        code, done = call(tok, "PATCH", f"/v1/appScreenshots/{shot['id']}", {"data": {"type": "appScreenshots",
            "id": shot["id"], "attributes": {"uploaded": True, "sourceFileChecksum": hashlib.md5(data).hexdigest()}}})
        print(f"{name}: {'uploaded' if code == 200 else f'{code} {errors(done)}'}")


# The EU's 27: selling there needs a trader-status declaration (Digital Services Act), which a
# free household app has no reason to make, so they are left out until someone decides otherwise.
EU = {"AUT", "BEL", "BGR", "HRV", "CYP", "CZE", "DNK", "EST", "FIN", "FRA", "DEU", "GRC", "HUN", "IRL",
      "ITA", "LVA", "LTU", "LUX", "MLT", "NLD", "POL", "PRT", "ROU", "SVK", "SVN", "ESP", "SWE"}


def pricing(tok: str) -> None:
    """Free, everywhere but the EU."""
    _, apps = call(tok, "GET", f"/v1/apps?filter[bundleId]={BUNDLE}")
    app = apps["data"][0]["id"]
    _, points = call(tok, "GET", f"/v1/apps/{app}/appPricePoints?filter[territory]=USA&limit=200")
    free = next(p["id"] for p in points["data"] if float(p["attributes"]["customerPrice"]) == 0)
    code, body = call(tok, "POST", "/v1/appPriceSchedules", {
        "data": {"type": "appPriceSchedules", "relationships": {
            "app": {"data": {"type": "apps", "id": app}},
            "baseTerritory": {"data": {"type": "territories", "id": "USA"}},
            "manualPrices": {"data": [{"type": "appPrices", "id": "${free}"}]}}},
        "included": [{"type": "appPrices", "id": "${free}", "attributes": {"startDate": None},
                      "relationships": {"appPricePoint": {"data": {"type": "appPricePoints", "id": free}}}}]})
    print(f"price free: {'ok' if code == 201 else f'{code} {errors(body)}'}")

    territories, path = [], "/v1/territories?limit=200"
    while path:
        _, page = call(tok, "GET", path)
        territories += [t["id"] for t in page["data"]]
        nxt = page.get("links", {}).get("next")
        path = nxt.replace("https://api.appstoreconnect.apple.com", "") if nxt else None
    # Every country is named, the EU's as not available: Apple wants the whole list.
    chosen = [t for t in territories if t not in EU]
    code, body = call(tok, "POST", "/v2/appAvailabilities", {
        "data": {"type": "appAvailabilities", "attributes": {"availableInNewTerritories": False},
                 "relationships": {"app": {"data": {"type": "apps", "id": app}},
                                   "territoryAvailabilities": {"data": [
                                       {"type": "territoryAvailabilities", "id": f"${{{t}}}"} for t in territories]}}},
        "included": [{"type": "territoryAvailabilities", "id": f"${{{t}}}", "attributes": {"available": t not in EU},
                      "relationships": {"territory": {"data": {"type": "territories", "id": t}}}} for t in territories]})
    print(f"available in {len(chosen)} of {len(territories)} countries (not the EU): "
          f"{'ok' if code == 201 else f'{code} {errors(body)}'}")


def submit(tok: str, build_number: str, go: bool) -> None:
    """Puts build `build_number` on the version waiting for submission and, with --submit, sends
    that version to App Review. Without --submit it only prepares and says what would go."""
    _, apps = call(tok, "GET", f"/v1/apps?filter[bundleId]={BUNDLE}")
    app = apps["data"][0]["id"]
    _, versions = call(tok, "GET", f"/v1/apps/{app}/appStoreVersions")
    version = next((x for x in versions["data"] if x["attributes"]["appStoreState"] == "PREPARE_FOR_SUBMISSION"), None)
    if version is None:
        print("no version is waiting for submission")
        return
    vid, vname = version["id"], version["attributes"]["versionString"]
    _, found = call(tok, "GET", f"/v1/builds?filter[app]={app}&filter[version]={build_number}")
    build = next((b for b in found.get("data", []) if b["attributes"]["processingState"] == "VALID"), None)
    if build is None:
        print(f"build {build_number}: not processed yet, or not found")
        return
    code, body = call(tok, "PATCH", f"/v1/appStoreVersions/{vid}/relationships/build",
                      {"data": {"type": "builds", "id": build["id"]}})
    print(f"version {vname} ← build {build_number}: {'ok' if code == 204 else f'{code} {errors(body)}'}")
    # The app shows only what the household's own server holds, none of it third-party content.
    code, body = call(tok, "PATCH", f"/v1/apps/{app}", {"data": {"type": "apps", "id": app,
                      "attributes": {"contentRightsDeclaration": "DOES_NOT_USE_THIRD_PARTY_CONTENT"}}})
    print(f"content rights: {'ok' if code == 200 else f'{code} {errors(body)}'}")
    if not go:
        print(f"ready: version {vname} with build {build_number}. Run again with --submit to send it to App Review.")
        return
    code, made = call(tok, "POST", "/v1/reviewSubmissions", {"data": {"type": "reviewSubmissions",
                      "attributes": {"platform": "IOS"},
                      "relationships": {"app": {"data": {"type": "apps", "id": app}}}}})
    if code != 201:
        print(f"review submission: {code} {errors(made)}")
        return
    rid = made["data"]["id"]
    code, body = call(tok, "POST", "/v1/reviewSubmissionItems", {"data": {"type": "reviewSubmissionItems",
                      "relationships": {"reviewSubmission": {"data": {"type": "reviewSubmissions", "id": rid}},
                                        "appStoreVersion": {"data": {"type": "appStoreVersions", "id": vid}}}}})
    if code != 201:
        print(f"review item: {code} {errors(body)}")
        return
    code, body = call(tok, "PATCH", f"/v1/reviewSubmissions/{rid}", {"data": {"type": "reviewSubmissions",
                      "id": rid, "attributes": {"submitted": True}}})
    print(f"submitted to App Review: {'ok' if code == 200 else f'{code} {errors(body)}'}")


def main() -> int:
    e = env()
    what = sys.argv[1] if len(sys.argv) > 1 else "check"
    key_id = sys.argv[2] if what == "key" else e["LUACH_ASC_KEY_ID"]
    tok = token(key_id, os.environ.get("LUACH_ASC_ISSUER_ID") or e["LUACH_ASC_ISSUER_ID"])
    if what in ("check", "key"):
        print(f"key {key_id}:")
        return 0 if check(tok) else 1
    if what == "bundle":
        bundle(tok)
        return 0
    if what == "testers":
        testers(tok, sys.argv[2])
        return 0
    if what == "builds":
        builds(tok)
        return 0
    if what == "submit":
        submit(tok, sys.argv[2], "--submit" in sys.argv[3:])
        return 0
    if what == "pricing":
        pricing(tok)
        return 0
    if what == "screenshots":
        screenshots(tok, sys.argv[2])
        return 0
    if what == "listing":
        listing(tok, sys.argv[2] if len(sys.argv) > 2 else "listing.json")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
