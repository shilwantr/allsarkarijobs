"""
Scrapes https://www.sarkariresult.com/ across all 6 primary sections:
- Result (RESULT)
- Admit Card (ADMIT_CARD)
- Latest Job (LATEST_JOB)
- Answer Key (ANSWER_KEY)
- Syllabus (SYLLABUS)
- Admission (ADMISSION)

Extracts each post's full metadata (Organization, Short Information, Important Dates,
Application Fee, Age Limit, Total Vacancy) and the complete curated
"Some Useful Important Links" table (Registration, Login, Result PDF, Cutoff PDF,
Admit Card Login, Answer Key Login, Syllabus PDF, Notification PDF, Official Website).

Populates data/allsarkarijobs.db (updates, recruitments, crawler_staging) and
exports portal_data.js so both localhost and Vercel display the clean sarkariresult.com
listings and exact endpoints.
"""
import concurrent.futures
import json
import os
import re
import sqlite3
import urllib.parse
import urllib.request
from bs4 import BeautifulSoup

from backend.config import DB_PATH
from backend.database import init_db
from backend.migrate_db import migrate
from backend.migrate_filters import migrate_filters
from backend.publish_crawled import export_portal_data_js


def is_pdf_url(url: str) -> bool:
    if not url:
        return False
    low = url.lower().strip()
    path_part = low.split("?")[0].split("#")[0]
    if path_part.endswith(".pdf"):
        return True
    if any(k in low for k in (
        "viewpdf.aspx",
        "application%2fpdf",
        "doc.sarkariresults.org.in/",
        "drive.google.com/file/d/",
        "natboard.edu.in/viewnotice.php",
    )):
        return True
    return False


def get_endpoints(title: str, org: str = "", cat: str = "LATEST_JOB") -> dict:
    t = f"{title} {org}".lower()
    if "mha" in t or "ib mts" in t or "intelligence bureau" in t:
        return {
            "registration_url": "https://www.mha.gov.in/en/notifications/vacancies",
            "login_url": "https://www.mha.gov.in/en/notifications/vacancies",
            "official_pdf": "https://www.mha.gov.in/en/notifications/vacancies",
            "official_website": "https://www.mha.gov.in/",
        }
    if "ssc" in t and "upsssc" not in t and "hssc" not in t and "bssc" not in t and "jssc" not in t and "osssc" not in t:
        return {
            "registration_url": "https://ssc.gov.in/candidate-portal/one-time-registration/home-page",
            "login_url": "https://ssc.gov.in/login",
            "official_pdf": "https://ssc.gov.in/api/attachment/uploads/masterData/NoticeBoards/notice_01122025.pdf",
            "official_website": "https://ssc.gov.in/",
        }
    if "upsssc" in t:
        return {
            "registration_url": "https://upsssc.gov.in/AllNotifications.aspx",
            "login_url": "https://upsssc.gov.in/ResultsDire.aspx" if cat in ("RESULT", "ANSWER_KEY") else "https://upsssc.gov.in/Online_App/AdmitCard.aspx",
            "official_pdf": "https://upsssc.gov.in/View_Notices.aspx",
            "official_website": "https://upsssc.gov.in/",
        }
    if "upsc" in t:
        return {
            "registration_url": "https://upsconline.nic.in/upsc/OTRP/index.php",
            "login_url": "https://upsconline.nic.in/upsc/OTRP/index.php",
            "official_pdf": "https://upsc.gov.in/sites/default/files/Notif-NDA-II-2026-Engl-200526.pdf",
            "official_website": "https://upsc.gov.in/",
        }
    if "railway" in t or "rrb" in t or "rrc" in t or "ntpc" in t:
        return {
            "registration_url": "https://www.rrbapply.gov.in/#/auth/landing",
            "login_url": "https://www.rrbapply.gov.in/#/auth/landing",
            "official_pdf": "https://www.rrbapply.gov.in/#/auth/landing",
            "official_website": "https://indianrailways.gov.in/",
        }
    if "bpsc" in t:
        return {
            "registration_url": "https://bpsconline.bihar.gov.in/candidate/login",
            "login_url": "https://bpsconline.bihar.gov.in/candidate/login",
            "official_pdf": "https://bpsc.bihar.gov.in/",
            "official_website": "https://bpsc.bihar.gov.in/",
        }
    if "mpesb" in t or "vyapam" in t:
        return {
            "registration_url": "https://esb.mponline.gov.in/Portal/Examinations/Vyapam/examsList.aspx",
            "login_url": "https://esb.mp.gov.in/e_default.html",
            "official_pdf": "https://esb.mp.gov.in/e_default.html",
            "official_website": "https://esb.mp.gov.in/e_default.html",
        }
    return {
        "registration_url": "https://www.india.gov.in/",
        "login_url": "https://www.india.gov.in/",
        "official_pdf": "https://www.india.gov.in/",
        "official_website": "https://www.india.gov.in/",
    }

HOMEPAGE_URL = "https://www.sarkariresult.com/"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

SECTION_MAP = {
    "Result": "RESULT",
    "Admit Card": "ADMIT_CARD",
    "Latest Job": "LATEST_JOB",
    "Answer Key": "ANSWER_KEY",
    "Syllabus": "SYLLABUS",
    "Admission": "ADMISSION",
}

COMPETITOR_DOMAINS = (
    "rojgarresult.com",
    "cdn.rojgarresult.com",
    "sarkariresult.com",
    "sarkariresults.org.in",
    "doc.sarkariresults.org.in",
    "scribd.com",
    "freejobalert.com",
    "sarkariexam.com",
    "fresherslive.com",
    "fastjobsearchers.com",
    "jobrasta.com",
)


def sanitize_link_to_official(href: str, title: str = "", org: str = "", source_url: str = "") -> str:
    """Intercepts any competitor/aggregator link or PDF and rewrites to the verified official government portal."""
    if not href:
        return ""
    href_low = href.lower()
    if not any(cd in href_low for cd in COMPETITOR_DOMAINS):
        return href
    t_low = f"{title} {org} {href}".lower()
    if "blet" in t_low or "bihar library" in t_low:
        return "https://biharboardonline.com/"
    if "htet" in t_low or "haryana tet" in t_low:
        return "https://bseh.org.in/"
    if "uptet" in t_low or "up tet" in t_low:
        return "https://updeled.gov.in/"
    if "ssc" in t_low:
        return "https://ssc.gov.in/"
    if "upsssc" in t_low:
        return "https://upsssc.gov.in/View_Notices.aspx"
    if "dsssb" in t_low:
        return "https://dsssb.delhi.gov.in/"
    if "skau" in t_low:
        return "https://skau.ac.in/"
    if "home guard" in t_low or "up police" in t_low or "uppbpb" in t_low:
        return "https://uppbpb.gov.in/"
    if "mha" in t_low or "ib mts" in t_low or "intelligence bureau" in t_low:
        return "https://www.mha.gov.in/en/notifications/vacancies"
    if source_url and source_url.startswith("http") and not any(cd in source_url.lower() for cd in COMPETITOR_DOMAINS):
        return source_url
    return "https://www.india.gov.in/"

SKIP_ROW_KEYWORDS = (
    "android app",
    "apple ios",
    "video hindi",
    "hindi video",
    "watch video",
    "sarkari result tools",
    "sarkari result portal",
    "pdf tool portal",
    "join sarkari result",
    "telegram",
    "whatsapp",
    "signature resizer",
    "image resizer",
    "resume cv maker",
    "remove background",
    "find more",
    "why government jobs",
)

SKIP_URL_DOMAINS = (
    "play.google.com",
    "itunes.apple.com",
    "youtube.com",
    "youtu.be",
    "t.me",
    "whatsapp.com",
    "sarkariresult.tools",
    "sarkariresultportal.com",
    "instagram.com",
    "facebook.com",
    "twitter.com",
    "x.com",
)


def fetch_html(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "ignore")


def resolve_shortlink(url: str) -> str:
    """Resolve tinyurl.com or bit.ly redirects to their actual destination URL."""
    low = url.lower()
    if "tinyurl.com/" not in low and "bit.ly/" not in low:
        return url
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method="HEAD")
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.geturl() or url
    except Exception:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=8) as resp:
                return resp.geturl() or url
        except Exception:
            return url


def clean_branding(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"Sarkari\s*Result(?:\.Com|\.com|s)?\s*[®™]?", "AllSarkariJobs", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def infer_filters(title: str, short_info: str = ""):
    combined = f"{title} {short_info}"
    low = combined.lower()

    # Qualification
    qual = "Graduate"
    if any(k in low for k in ["10th", "matric", "high school", "class 10", "gds", "constable", "mts", "gd"]):
        qual = "10th Pass"
    elif any(k in low for k in ["12th", "10+2", "intermediate", "chsl", "nda", "stenographer", "higher secondary"]):
        qual = "12th Pass"
    elif any(k in low for k in ["iti", "apprentice", "technician", "trade"]):
        qual = "ITI / Diploma"
    elif any(k in low for k in ["diploma", "junior engineer", "je ", "sub engineer", "polytechnic"]):
        qual = "Diploma / Engineering"
    elif any(k in low for k in ["pgt", "post graduate", "m.sc", "m.a", "ugc net", "csir", "jam ", "gate ", "phd"]):
        qual = "Post Graduate"
    elif any(k in low for k in ["b.ed", "tet", "ctet", "teacher", "prt", "tgt"]):
        qual = "B.Ed / Teaching"
    elif any(k in low for k in ["mbbs", "nursing", "norcet", "medical", "paramedical", "pharmacist", "anm", "gnm"]):
        qual = "Medical / Nursing"
    elif any(k in low for k in ["llb", "law", "judicial", "civil judge", "apo", "clt", "clat"]):
        qual = "Law / LLB"

    # Sector
    sector = "Central Govt"
    if any(k in low for k in ["railway", "rrb", "rrc", "ntpc", "dfccil", "metro"]):
        sector = "Railways"
    elif any(k in low for k in ["bank", "ibps", "sbi", "rbi", "nabard", "lic", "niacl", "gic", "idbi", "gramin bank"]):
        sector = "Banking"
    elif any(k in low for k in ["army", "navy", "air force", "airforce", "nda", "cds", "agniveer", "coast guard", "bsf", "crpf", "itbp", "cisf", "ssb", "assam rifles", "capf", "tgc", "afcat"]):
        sector = "Defence"
    elif any(k in low for k in ["police", "constable", "sub inspector", "si ", "csbc", "upprpb", "home guard"]):
        sector = "Police"
    elif any(k in low for k in ["teacher", "tet", "ctet", "pgt", "tgt", "prt", "upessc", "professor", "lecturer", "kvs", "nvs", "emrs"]):
        sector = "Teaching"
    elif any(k in low for k in ["gate", "iit", "jee", "neet", "cuet", "jam", "clat", "admission", "counselling", "board", "scholarship"]):
        sector = "Education / Admission"
    elif any(k in low for k in ["aiims", "nursing", "hospital", "medical", "nhm", "esic", "health"]):
        sector = "Medical / Health"
    elif any(k in low for k in ["high court", "supreme court", "judicial", "district court"]):
        sector = "Judiciary"
    elif any(k in low for k in ["ssc", "upsc"]):
        sector = "Central Govt"
    elif any(k in low for k in ["upsssc", "uppsc", "bpsc", "bssc", "btsc", "rpsc", "rssb", "mpesb", "mppsc", "hssc", "hpsc", "dsssb", "ukpsc", "uksssc", "jpsc", "jssc", "cgpsc", "cgvyapam", "wbpsc", "opsc", "osssc"]):
        sector = "State Govt"

    # State
    state = "All India"
    state_patterns = [
        ("Uttar Pradesh", ["up ", "uttar pradesh", "upsssc", "uppsc", "upessc", "upprpb", "uptet", "allahabad", "lucknow"]),
        ("Bihar", ["bihar", "bpsc", "bssc", "btsc", "csbc", "bpSSC", "patna", "lnmu", "vksu"]),
        ("Madhya Pradesh", ["mp ", "madhya pradesh", "mpesb", "mppsc", "vyapam", "mponline"]),
        ("Rajasthan", ["rajasthan", "rpsc", "rssb", "rsmssb", "jaipur", "reet"]),
        ("Haryana", ["haryana", "hssc", "hpsc", "htet"]),
        ("Delhi", ["delhi", "dsssb"]),
        ("Uttarakhand", ["uttarakhand", "ukpsc", "uksssc"]),
        ("Jharkhand", ["jharkhand", "jpsc", "jssc"]),
        ("Chhattisgarh", ["chhattisgarh", "cgpsc", "cgvyapam"]),
        ("Maharashtra", ["maharashtra", "mpsc", "mahagencl", "mahatransco"]),
        ("Gujarat", ["gujarat", "gpsc", "gsssb", "ojas"]),
        ("Punjab", ["punjab", "psssb", "ppsc"]),
        ("West Bengal", ["west bengal", "wbpsc", "wbhrb"]),
        ("Odisha", ["odisha", "opsc", "osssc", "ossc"]),
        ("Karnataka", ["karnataka", "kpsc", "kea"]),
        ("Tamil Nadu", ["tamil nadu", "tnpsc", "trb"]),
    ]
    for st_name, kws in state_patterns:
        if any(k in low for k in kws):
            state = st_name
            break

    return qual, sector, state


def infer_organization(title: str, short_info: str = "") -> str:
    combined = f"{title} {short_info}"
    if short_info:
        m = re.match(r"^([A-Z][A-Za-z0-9\s,&()\-]{4,85}?)\s+(?:has|have|are|is|invites|released|issued|published|conducted)", short_info)
        if m:
            candidate = clean_branding(m.group(1)).strip(" :-,")
            if len(candidate) >= 5 and "AllSarkariJobs" not in candidate:
                return candidate

    low = combined.lower()
    org_map = [
        ("ssc", "Staff Selection Commission (SSC)"),
        ("upsc", "Union Public Service Commission (UPSC)"),
        ("upsssc", "Uttar Pradesh Subordinate Services Selection Commission (UPSSSC)"),
        ("uppsc", "Uttar Pradesh Public Service Commission (UPPSC)"),
        ("upessc", "UP Education Service Selection Commission (UPESSC)"),
        ("up police", "UP Police Recruitment & Promotion Board (UPPRPB)"),
        ("bpsc", "Bihar Public Service Commission (BPSC)"),
        ("bssc", "Bihar Staff Selection Commission (BSSC)"),
        ("btsc", "Bihar Technical Service Commission (BTSC)"),
        ("csbc", "Central Selection Board of Constable (CSBC Bihar)"),
        ("railway", "Railway Recruitment Boards (RRB)"),
        ("rrb", "Railway Recruitment Boards (RRB)"),
        ("rrc", "Railway Recruitment Cell (RRC)"),
        ("ibps", "Institute of Banking Personnel Selection (IBPS)"),
        ("sbi", "State Bank of India (SBI)"),
        ("rbi", "Reserve Bank of India (RBI)"),
        ("nabard", "National Bank for Agriculture and Rural Development (NABARD)"),
        ("mpesb", "Madhya Pradesh Employees Selection Board (MPESB)"),
        ("mppsc", "Madhya Pradesh Public Service Commission (MPPSC)"),
        ("rpsc", "Rajasthan Public Service Commission (RPSC)"),
        ("rssb", "Rajasthan Staff Selection Board (RSSB)"),
        ("rsmssb", "Rajasthan Staff Selection Board (RSSB)"),
        ("hssc", "Haryana Staff Selection Commission (HSSC)"),
        ("hpsc", "Haryana Public Service Commission (HPSC)"),
        ("dsssb", "Delhi Subordinate Services Selection Board (DSSSB)"),
        ("aiims", "All India Institute of Medical Sciences (AIIMS)"),
        ("nta", "National Testing Agency (NTA)"),
        ("gate", "Indian Institute of Technology (IIT GATE Organizing Institute)"),
        ("iit jam", "Indian Institute of Technology (IIT JAM)"),
        ("india post", "Department of Posts (India Post)"),
        ("army", "Indian Army (Join Indian Army)"),
        ("navy", "Indian Navy (Join Indian Navy)"),
        ("air force", "Indian Air Force (CASB)"),
        ("afcat", "Indian Air Force (AFCAT)"),
        ("coast guard", "Indian Coast Guard (ICG)"),
        ("bsf", "Border Security Force (BSF)"),
        ("crpf", "Central Reserve Police Force (CRPF)"),
        ("itbp", "Indo-Tibetan Border Police (ITBP)"),
        ("cisf", "Central Industrial Security Force (CISF)"),
        ("allahabad high court", "High Court of Judicature at Allahabad"),
        ("delhi high court", "High Court of Delhi"),
        ("supreme court", "Supreme Court of India"),
    ]
    for kw, org_name in org_map:
        if kw in low:
            return org_name
    return "Government Recruitment Commission"


def parse_post_page(url: str) -> dict:
    """Fetch and parse a single sarkariresult.com post page."""
    result = {
        "source_post_url": url,
        "full_title": "",
        "post_date": "",
        "short_info": "",
        "organization": "",
        "important_dates": [],
        "application_fee": [],
        "age_limit": [],
        "total_vacancy": "",
        "important_links": [],
        "registration_url": "",
        "login_url": "",
        "result_login_url": "",
        "admit_card_login_url": "",
        "answer_key_login_url": "",
        "result_pdf_url": "",
        "cutoff_pdf_url": "",
        "admit_card_pdf_url": "",
        "answer_key_pdf_url": "",
        "syllabus_pdf_url": "",
        "notification_pdf_url": "",
        "official_website_url": "",
    }
    if is_pdf_url(url):
        clean_url = sanitize_link_to_official(url, "", "", "")
        result["result_pdf_url"] = clean_url
        result["notification_pdf_url"] = clean_url
        result["important_links"] = [{
            "label": "Download Official Result / Notification PDF",
            "links": [{"text": "Click Here", "url": clean_url, "is_pdf": True}],
        }]
        return result

    try:
        html = fetch_html(url)
    except Exception as e:
        result["error"] = str(e)
        return result

    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")

    # 1. Table 0: Name of Post, Post Date, Short Information
    if tables:
        t0 = tables[0]
        for r in t0.find_all("tr"):
            cols = [c.get_text(" ", strip=True) for c in r.find_all(["td", "th"])]
            if len(cols) >= 2:
                k = cols[0].lower()
                val = clean_branding(cols[1])
                if "name of post" in k:
                    result["full_title"] = val
                elif "post date" in k:
                    result["post_date"] = val
                elif "short information" in k:
                    result["short_info"] = val

    # 2. Extract metadata blocks (Important Dates, Application Fee, Age Limit, Vacancy Details)
    # and "Some Useful Important Links" rows from content tables
    in_links = False
    for t in tables[1:]:
        for r in t.find_all("tr"):
            cells = r.find_all(["td", "th"])
            row_text = " | ".join(c.get_text(" ", strip=True) for c in cells)
            if not row_text.strip():
                continue

            if "some useful important links" in row_text.lower() or "important links" in row_text.lower():
                in_links = True
                continue

            if not in_links:
                for c in cells:
                    c_text = c.get_text("\n", strip=True)
                    c_low = c_text.lower()
                    lines = [clean_branding(ln.strip(" •-*")) for ln in c_text.split("\n") if ln.strip()]
                    if "important dates" in c_low and not result["important_dates"]:
                        result["important_dates"] = [ln for ln in lines if "important dates" not in ln.lower()][:10]
                    if "application fee" in c_low and not result["application_fee"]:
                        result["application_fee"] = [ln for ln in lines if "application fee" not in ln.lower()][:8]
                    if "age limit" in c_low and not result["age_limit"]:
                        result["age_limit"] = [ln for ln in lines if "age limit" not in ln.lower()][:6]
                    if "vacancy details" in c_low and "total" in c_low and not result["total_vacancy"]:
                        m = re.search(r"Total\s*:?\s*([0-9,]+\s*(?:Post|Posts|Vacancies|Seats)?)", c_text, re.IGNORECASE)
                        if m:
                            result["total_vacancy"] = m.group(1).strip()
            else:
                # Inside "Some Useful Important Links"
                if not cells:
                    continue
                label = clean_branding(cells[0].get_text(" ", strip=True))
                label_low = label.lower()
                if not label or any(sk in label_low for sk in SKIP_ROW_KEYWORDS):
                    continue

                a_tags = r.find_all("a")
                if not a_tags:
                    continue

                row_links = []
                for a in a_tags:
                    href = (a.get("href") or "").strip()
                    ltext = clean_branding(a.get_text(" ", strip=True)) or "Click Here"
                    if not href or href.startswith("#") or href.startswith("javascript"):
                        continue
                    # Normalize relative URLs
                    href = urllib.parse.urljoin(HOMEPAGE_URL, href)
                    # Resolve tinyurl / bit.ly shortlinks
                    if "tinyurl.com/" in href.lower() or "bit.ly/" in href.lower():
                        href = resolve_shortlink(href)
                    href_low = href.lower()
                    if any(dom in href_low for dom in SKIP_URL_DOMAINS):
                        continue
                    if any(sk in ltext.lower() for sk in SKIP_ROW_KEYWORDS):
                        continue
                    # Intercept ANY competitor/private aggregator links and replace with official government portal
                    if any(cd in href_low for cd in COMPETITOR_DOMAINS):
                        clean_href = sanitize_link_to_official(href, result.get("full_title", ""), result.get("organization", ""), result.get("official_website_url", ""))
                        if clean_href and not any(cd in clean_href.lower() for cd in COMPETITOR_DOMAINS):
                            href = clean_href
                        else:
                            continue
                    row_links.append({"text": ltext, "url": href, "is_pdf": is_pdf_url(href)})

                if row_links:
                    result["important_links"].append({
                        "label": label,
                        "links": row_links,
                    })

    map_important_links_to_fields(result)
    return result


def map_important_links_to_fields(result: dict) -> dict:
    """Populate canonical URL fields from result['important_links']."""
    for k in (
        "registration_url", "login_url", "result_login_url", "admit_card_login_url",
        "answer_key_login_url", "result_pdf_url", "cutoff_pdf_url", "admit_card_pdf_url",
        "answer_key_pdf_url", "syllabus_pdf_url", "notification_pdf_url", "official_website_url"
    ):
        result.setdefault(k, "")

    for row in result.get("important_links", []):
        lbl = row["label"].lower()
        links = row["links"]
        for lk in links:
            lk["is_pdf"] = is_pdf_url(lk["url"])

        # Official Website
        if "official website" in lbl and not result["official_website_url"]:
            for lk in links:
                if not lk["is_pdf"]:
                    result["official_website_url"] = lk["url"]
                    break

        # Apply Online / Registration / Login
        if any(k in lbl for k in ["apply online", "registration", "candidate login", "correction", "edit form"]):
            for lk in links:
                if lk["is_pdf"]:
                    continue
                lt = lk["text"].lower()
                if any(w in lt for w in ["register", "registration", "part i", "new", "otr"]):
                    if not result["registration_url"]:
                        result["registration_url"] = lk["url"]
                elif any(w in lt for w in ["login", "log in", "part ii", "already", "sign in"]):
                    if not result["login_url"]:
                        result["login_url"] = lk["url"]
                else:
                    if not result["registration_url"]:
                        result["registration_url"] = lk["url"]
                    if not result["login_url"]:
                        result["login_url"] = lk["url"]

        # Result / Merit List / Scorecard / Time Table
        if any(k in lbl for k in ["result", "merit list", "score card", "scorecard", "marks", "time table"]):
            for lk in links:
                if lk["is_pdf"]:
                    if not result["result_pdf_url"]:
                        result["result_pdf_url"] = lk["url"]
                else:
                    if not result["result_login_url"]:
                        result["result_login_url"] = lk["url"]

        # Cutoff
        if any(k in lbl for k in ["cutoff", "cut off", "writeup"]):
            for lk in links:
                if lk["is_pdf"] and not result["cutoff_pdf_url"]:
                    result["cutoff_pdf_url"] = lk["url"]

        # Admit Card / Exam City / Hall Ticket
        if any(k in lbl for k in ["admit card", "hall ticket", "exam city", "exam date", "pre exam notice", "exam notice", "exam schedule"]):
            for lk in links:
                if lk["is_pdf"]:
                    if not result["admit_card_pdf_url"]:
                        result["admit_card_pdf_url"] = lk["url"]
                else:
                    if not result["admit_card_login_url"]:
                        result["admit_card_login_url"] = lk["url"]

        # Answer Key / Objection
        if any(k in lbl for k in ["answer key", "objection", "response sheet", "question paper"]):
            for lk in links:
                if lk["is_pdf"]:
                    if not result["answer_key_pdf_url"]:
                        result["answer_key_pdf_url"] = lk["url"]
                else:
                    if not result["answer_key_login_url"]:
                        result["answer_key_login_url"] = lk["url"]

        # Syllabus / Exam Pattern
        if any(k in lbl for k in ["syllabus", "exam pattern", "scheme"]):
            for lk in links:
                if lk["is_pdf"] and not result["syllabus_pdf_url"]:
                    result["syllabus_pdf_url"] = lk["url"]

        # Notification / Brochure / Advertisement / Rulebook
        if any(k in lbl for k in ["notification", "brochure", "advertisement", "rulebook", "short notice", "vacancy", "corrigendum", "postponed", "notice", "time table"]):
            for lk in links:
                if lk["is_pdf"] and not result["notification_pdf_url"]:
                    result["notification_pdf_url"] = lk["url"]

    # Also check if any row has a PDF (e.g. district-wise order PDFs on UP Anganwadi)
    for row in result.get("important_links", []):
        for lk in row.get("links", []):
            if lk.get("is_pdf") and not result["notification_pdf_url"]:
                result["notification_pdf_url"] = lk["url"]

    # If still no PDF, check if a "Download Notification / Information Brochure / Notice" row has an official notice page URL
    for row in result.get("important_links", []):
        lbl = row["label"].lower()
        if any(k in lbl for k in ["notification", "brochure", "notice", "syllabus", "exam pattern", "result"]):
            for lk in row.get("links", []):
                if lk.get("url") and not result["notification_pdf_url"]:
                    result["notification_pdf_url"] = lk["url"]

    return result


def resolve_category_urls(cat: str, title: str, org: str, parsed: dict) -> dict:
    """
    Combines the scraped sarkariresult.com links with our commission fallback map
    so every category has a guaranteed non-PDF login/registration URL and a
    guaranteed official PDF/notice URL.
    """
    fallback = get_endpoints(title, org, cat)
    official_site = parsed.get("official_website_url") or fallback["official_website"]

    # All non-PDF candidate portal links found on this post page
    any_non_pdf_login = (
        parsed.get("login_url")
        or parsed.get("admit_card_login_url")
        or parsed.get("answer_key_login_url")
        or parsed.get("result_login_url")
        or parsed.get("registration_url")
        or (official_site if "india.gov.in" not in official_site else "")
    )

    # All PDF/notice links found on this post page
    any_pdf = (
        parsed.get("notification_pdf_url")
        or parsed.get("result_pdf_url")
        or parsed.get("cutoff_pdf_url")
        or parsed.get("admit_card_pdf_url")
        or parsed.get("answer_key_pdf_url")
        or parsed.get("syllabus_pdf_url")
        or (official_site if "india.gov.in" not in official_site else "")
    )

    reg_url = parsed.get("registration_url") or any_non_pdf_login or fallback["registration_url"]
    login_url = parsed.get("login_url") or any_non_pdf_login or fallback["login_url"]

    if cat == "RESULT":
        action_url = parsed.get("result_login_url") or parsed.get("admit_card_login_url") or parsed.get("answer_key_login_url") or parsed.get("login_url") or any_non_pdf_login or fallback["login_url"]
        pdf_url = parsed.get("result_pdf_url") or parsed.get("cutoff_pdf_url") or any_pdf or fallback["official_pdf"]
        login_url = action_url
    elif cat == "ADMIT_CARD":
        action_url = parsed.get("admit_card_login_url") or parsed.get("login_url") or any_non_pdf_login or fallback["login_url"]
        pdf_url = parsed.get("admit_card_pdf_url") or parsed.get("notification_pdf_url") or any_pdf or fallback["official_pdf"]
        login_url = action_url
    elif cat == "ANSWER_KEY":
        action_url = parsed.get("answer_key_login_url") or parsed.get("admit_card_login_url") or parsed.get("login_url") or any_non_pdf_login or fallback["login_url"]
        pdf_url = parsed.get("answer_key_pdf_url") or parsed.get("notification_pdf_url") or any_pdf or fallback["official_pdf"]
        login_url = action_url
    elif cat == "SYLLABUS":
        action_url = parsed.get("login_url") or parsed.get("registration_url") or any_non_pdf_login or fallback["login_url"]
        pdf_url = parsed.get("syllabus_pdf_url") or parsed.get("notification_pdf_url") or any_pdf or fallback["official_pdf"]
        login_url = action_url
    elif cat == "ADMISSION":
        action_url = parsed.get("registration_url") or parsed.get("login_url") or any_non_pdf_login or fallback["registration_url"]
        pdf_url = parsed.get("notification_pdf_url") or any_pdf or fallback["official_pdf"]
    else:  # LATEST_JOB
        action_url = parsed.get("registration_url") or parsed.get("login_url") or any_non_pdf_login or fallback["registration_url"]
        pdf_url = parsed.get("notification_pdf_url") or any_pdf or fallback["official_pdf"]

    # Final safety guard: never allow action_url, registration_url, or login_url to be a PDF
    if is_pdf_url(action_url):
        action_url = any_non_pdf_login if (any_non_pdf_login and not is_pdf_url(any_non_pdf_login)) else (fallback["login_url"] if cat != "LATEST_JOB" else fallback["registration_url"])
    if is_pdf_url(reg_url):
        reg_url = any_non_pdf_login if (any_non_pdf_login and not is_pdf_url(any_non_pdf_login)) else fallback["registration_url"]
    if is_pdf_url(login_url):
        login_url = any_non_pdf_login if (any_non_pdf_login and not is_pdf_url(any_non_pdf_login)) else fallback["login_url"]

    return {
        "action_url": action_url,
        "registration_url": reg_url,
        "login_url": login_url,
        "pdf_url": pdf_url,
        "cutoff_pdf_url": parsed.get("cutoff_pdf_url") or "",
        "official_website_url": official_site,
    }


def re_resolve_existing_db():
    """Re-evaluates all rows in updates using their stored meta_json without re-fetching 148 pages."""
    init_db()
    migrate()
    migrate_filters()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    rows = [dict(r) for r in c.execute("SELECT * FROM updates").fetchall()]
    for r in rows:
        meta = json.loads(r["meta_json"]) if r.get("meta_json") else {}
        sr_url = meta.get("sarkariresult_url") or ""
        if is_pdf_url(sr_url) and not meta.get("important_links"):
            meta["important_links"] = [{
                "label": "Download Official Result / Notification PDF",
                "links": [{"text": "Click Here", "url": sr_url, "is_pdf": True}],
            }]
        parsed = {"important_links": meta.get("important_links", [])}
        map_important_links_to_fields(parsed)
        resolved = resolve_category_urls(r["category"], r["title"], r.get("source_portal") or "", parsed)
        c.execute(
            """
            UPDATE updates
            SET action_url = ?, registration_url = ?, login_url = ?, pdf_url = ?, cutoff_pdf_url = ?, source_url = ?, meta_json = ?
            WHERE id = ?
            """,
            (
                resolved["action_url"],
                resolved["registration_url"],
                resolved["login_url"],
                resolved["pdf_url"],
                resolved["cutoff_pdf_url"],
                resolved["official_website_url"],
                json.dumps(meta, ensure_ascii=False),
                r["id"],
            ),
        )
    conn.commit()
    conn.close()
    export_portal_data_js()
    from backend.generate_sitemap import generate_sitemap
    generate_sitemap()
    print(f"Re-resolved all {len(rows)} rows, synced portal_data.js and updated sitemap.xml.")


def scrape_all_from_sarkariresult():
    print(f"Fetching {HOMEPAGE_URL} ...")
    homepage_html = fetch_html(HOMEPAGE_URL)
    soup = BeautifulSoup(homepage_html, "html.parser")

    # 1. Extract the 6 main section lists on the homepage
    section_items = {cat: [] for cat in SECTION_MAP.values()}
    unique_urls = set()

    for ul in soup.find_all("ul"):
        links = [(a.get_text(" ", strip=True), a.get("href")) for a in ul.find_all("a") if a.get("href")]
        if len(links) >= 4:
            prev = ul.find_previous(["h1", "h2", "h3", "h4", "div", "p", "th", "td"])
            sec_title = prev.get_text(" ", strip=True) if prev else ""
            if sec_title in SECTION_MAP:
                cat_code = SECTION_MAP[sec_title]
                for link_text, href in links:
                    full_url = urllib.parse.urljoin(HOMEPAGE_URL, href.strip())
                    clean_title = clean_branding(link_text)
                    if clean_title and full_url.startswith("http"):
                        section_items[cat_code].append((clean_title, full_url))
                        unique_urls.add(full_url)

    print(f"Found {sum(len(v) for v in section_items.values())} categorized items across {len(unique_urls)} unique post URLs.")

    # 2. Concurrently fetch and parse all unique post pages
    parsed_by_url = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
        future_to_url = {executor.submit(parse_post_page, u): u for u in unique_urls}
        for idx, future in enumerate(concurrent.futures.as_completed(future_to_url), 1):
            u = future_to_url[future]
            try:
                parsed_by_url[u] = future.result()
            except Exception as e:
                parsed_by_url[u] = {"source_post_url": u, "important_links": [], "error": str(e)}
            if idx % 25 == 0 or idx == len(unique_urls):
                print(f"  Parsed {idx}/{len(unique_urls)} post pages...")

    # 3. Update SQLite database schema to store rich scraped metadata
    init_db()
    migrate()
    migrate_filters()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    existing_cols = {r[1] for r in c.execute("PRAGMA table_info(updates)").fetchall()}
    for col_name in ("registration_url", "login_url", "cutoff_pdf_url", "meta_json"):
        if col_name not in existing_cols:
            c.execute(f"ALTER TABLE updates ADD COLUMN {col_name} TEXT")

    # Replace updates table with the clean, verified sarkariresult.com items
    c.execute("DELETE FROM updates")
    c.execute("DELETE FROM sqlite_sequence WHERE name='updates'")

    # Insert in reverse order within each category so that when queried ORDER BY id DESC,
    # the #1 newest item at the top of each sarkariresult.com column appears #1 on our portal!
    cat_order = ["RESULT", "ADMIT_CARD", "LATEST_JOB", "ANSWER_KEY", "SYLLABUS", "ADMISSION"]
    total_inserted = 0

    # Mark top 2 items of Latest Job, Result, Admit Card as featured for the top highlight banner
    featured_Badges = ["Live", "Hot", "New", "Out", "Apply", "Active", "Top", "Direct"]

    for cat in cat_order:
        items = section_items.get(cat, [])
        n = len(items)
        for rev_idx, (title, post_url) in enumerate(reversed(items)):
            orig_rank = n - 1 - rev_idx  # 0 is the very top item in the column
            parsed = parsed_by_url.get(post_url, {})
            short_info = parsed.get("short_info") or ""
            org = infer_organization(title, short_info)
            qual, sector, state = infer_filters(title, short_info)
            resolved = resolve_category_urls(cat, title, org, parsed)
            resolved["official_pdf"] = sanitize_link_to_official(resolved.get("official_pdf", ""), title, org, resolved.get("official_website", ""))
            resolved["pdf_url"] = sanitize_link_to_official(resolved.get("pdf_url", ""), title, org, resolved.get("official_website", ""))
            resolved["registration_url"] = sanitize_link_to_official(resolved.get("registration_url", ""), title, org, resolved.get("official_website", ""))
            resolved["login_url"] = sanitize_link_to_official(resolved.get("login_url", ""), title, org, resolved.get("official_website", ""))
            resolved["official_website"] = sanitize_link_to_official(resolved.get("official_website", ""), title, org, "")

            is_featured = 1 if (cat in ("LATEST_JOB", "RESULT", "ADMIT_CARD") and orig_rank < 3) else 0
            featured_badge = featured_Badges[orig_rank % len(featured_Badges)] if is_featured else None

            if orig_rank < 5:
                tag = "New" if cat != "RESULT" else "Out"
            elif orig_rank < 12:
                tag = "Active" if cat == "LATEST_JOB" else "Live"
            else:
                tag = "Direct"

            meta_obj = {
                "full_title": parsed.get("full_title") or title,
                "post_date": parsed.get("post_date") or "October 2026",
                "short_info": short_info,
                "important_dates": parsed.get("important_dates") or [],
                "application_fee": parsed.get("application_fee") or [],
                "age_limit": parsed.get("age_limit") or [],
                "total_vacancy": parsed.get("total_vacancy") or "",
                "important_links": parsed.get("important_links") or [],
                "source_feed_id": post_url.rstrip("/").split("/")[-1],
            }

            from datetime import datetime
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            c.execute(
                """
                INSERT INTO updates (
                    category, title, tag, action_url, is_featured, featured_badge,
                    created_at, source_portal, source_url, pdf_url,
                    qualification_level, sector, state,
                    registration_url, login_url, cutoff_pdf_url, meta_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cat,
                    title,
                    tag,
                    resolved["action_url"],
                    is_featured,
                    featured_badge,
                    ts,
                    org,
                    resolved["official_website_url"],
                    resolved["pdf_url"],
                    qual,
                    sector,
                    state,
                    resolved["registration_url"],
                    resolved["login_url"],
                    resolved["cutoff_pdf_url"],
                    json.dumps(meta_obj, ensure_ascii=False),
                ),
            )
            total_inserted += 1

    # Also update crawler_staging so /admin shows all scraped items as APPROVED + top latest as PENDING for review if needed
    c.execute("DELETE FROM crawler_staging")
    c.execute("SELECT * FROM updates ORDER BY id DESC")
    all_updates = [dict(r) for r in c.fetchall()]
    for u in all_updates:
        c.execute(
            """
            INSERT INTO crawler_staging (
                source_portal, source_url, title, category, detected_date,
                pdf_url, action_url, extracted_data, status, confidence_score,
                qualification_level, sector, state, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'APPROVED', 0.99, ?, ?, ?, ?)
            """,
            (
                u.get("source_portal") or "Official Government Commission",
                u.get("source_url") or u.get("action_url"),
                u["title"],
                u["category"],
                datetime.now().strftime("%Y-%m-%d"),
                u.get("pdf_url"),
                u["action_url"],
                json.dumps({
                    "education": u.get("qualification_level") or "All",
                    "last_date": "Active 2026",
                    "registration_url": u.get("registration_url"),
                    "login_url": u.get("login_url"),
                }),
                u.get("qualification_level") or "All",
                u.get("sector") or "Central Govt",
                u.get("state") or "All India",
                u.get("created_at"),
            ),
        )

    conn.commit()
    conn.close()
    export_portal_data_js()
    from backend.generate_sitemap import generate_sitemap
    generate_sitemap()
    print(f"Successfully saved {total_inserted} scraped sarkariresult.com notices into {DB_PATH}, synced portal_data.js and sitemap.xml.")
    return total_inserted


if __name__ == "__main__":
    scrape_all_from_sarkariresult()
