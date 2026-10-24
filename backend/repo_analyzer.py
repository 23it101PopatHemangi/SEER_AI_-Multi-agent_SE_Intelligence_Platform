import os
import re
import json
import base64
import requests
from typing import List, Dict, Any, Optional, Tuple
from github_service import get_headers

CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")

def ensure_cache_dir():
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)

def load_raw_cache(repo_id: str) -> Optional[Dict[str, Any]]:
    """
    Reads the raw cache file from disk if it exists.
    """
    ensure_cache_dir()
    cache_path = os.path.join(CACHE_DIR, f"{repo_id}.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None

def save_raw_cache(repo_id: str, data: Dict[str, Any]):
    """
    Saves or updates raw cache data for a repository on disk.
    """
    ensure_cache_dir()
    cache_path = os.path.join(CACHE_DIR, f"{repo_id}.json")
    existing_data = {}
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
        except Exception:
            pass

    existing_data.update(data)
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(existing_data, f, indent=2)
    except Exception as e:
        print(f"Failed to save raw cache for {repo_id}: {e}")

def get_cached_analysis(repo_id: str, last_pushed_at: str) -> Optional[Dict[str, Any]]:
    """
    Checks if a cached analysis file exists on disk and is up to date.
    If the cached analysis contains generic fallbacks or is an older version (< 3),
    it automatically invalidates the cache to force a correct analysis.
    """
    ensure_cache_dir()
    cache_path = os.path.join(CACHE_DIR, f"{repo_id}.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached_data = json.load(f)
                
                # Check for stale cache version
                if cached_data.get("cache_version", 0) < 8:
                    print(f"Self-healing: Cache version outdated for {repo_id}. Invalidating cache.")
                    return None
                
                if cached_data.get("last_pushed_at") == last_pushed_at:
                    analysis = cached_data.get("analysis")
                    if analysis:
                        overview = analysis.get("overview", "")
                        # Self-healing: if overview contains the old generic owner template or HTML tags, invalidate cache
                        if overview and ("is a software project owned by" in overview or "This repository," in overview or any(tag in overview for tag in ["<strong>", "<a", "-->", "on Github", "href="])):
                            print(f"Self-healing: Cached overview is generic/raw for {repo_id}. Invalidating cache.")
                            return None

                    # Self-healing: if cache has empty analysis details but there are files, trigger re-analysis
                    if analysis and not analysis.get("key_components_details"):
                        file_struct = cached_data.get("file_structure", [])
                        if len(file_struct) > 10:  # there are actually files in this repo
                            print(f"Self-healing: Cache exists but has empty analysis details for {repo_id}. Invalidating cache.")
                            return None

                    return analysis
        except Exception as e:
            print(f"Failed to read analysis cache for {repo_id}: {e}")
    return None

def save_analysis_cache(repo_id: str, last_pushed_at: str, analysis: Dict[str, Any], extra_data: Dict[str, Any] = None):
    """
    Saves the analyzed telemetry results and extra live data to disk cache.
    """
    ensure_cache_dir()
    cache_path = os.path.join(CACHE_DIR, f"{repo_id}.json")
    existing_data = {}
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
        except Exception:
            pass

    existing_data.update({
        "last_pushed_at": last_pushed_at,
        "analysis": analysis,
        "cache_version": 8
    })

    if extra_data:
        for k, v in extra_data.items():
            if v is not None:
                existing_data[k] = v

    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(existing_data, f, indent=2)
    except Exception as e:
        print(f"Failed to save analysis cache for {repo_id}: {e}")


def fetch_file_content(owner: str, repo: str, path: str, token: str = None, branch: str = "main") -> Optional[str]:
    """
    Downloads file content from GitHub REST API, falling back to raw.githubusercontent.com on rate limits.
    """
    print(f"[FILE FETCH] Fetching file content for analysis: {owner}/{repo}/{path}")
    branches_to_try = [branch]
    for b in ["main", "master"]:
        if b not in branches_to_try:
            branches_to_try.append(b)

    for b in branches_to_try:
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={b}"
        headers = get_headers(token)
        try:
            res = requests.get(url, headers=headers, timeout=10)
            log_github_request_diagnostic(url, headers, res, repo_tag=f"{owner}/{repo}")
            if res.status_code == 200:
                data = res.json()
                content_b64 = data.get("content", "")
                if content_b64:
                    clean_b64 = content_b64.replace("\n", "").replace("\r", "")
                    content_bytes = base64.b64decode(clean_b64)
                    return content_bytes.decode("utf-8", errors="ignore")
        except Exception:
            pass

        try:
            raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{b}/{path}"
            res = requests.get(raw_url, timeout=10)
            if res.status_code == 200 and res.text:
                return res.text
        except Exception:
            pass

    return None


def extract_readme_insights(owner: str, repo: str, paths: List[str], token: str = None, branch: str = "main", repo_description: str = None) -> Dict[str, Any]:
    """
    Downloads README.md and extracts a concise plain-text summary (2-4 sentences) and section headers.
    """
    readme_path = next((p for p in paths if p.lower() in ["readme.md", "readme.txt", "readme", "readme.rst"]), None)
    
    clean_headers = []
    content = None
    if readme_path:
        content = fetch_file_content(owner, repo, readme_path, token, branch=branch)

    if not content:
        # Direct GitHub fetch fallback if paths was empty or didn't list README
        for fallback_file in ["README.md", "readme.md", "README", "readme.txt"]:
            content = fetch_file_content(owner, repo, fallback_file, token, branch=branch)
            if content:
                readme_path = fallback_file
                break

    summary = None
    has_readme = False
    
    if content:
        has_readme = True
        # Extract headers for telemetry
        headers = re.findall(r"^#{1,3}\s+(.+)$", content, re.MULTILINE)
        clean_headers = [h.strip() for h in headers if len(h.strip()) < 50][:8]

        # 1. Clean HTML comments and raw tags
        cleaned_content = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL)
        cleaned_content = re.sub(r'<img[^>]*>', '', cleaned_content)
        cleaned_content = re.sub(r'<a\b[^>]*>(.*?)</a>', r'\1', cleaned_content, flags=re.DOTALL)
        cleaned_content = re.sub(r'</?(?:strong|b|em|i|span|p|div|h\d)\b[^>]*>', '', cleaned_content, flags=re.IGNORECASE)
        cleaned_content = re.sub(r'<[^>]+>', '', cleaned_content)

        lines = cleaned_content.splitlines()
        intro_sentences = []
        feature_terms = []
        
        in_code_block = False
        in_skip_section = False
        
        for line in lines:
            line_strip = line.strip()
            if not line_strip:
                continue
            if line_strip.startswith(("```", ">")):
                if line_strip.startswith("```"):
                    in_code_block = not in_code_block
                continue
            if in_code_block:
                continue
            # Ignore markdown table rows
            if "|" in line_strip:
                continue
                
            # Header check
            if line_strip.startswith("#"):
                header_text = re.sub(r'^#+\s*', '', line_strip)
                header_clean = re.sub(r'[^\w\s\-\&]', '', header_text).strip()
                header_lower = header_clean.lower()
                
                # Check if we enter a non-feature section to skip
                if any(skip_kw in header_lower for skip_kw in ["tech stack", "architecture", "setup", "prerequisites", "screens", "commit", "license", "design system", "steps", "first launch", "notes", "algorithm"]):
                    in_skip_section = True
                    continue
                else:
                    in_skip_section = False
                    
                # Only h2/h3 headers (starting with ##) should be considered as sub-features
                if line_strip.startswith("##"):
                    feat_header = re.sub(r'^\d+[\.\)]\s*', '', header_clean)
                    feat_header = re.sub(r'^\d+\s+', '', feat_header).strip()
                    if 3 < len(feat_header) < 40 and feat_header.lower() not in ["features", "overview", "about", repo.lower()]:
                        feature_terms.append(feat_header)
                continue

            if in_skip_section:
                continue

            if line_strip.startswith(("[!", "![", "http://", "https://")):
                continue

            # List item check for features
            bullet_match = re.match(r'^[\s\-\*\+]{1,4}(.*)$', line_strip)
            if bullet_match:
                bullet_content = bullet_match.group(1).strip()
                bold_match = re.match(r'^\*\*([^*]+)\*\*\s*(?::|\s-\s|\s\u2013\s)', bullet_content)
                if bold_match:
                    term = bold_match.group(1).strip()
                    if 3 < len(term) < 40:
                        feature_terms.append(term)
                else:
                    clean_bullet = re.sub(r'[`*_~#]', '', bullet_content)
                    general_match = re.match(r'^([^:\-\n\(\)]+)(?::|\s-\s)', clean_bullet)
                    if general_match:
                        term = general_match.group(1).strip()
                        if 3 < len(term) < 40 and not term.lower().startswith("http"):
                            feature_terms.append(term)
                continue

            # Prose text line (introduction candidate)
            line_clean = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', line_strip)
            line_clean = re.sub(r'\[([^\]]+)\]\[[^\]]*\]', r'\1', line_clean)
            line_clean = re.sub(r'[`*_~#]', '', line_clean)
            line_clean = re.sub(r'[^\x00-\x7F]+', ' ', line_clean)

            sentences = re.split(r'(?<=[.!?])\s+', line_clean)
            for s in sentences:
                s_clean = s.strip()
                if len(s_clean) > 20 and not s_clean.startswith(("http://", "https://", "[!", ">")):
                    s_clean = re.sub(r'\s+', ' ', s_clean)
                    if s_clean not in intro_sentences:
                        intro_sentences.append(s_clean)

        # Build introduction
        intro_text = " ".join(intro_sentences[:2]) if intro_sentences else ""
        
        # Build features sentence
        features_text = ""
        if feature_terms:
            seen = set()
            unique_features = []
            for f in feature_terms:
                f_clean = re.sub(r'[^\w\s\-\&]', '', f).strip()
                f_clean = re.sub(r'^\d+\s*', '', f_clean).strip()
                f_lower = f_clean.lower()
                if f_lower not in seen and len(f_clean) > 3 and not any(kw in f_lower for kw in ["features", "overview", "app", "category", "categories", repo.lower()]):
                    seen.add(f_lower)
                    unique_features.append(f_clean)
                    
            unique_features = unique_features[:6]
            if unique_features:
                if len(unique_features) == 1:
                    features_str = unique_features[0]
                elif len(unique_features) == 2:
                    features_str = f"{unique_features[0]} and {unique_features[1]}"
                else:
                    features_str = ", ".join(unique_features[:-1]) + f", and {unique_features[-1]}"
                
                features_text = f"Key features include {features_str}."

        if intro_text and features_text:
            summary = f"{intro_text} {features_text}"
        elif intro_text:
            summary = intro_text
        elif features_text:
            summary = features_text

        if summary and not summary.endswith((".", "!", "?")):
            summary += "."

    if summary:
        summary = re.sub(r'<[^>]+>', '', summary)
        summary = re.sub(r'[`*_~#]', '', summary)
        summary = re.sub(r'\s+', ' ', summary).strip()

    return {
        "has_readme": has_readme,
        "summary": summary,
        "sections": clean_headers
    }

def detect_frontend_signals(
    owner: str,
    repo: str,
    paths: List[str],
    dependencies: List[str],
    file_structure: List[Dict[str, Any]],
    token: str = None,
    branch: str = "main",
    readme_summary: str = None,
    repo_description: str = None
) -> Tuple[str, List[str], Dict[str, Any]]:
    """
    Detects frontend framework, UI libraries, and web view templates using multi-signal telemetry across:
    1. Package Dependencies & Frameworks (React, Next.js, Vue, Nuxt, Angular, Svelte, Flutter, Bootstrap, Tailwind, etc.)
    2. File Paths & Template Views (.html, .css, templates/, static/, public/, .jsx, .tsx, .vue, .svelte, .jinja, .ejs, etc.)
    3. Source Code Renderers & Template Engine Imports (render_template, render, send_from_directory, React, etc.)
    4. README Documentation & Tech Stack Specifications
    """
    fe_scores = {
        "React SPA": 0,
        "Next.js SSR": 0,
        "Vue.js SPA": 0,
        "Nuxt.js SSR": 0,
        "Angular Web App": 0,
        "Svelte / SvelteKit": 0,
        "Flutter Mobile App": 0,
        "HTML5 / CSS / JavaScript Web UI": 0,
        "Jinja2 / Flask Web Templates": 0,
        "Django Web Templates": 0,
    }
    
    evidence = {k: [] for k in fe_scores.keys()}
    detected_techs = []
    deps_lower = [d.lower() for d in dependencies if isinstance(d, str)]

    # 1. Dependencies & Framework Packages
    if any("react" in d for d in deps_lower):
        if any("next" in d for d in deps_lower):
            fe_scores["Next.js SSR"] += 35
            evidence["Next.js SSR"].append("Package dependency: next")
            detected_techs.append("Next.js")
        else:
            fe_scores["React SPA"] += 30
            evidence["React SPA"].append("Package dependency: react")
            detected_techs.append("React")

    if any("vue" in d for d in deps_lower):
        if any("nuxt" in d for d in deps_lower):
            fe_scores["Nuxt.js SSR"] += 35
            evidence["Nuxt.js SSR"].append("Package dependency: nuxt")
            detected_techs.append("Nuxt.js")
        else:
            fe_scores["Vue.js SPA"] += 30
            evidence["Vue.js SPA"].append("Package dependency: vue")
            detected_techs.append("Vue.js")

    if any("angular" in d or "@angular/core" in d for d in deps_lower):
        fe_scores["Angular Web App"] += 30
        evidence["Angular Web App"].append("Package dependency: angular")
        detected_techs.append("Angular")

    if any("svelte" in d for d in deps_lower):
        fe_scores["Svelte / SvelteKit"] += 30
        evidence["Svelte / SvelteKit"].append("Package dependency: svelte")
        detected_techs.append("Svelte")

    for css_fw in ["bootstrap", "tailwindcss", "tailwind", "@mui/material", "chakra-ui", "antd"]:
        if any(css_fw in d for d in deps_lower):
            fw_name = "Tailwind CSS" if "tailwind" in css_fw else css_fw.capitalize()
            if fw_name not in detected_techs:
                detected_techs.append(fw_name)

    # 2. File Paths & Template Structure
    html_files = [p for p in paths if p.lower().endswith(".html")]
    css_files = [p for p in paths if p.lower().endswith((".css", ".scss", ".sass", ".less"))]
    js_files = [p for p in paths if p.lower().endswith((".js", ".ts")) and not any(skip in p.lower() for skip in ["node_modules", "dist", "build"])]
    template_paths = [p for p in paths if any(kw in p.lower() for kw in ["templates/", "static/", "public/", "views/", "pages/"])]

    if html_files or template_paths:
        if any("templates/" in p.lower() for p in paths):
            # Check if Python Flask / Django backend is present
            if any("flask" in d for d in deps_lower) or any("app.py" in p or "main.py" in p for p in paths):
                fe_scores["Jinja2 / Flask Web Templates"] += 25
                evidence["Jinja2 / Flask Web Templates"].append(f"Flask templates directory present ({len(html_files)} HTML template views)")
            elif any("django" in d for d in deps_lower):
                fe_scores["Django Web Templates"] += 25
                evidence["Django Web Templates"].append(f"Django templates directory present ({len(html_files)} HTML template views)")
            else:
                fe_scores["HTML5 / CSS / JavaScript Web UI"] += 20
                evidence["HTML5 / CSS / JavaScript Web UI"].append(f"Web template view files present in tree ({len(html_files)} HTML files)")

        if html_files:
            fe_scores["HTML5 / CSS / JavaScript Web UI"] += 20
            evidence["HTML5 / CSS / JavaScript Web UI"].append(f"HTML5 markup files present in repository: {', '.join(html_files[:3])}")
            if "HTML5" not in detected_techs: detected_techs.append("HTML5")
            if css_files and "CSS3" not in detected_techs: detected_techs.append("CSS3")
            if js_files and "JavaScript" not in detected_techs: detected_techs.append("JavaScript")

    # 3. Source Code Renderer Operations
    code_files = [p for p in paths if p.endswith((".py", ".js", ".ts", ".php")) and any(kw in p.lower() for kw in ["main", "app", "server", "routes", "views", "index"])]
    for cf in code_files[:6]:
        content = fetch_file_content(owner, repo, cf, token, branch=branch)
        if content:
            c_low = content.lower()
            if "render_template" in c_low:
                fe_scores["Jinja2 / Flask Web Templates"] += 30
                evidence["Jinja2 / Flask Web Templates"].append(f"Source code in '{cf}' calls Flask render_template()")
            elif "render(" in c_low and "django" in c_low:
                fe_scores["Django Web Templates"] += 30
                evidence["Django Web Templates"].append(f"Source code in '{cf}' calls Django render()")

    # 4. README Documentation Telemetry
    comb_doc = f"{readme_summary or ''} {repo_description or ''}".lower()
    if any(kw in comb_doc for kw in ["html, css, javascript", "html, css", "frontend: html", "web interface", "web app", "flask-based image recognition web app", "flask web app"]):
        if fe_scores["Jinja2 / Flask Web Templates"] > 0:
            fe_scores["Jinja2 / Flask Web Templates"] += 20
            evidence["Jinja2 / Flask Web Templates"].append("Documentation / README specifies Flask Web Interface (HTML/CSS/JS)")
        else:
            fe_scores["HTML5 / CSS / JavaScript Web UI"] += 25
            evidence["HTML5 / CSS / JavaScript Web UI"].append("Documentation / README specifies HTML, CSS, JavaScript frontend")
        if "HTML5" not in detected_techs: detected_techs.append("HTML5")
        if "CSS3" not in detected_techs: detected_techs.append("CSS3")
        if "JavaScript" not in detected_techs: detected_techs.append("JavaScript")

    # Determine Top Detected Frontend Tier
    sorted_fes = sorted(fe_scores.items(), key=lambda x: x[1], reverse=True)
    top_fe_name, top_score = sorted_fes[0]

    detected_fe_str = "Not detected"
    confidence = "None"

    if top_score > 0:
        confidence = "High Confidence" if top_score >= 25 else ("Medium Confidence" if top_score >= 10 else "Low Confidence")
        if top_fe_name in ["HTML5 / CSS / JavaScript Web UI", "Jinja2 / Flask Web Templates", "Django Web Templates"]:
            detected_fe_str = "HTML, CSS, JavaScript"
        elif top_fe_name == "React SPA":
            detected_fe_str = "React"
        elif top_fe_name == "Next.js SSR":
            detected_fe_str = "Next.js"
        elif top_fe_name == "Vue.js SPA":
            detected_fe_str = "Vue.js"
        elif top_fe_name == "Nuxt.js SSR":
            detected_fe_str = "Nuxt.js"
        elif top_fe_name == "Angular Web App":
            detected_fe_str = "Angular"
        elif top_fe_name == "Svelte / SvelteKit":
            detected_fe_str = "Svelte"
        elif top_fe_name == "Flutter Mobile App":
            detected_fe_str = "Flutter"
        else:
            detected_fe_str = top_fe_name
    
    evidence_report = {
        "primary_frontend": top_fe_name if top_score > 0 else "None",
        "score": top_score,
        "confidence": confidence,
        "evidence": evidence.get(top_fe_name, []),
        "all_scores": fe_scores
    }

    return detected_fe_str, detected_techs, evidence_report

def detect_database_signals(
    owner: str,
    repo: str,
    paths: List[str],
    dependencies: List[str],
    file_structure: List[Dict[str, Any]],
    token: str = None,
    branch: str = "main",
    readme_summary: str = None,
    repo_description: str = None
) -> Tuple[str, List[str], Dict[str, Any]]:
    """
    Detects database & storage technologies using multi-signal telemetry across 8 engines:
    MongoDB, PostgreSQL, MySQL, SQLite, Redis, Firebase, LowDB, and JSON File Storage.
    Evaluates:
    1. Dependencies & Driver Packages
    2. File Paths & Local Storage Files
    3. Docker & Docker-Compose Configurations
    4. Config & Environment Files (.env, settings.py, config.py, database.yml)
    5. ORM Schemas (Prisma, Alembic, Django, TypeORM)
    6. Source Code Imports & Adapter Usages
    7. README Documentation & Telemetry
    """
    db_scores = {
        "PostgreSQL": 0,
        "MySQL": 0,
        "MongoDB": 0,
        "SQLite": 0,
        "Redis": 0,
        "Firebase": 0,
        "LowDB": 0,
        "JSON File Storage": 0,
        "Oracle": 0,
        "MSSQL": 0,
    }
    
    evidence = {
        "PostgreSQL": [],
        "MySQL": [],
        "MongoDB": [],
        "SQLite": [],
        "Redis": [],
        "Firebase": [],
        "LowDB": [],
        "JSON File Storage": [],
        "Oracle": [],
        "MSSQL": [],
    }

    detected_orms_drivers = []
    deps_lower = [d.lower() for d in dependencies if isinstance(d, str)]

    # 1. Package Dependencies & Drivers
    pg_pkgs = ["psycopg2", "psycopg2-binary", "psycopg", "asyncpg", "pg8000", "pg", "pg-promise", "pg-hstore", "pdo_pgsql", "org.postgresql", "jackc/pgx", "lib/pq"]
    for pg_pkg in pg_pkgs:
        if any(pg_pkg in d for d in deps_lower):
            db_scores["PostgreSQL"] += 20
            evidence["PostgreSQL"].append(f"Package dependency: {pg_pkg}")
            if pg_pkg not in detected_orms_drivers:
                detected_orms_drivers.append(pg_pkg)

    my_pkgs = ["mysqlclient", "pymysql", "mysql-connector", "mysql", "mysql2", "pdo_mysql"]
    for my_pkg in my_pkgs:
        if any(my_pkg in d for d in deps_lower):
            db_scores["MySQL"] += 20
            evidence["MySQL"].append(f"Package dependency: {my_pkg}")
            if my_pkg not in detected_orms_drivers:
                detected_orms_drivers.append(my_pkg)

    mongo_pkgs = ["pymongo", "motor", "mongoose", "mongodb"]
    for mg_pkg in mongo_pkgs:
        if any(mg_pkg in d for d in deps_lower):
            db_scores["MongoDB"] += 20
            evidence["MongoDB"].append(f"Package dependency: {mg_pkg}")
            if mg_pkg not in detected_orms_drivers:
                detected_orms_drivers.append(mg_pkg)

    lite_pkgs = ["sqlite3", "better-sqlite3", "sqflite", "sqlite"]
    for l_pkg in lite_pkgs:
        if any(l_pkg in d for d in deps_lower):
            db_scores["SQLite"] += 20
            evidence["SQLite"].append(f"Package dependency: {l_pkg}")

    redis_pkgs = ["redis", "aioredis", "ioredis"]
    for r_pkg in redis_pkgs:
        if any(r_pkg in d for d in deps_lower):
            db_scores["Redis"] += 20
            evidence["Redis"].append(f"Package dependency: {r_pkg}")

    firebase_pkgs = ["firebase", "firebase-admin", "@firebase/app", "@firebase/firestore", "@firebase/database", "flutterfire"]
    for fb_pkg in firebase_pkgs:
        if any(fb_pkg in d for d in deps_lower):
            db_scores["Firebase"] += 25
            evidence["Firebase"].append(f"Package dependency: {fb_pkg}")
            if "Firebase SDK" not in detected_orms_drivers:
                detected_orms_drivers.append("Firebase SDK")

    lowdb_pkgs = ["lowdb", "lowdb-node"]
    for ldb_pkg in lowdb_pkgs:
        if any(ldb_pkg in d for d in deps_lower):
            db_scores["LowDB"] += 25
            evidence["LowDB"].append(f"Package dependency: {ldb_pkg}")
            if "LowDB Engine" not in detected_orms_drivers:
                detected_orms_drivers.append("LowDB Engine")

    json_storage_pkgs = ["jsonfile", "flat-file-db", "pouchdb", "nedb", "storkdb"]
    for js_pkg in json_storage_pkgs:
        if any(js_pkg in d for d in deps_lower):
            db_scores["JSON File Storage"] += 15
            evidence["JSON File Storage"].append(f"Package dependency: {js_pkg}")

    if any(o in deps_lower for o in ["sqlalchemy", "alembic"]):
        if "SQLAlchemy ORM" not in detected_orms_drivers:
            detected_orms_drivers.append("SQLAlchemy ORM")
    if any(o in deps_lower for o in ["prisma", "@prisma/client"]):
        if "Prisma ORM" not in detected_orms_drivers:
            detected_orms_drivers.append("Prisma ORM")
    if any(o in deps_lower for o in ["typeorm", "sequelize", "knex", "drizzle-orm"]):
        if "SQL ORM" not in detected_orms_drivers:
            detected_orms_drivers.append("SQL ORM")

    # 2. File Paths & Seed / Data Storage Files
    for p in paths:
        p_low = p.lower()
        if any(p_low.endswith(ext) for ext in [".sqlite", ".sqlite3", "db.sqlite3"]) or (p_low.endswith(".db") and not "node_modules" in p_low):
            db_scores["SQLite"] += 25
            evidence["SQLite"].append(f"Database file in tree: {p}")
        if any(fn in p_low for fn in ["database.json", "db.json", "data/database.json", "data/db.json", "db/database.json", "storage.json", "seed.json"]) and not "package" in p_low and not "tsconfig" in p_low:
            db_scores["JSON File Storage"] += 25
            evidence["JSON File Storage"].append(f"JSON database file in tree: {p}")
            if db_scores["LowDB"] > 0:
                db_scores["LowDB"] += 15
                evidence["LowDB"].append(f"JSON persistence file in tree: {p}")

    # 3. Docker & Docker-Compose Configurations
    docker_files = [p for p in paths if p.lower().endswith(("docker-compose.yml", "docker-compose.yaml", "docker-compose.override.yml", "dockerfile")) or "docker-compose" in p.lower()]
    for df in docker_files[:4]:
        content = fetch_file_content(owner, repo, df, token, branch=branch)
        if content:
            c_low = content.lower()
            if any(kw in c_low for kw in ["postgres", "5432", "postgres_user", "postgres_password", "postgres_db", "bitnami/postgresql"]):
                db_scores["PostgreSQL"] += 25
                evidence["PostgreSQL"].append(f"Docker file ({df}) defines PostgreSQL container/ports")
            if any(kw in c_low for kw in ["mysql", "mariadb", "3306", "mysql_root_password"]):
                db_scores["MySQL"] += 25
                evidence["MySQL"].append(f"Docker file ({df}) defines MySQL container/ports")
            if any(kw in c_low for kw in ["mongo", "27017", "mongo_initdb"]):
                db_scores["MongoDB"] += 25
                evidence["MongoDB"].append(f"Docker file ({df}) defines MongoDB container/ports")
            if any(kw in c_low for kw in ["redis", "6379"]):
                db_scores["Redis"] += 15
                evidence["Redis"].append(f"Docker file ({df}) defines Redis container/ports")

    # 4. Config & Environment Files (.env, settings.py, config.py)
    cfg_files = [
        p for p in paths 
        if p.lower().endswith((".env", ".env.example", ".env.local", ".env.development", ".env.production", "settings.py", "database.py", "db.py", "config.py", "database.yml", "application.yml", "application.properties"))
        or any(dir_kw in p.lower() for dir_kw in ["/config/", "/db/", "/database/"])
    ]
    for cfg in cfg_files[:6]:
        content = fetch_file_content(owner, repo, cfg, token, branch=branch)
        if content:
            c_low = content.lower()
            if any(kw in c_low for kw in ["postgres", "pg_host", "pg_user", "pgpassword", "pgdatabase", "postgresql://", "postgres://", "django.db.backends.postgresql", "db_connection=pgsql"]):
                db_scores["PostgreSQL"] += 25
                evidence["PostgreSQL"].append(f"Config/Env file ({cfg}) specifies PostgreSQL connection parameters")
            if any(kw in c_low for kw in ["mysql", "mysql://", "django.db.backends.mysql", "db_connection=mysql"]):
                db_scores["MySQL"] += 25
                evidence["MySQL"].append(f"Config/Env file ({cfg}) specifies MySQL connection parameters")
            if any(kw in c_low for kw in ["mongodb://", "mongodb+srv://", "mongo_uri"]):
                db_scores["MongoDB"] += 25
                evidence["MongoDB"].append(f"Config/Env file ({cfg}) specifies MongoDB connection string")
            if any(kw in c_low for kw in ["firebase_api_key", "firebase_project_id", "firebase_auth_domain"]):
                db_scores["Firebase"] += 25
                evidence["Firebase"].append(f"Config/Env file ({cfg}) specifies Firebase project credentials")
            if any(kw in c_low for kw in ["lowdb", "db_file", "database_json"]):
                db_scores["LowDB"] += 20
                evidence["LowDB"].append(f"Config/Env file ({cfg}) references LowDB / local storage path")

    # 5. ORM Schema Files
    prisma_schemas = [p for p in paths if p.lower().endswith("schema.prisma")]
    for ps in prisma_schemas:
        content = fetch_file_content(owner, repo, ps, token, branch=branch)
        if content:
            c_low = content.lower()
            if 'provider = "postgresql"' in c_low or 'provider = "postgres"' in c_low:
                db_scores["PostgreSQL"] += 35
                evidence["PostgreSQL"].append(f"Prisma schema ({ps}) defines provider = 'postgresql'")
            elif 'provider = "mysql"' in c_low:
                db_scores["MySQL"] += 35
                evidence["MySQL"].append(f"Prisma schema ({ps}) defines provider = 'mysql'")
            elif 'provider = "mongodb"' in c_low:
                db_scores["MongoDB"] += 35
                evidence["MongoDB"].append(f"Prisma schema ({ps}) defines provider = 'mongodb'")
            elif 'provider = "sqlite"' in c_low:
                db_scores["SQLite"] += 35
                evidence["SQLite"].append(f"Prisma schema ({ps}) defines provider = 'sqlite'")

    # 6. Source Code Imports & Driver Usages
    code_files = [
        p for p in paths
        if p.endswith((".py", ".ts", ".js", ".go", ".java", ".php"))
        and any(kw in p.lower() for kw in ["db", "database", "main", "app", "server", "model", "connection", "client", "seed", "backend"])
    ]
    for code_file in code_files[:10]:
        content = fetch_file_content(owner, repo, code_file, token, branch=branch)
        if content:
            c_low = content.lower()
            if any(kw in c_low for kw in ["import psycopg2", "import asyncpg", "create_engine('postgresql", "create_engine(\"postgresql", "from pg import", "require('pg')", "from 'pg'", 'from "pg"']):
                db_scores["PostgreSQL"] += 20
                evidence["PostgreSQL"].append(f"Source code in '{code_file}' imports PostgreSQL driver/engine")
            if any(kw in c_low for kw in ["import pymysql", "import mysql", "create_engine('mysql", "create_engine(\"mysql", "require('mysql2')", "from 'mysql2'"]):
                db_scores["MySQL"] += 20
                evidence["MySQL"].append(f"Source code in '{code_file}' imports MySQL driver/engine")
            if any(kw in c_low for kw in ["import pymongo", "mongoose.connect", "require('mongoose')", "from 'mongoose'"]):
                db_scores["MongoDB"] += 20
                evidence["MongoDB"].append(f"Source code in '{code_file}' imports MongoDB driver/client")
            if any(kw in c_low for kw in ["initializeapp", "getfirestore", "getdatabase", "firebase.firestore"]):
                db_scores["Firebase"] += 20
                evidence["Firebase"].append(f"Source code in '{code_file}' imports Firebase/Firestore SDK")
            if any(kw in c_low for kw in ["from 'lowdb'", "require('lowdb')", "jsonfile", "filesync", "low(adapter)"]):
                db_scores["LowDB"] += 25
                evidence["LowDB"].append(f"Source code in '{code_file}' imports LowDB adapter")

    # 7. SQL & Migration Files
    sql_files = [p for p in paths if p.endswith(".sql") or "alembic" in p.lower() or "migration" in p.lower()]
    if sql_files:
        db_scores["PostgreSQL"] += 5
        evidence["PostgreSQL"].append(f"Database schema/migration files present: {', '.join(sql_files[:3])}")

    # 8. README & Documentation
    comb_doc = f"{readme_summary or ''} {repo_description or ''}".lower()
    if any(k in comb_doc for k in ["postgres", "postgresql", "pgsql", "supabase"]):
        db_scores["PostgreSQL"] += 15
        evidence["PostgreSQL"].append("Documentation / README specifies PostgreSQL / Supabase")
    if any(k in comb_doc for k in ["mysql", "mariadb"]):
        db_scores["MySQL"] += 15
        evidence["MySQL"].append("Documentation / README specifies MySQL / MariaDB")
    if "mongodb" in comb_doc or "mongoose" in comb_doc:
        db_scores["MongoDB"] += 15
        evidence["MongoDB"].append("Documentation / README specifies MongoDB")
    if "firebase" in comb_doc or "firestore" in comb_doc:
        db_scores["Firebase"] += 15
        evidence["Firebase"].append("Documentation / README specifies Firebase")
    if "lowdb" in comb_doc or "low db" in comb_doc:
        db_scores["LowDB"] += 15
        evidence["LowDB"].append("Documentation / README specifies LowDB")

    # Determine Top Detected Database / Storage
    sorted_dbs = sorted(db_scores.items(), key=lambda x: x[1], reverse=True)
    top_db_name, top_score = sorted_dbs[0]

    detected_db_str = "Not detected"
    final_db_techs = []
    confidence = "None"

    if top_score > 0:
        confidence = "High Confidence" if top_score >= 25 else ("Medium Confidence" if top_score >= 10 else "Low Confidence")
        
        # Handle LowDB & JSON File Storage combined naming
        if (top_db_name in ["LowDB", "JSON File Storage"]) and (db_scores["LowDB"] > 0 and db_scores["JSON File Storage"] > 0):
            detected_db_str = "LowDB / JSON File Storage"
            final_db_techs.extend(["LowDB", "JSON File Storage"])
        else:
            primary_label = f"{top_db_name} Database" if top_db_name not in ["Firebase", "LowDB", "JSON File Storage"] else f"{top_db_name} Storage"
            detected_db_str = primary_label
            final_db_techs.append(top_db_name)

        for orm_drv in detected_orms_drivers:
            if orm_drv not in final_db_techs:
                final_db_techs.append(orm_drv)

        for second_db, second_score in sorted_dbs[1:]:
            if second_score >= 15 and second_db != top_db_name:
                if second_db not in final_db_techs:
                    final_db_techs.append(second_db)
    elif detected_orms_drivers:
        detected_db_str = f"{detected_orms_drivers[0]}"
        final_db_techs.extend(detected_orms_drivers)

    top_evidence = evidence.get(top_db_name, [])
    if top_db_name in ["LowDB", "JSON File Storage"]:
        top_evidence = evidence.get("LowDB", []) + evidence.get("JSON File Storage", [])

    evidence_report = {
        "primary_database": top_db_name if top_score > 0 else "None",
        "score": top_score,
        "confidence": confidence,
        "evidence": top_evidence,
        "all_scores": db_scores
    }

    return detected_db_str, final_db_techs, evidence_report

def analyze_repo_pipeline(
    repo_id: str,
    last_pushed_at: str,
    owner: str,
    repo: str,
    file_structure: List[Dict[str, Any]],
    token: str = None,
    force_reanalyze: bool = False,
    branch: str = "main",
    commits: List[Dict[str, Any]] = None,
    branches: List[Dict[str, Any]] = None,
    contributors: List[Dict[str, Any]] = None,
    issues: List[Dict[str, Any]] = None,
    pull_requests: List[Dict[str, Any]] = None,
    languages: Dict[str, float] = None,
    total_commits: int = None,
    repo_description: str = None
) -> Dict[str, Any]:
    """
    Runs the full static repository parser pipeline, extracting deep source code telemetry,
    key components, API endpoints, code patterns, dependencies, integrations, and architecture.
    """
    # 1. Return cached results if valid and not forcing re-analysis
    if not force_reanalyze:
        cached = get_cached_analysis(repo_id, last_pushed_at)
        if cached:
            print(f"Analysis Cache HIT for repository: {owner}/{repo}")
            return cached

    print(f"Analysis Execution. Commencing static telemetry extraction for: {owner}/{repo}")

    # Ensure file_structure is hydrated recursively if missing or empty
    if not file_structure:
        try:
            from github_service import fetch_repo_tree
            file_structure = fetch_repo_tree(owner, repo, branch, token=token)
        except Exception as fe:
            print(f"Failed hydrating file structure for {owner}/{repo}: {fe}")
            file_structure = []

    paths = [item.get("path", "") for item in file_structure if item.get("path")]

    # Base telemetry data structures
    technologies = []
    dependencies = []
    dependencies_details = []
    key_components = []
    key_components_details = []
    api_surface = []
    api_surface_details = []
    code_patterns = []
    code_patterns_details = []
    integration_points = []
    integration_points_details = []
    build_deployment_config = []
    database_technologies = []
    external_services = []

    detected_db = "Not detected"
    detected_frontend = "Not detected"
    detected_backend = "Not detected"
    detected_auth = "Not detected"
    detected_payment = "Not detected"

    # Integrate language telemetry into technologies list
    if languages:
        for lang, pct in languages.items():
            if pct >= 2.0 and lang not in technologies:
                technologies.append(lang)

    # Analyze branch names for branching model
    if branches:
        branch_names = [b.get("name") for b in branches if b.get("name")]
        if "develop" in branch_names and "main" in branch_names:
            build_deployment_config.append("Git Flow Branching (main, develop)")
        elif len(branch_names) > 3:
            build_deployment_config.append("Feature-Branch Development Workflow")

    # Analyze commit history messages for Conventional Commit patterns
    if commits:
        msg_lower = [c.get("message", "").lower() for c in commits if c.get("message")]
        feat_cnt = sum(1 for m in msg_lower if m.startswith("feat"))
        fix_cnt = sum(1 for m in msg_lower if m.startswith("fix"))
        chore_cnt = sum(1 for m in msg_lower if m.startswith("chore") or m.startswith("docs") or m.startswith("refactor"))
        if feat_cnt + fix_cnt + chore_cnt > 1:
            code_patterns.append("Conventional Commit Specification")
            code_patterns_details.append({
                "pattern_name": "Conventional Commits Specification",
                "category": "Development Lifecycle",
                "description": "Standardized commit prefixing (feat, fix, chore, docs) for automated changelogs and semver release versioning.",
                "source_files": ["Git Commit History"],
                "reusable_approach": "Enforces structured message formats to streamline release management."
            })

    # ==========================================
    # 1. PARSE DEPENDENCY MANIFESTS ACROSS TREE
    # ==========================================
    try:
        # A. package.json manifests (Root & Subfolders)
        pkg_paths = [p for p in paths if p.endswith("package.json")]
        for pkg_path in pkg_paths:
            content = fetch_file_content(owner, repo, pkg_path, token, branch=branch)
            if content:
                try:
                    data = json.loads(content)
                    deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
                    for d_name, d_ver in deps.items():
                        if d_name not in dependencies:
                            dependencies.append(d_name)
                            ecosystem = "npm"
                            purpose = "JavaScript/TypeScript package dependency"
                            d_lower = d_name.lower()
                            if "react" in d_lower: purpose = "Frontend UI library for component views"
                            elif "fastapi" in d_lower: purpose = "High-performance Python Web framework"
                            elif "express" in d_lower: purpose = "Node.js REST API router framework"
                            elif "sqlalchemy" in d_lower: purpose = "Python SQL toolkit and Object Relational Mapper"
                            elif "vite" in d_lower: purpose = "Next-generation frontend tooling bundler"
                            elif "tailwindcss" in d_lower: purpose = "Utility-first CSS styling framework"
                            elif "okta" in d_lower: purpose = "Enterprise identity & Single Sign-On SDK"
                            elif "prisma" in d_lower: purpose = "Next-generation Node.js and TypeScript ORM"
                            elif "cypress" in d_lower: purpose = "End-to-end web test automation engine"

                            dependencies_details.append({
                                "package": d_name,
                                "version": str(d_ver) if d_ver else "Manifest defined",
                                "ecosystem": ecosystem,
                                "purpose": purpose,
                                "relationships": pkg_path
                            })

                    # Framework & Service Mapping
                    if "react" in deps and "React" not in technologies:
                        technologies.append("React")
                        detected_frontend = "React SPA"
                    if "vue" in deps and "Vue.js" not in technologies:
                        technologies.append("Vue.js")
                        detected_frontend = "Vue SPA"
                    if "next" in deps and "Next.js" not in technologies:
                        technologies.append("Next.js")
                        detected_frontend = "Next.js SSR Frontend"
                    if "express" in deps and "Express.js" not in technologies:
                        technologies.append("Express.js")
                        detected_backend = "Express.js API Router"
                    if "nestjs" in deps or "@nestjs/core" in deps:
                        technologies.append("NestJS")
                        detected_backend = "NestJS Controller Architecture"
                    if "tailwindcss" in deps and "Tailwind CSS" not in technologies:
                        technologies.append("Tailwind CSS")
                    if "vite" in deps and "Vite" not in technologies:
                        technologies.append("Vite")
                        build_deployment_config.append("Vite Bundler")
                    if "prisma" in deps:
                        detected_db = "Prisma ORM"
                        database_technologies.append("Prisma ORM")
                        integration_points.append("Prisma Database Access")
                    elif "mongoose" in deps:
                        detected_db = "MongoDB (Mongoose)"
                        database_technologies.append("MongoDB (Mongoose)")
                        integration_points.append("Mongoose MongoDB driver")
                    elif "sequelize" in deps:
                        detected_db = "Sequelize ORM"
                        database_technologies.append("Sequelize ORM")
                    if "stripe" in deps or "@stripe/stripe-js" in deps:
                        detected_payment = "Stripe Payments"
                        external_services.append("Stripe Payment Gateway")
                        integration_points.append("Stripe Payment Gateway")
                    if "cypress" in deps:
                        technologies.append("Cypress E2E")
                        integration_points.append("Cypress Automation Framework")

                except Exception as pe:
                    print(f"Error parsing {pkg_path}: {pe}")

        # B. Python dependency manifests
        req_paths = [p for p in paths if p.endswith(("requirements.txt", "Pipfile", "pyproject.toml"))]
        for req_path in req_paths:
            content = fetch_file_content(owner, repo, req_path, token, branch=branch)
            if content:
                for line in content.splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and not line.startswith("["):
                        clean_dep = re.split(r"[<>=~]", line)[0].strip()
                        if clean_dep and clean_dep not in dependencies:
                            dependencies.append(clean_dep)
                            dependencies_details.append({
                                "package": clean_dep,
                                "version": "Manifest defined",
                                "ecosystem": "PyPI",
                                "purpose": "Python package dependency",
                                "relationships": req_path
                            })
                            c_lower = clean_dep.lower()
                            if c_lower == "fastapi":
                                technologies.append("FastAPI")
                                detected_backend = "FastAPI REST Server"
                            elif c_lower == "django":
                                technologies.append("Django")
                                detected_backend = "Django MVC Framework"
                            elif c_lower == "flask":
                                technologies.append("Flask")
                                detected_backend = "Flask REST Microservice"
                            elif c_lower in ["sqlalchemy", "alembic"]:
                                detected_db = "SQLAlchemy ORM"
                                database_technologies.append("SQLAlchemy ORM")

        # C. Flutter / Dart pubspec.yaml
        pub_paths = [p for p in paths if p.endswith("pubspec.yaml")]
        for pub_path in pub_paths:
            content = fetch_file_content(owner, repo, pub_path, token, branch=branch)
            if content:
                technologies.extend(["Flutter", "Dart"])
                detected_frontend = "Flutter Mobile App"
                in_deps = False
                for line in content.splitlines():
                    line_s = line.strip()
                    if line_s.startswith("dependencies:"):
                        in_deps = True
                        continue
                    elif line_s.startswith(("dev_dependencies:", "flutter:", "environment:", "flutter_test:")):
                        in_deps = False
                        continue
                    if in_deps and ":" in line_s and not line_s.startswith("#"):
                        dep_name = line_s.split(":")[0].strip()
                        if dep_name and dep_name not in ["flutter", "sdk"] and dep_name not in dependencies:
                            dependencies.append(dep_name)
                            dependencies_details.append({
                                "package": dep_name,
                                "version": "Pubspec defined",
                                "ecosystem": "pub.dev",
                                "purpose": "Flutter / Dart package dependency",
                                "relationships": pub_path
                            })
                            if "hive" in dep_name:
                                detected_db = "Hive Offline DB"
                                database_technologies.append("Hive Local Database")
                            elif "firebase" in dep_name:
                                detected_auth = "Firebase Auth"
                                external_services.append("Firebase Services")

        # D. Maven pom.xml & Gradle
        java_paths = [p for p in paths if p.endswith(("pom.xml", "build.gradle"))]
        for java_path in java_paths:
            content = fetch_file_content(owner, repo, java_path, token, branch=branch)
            if content:
                technologies.append("Java")
                build_deployment_config.append("Maven/Gradle Build System")
                artifacts = re.findall(r"<artifactId>([^<]+)</artifactId>", content) or re.findall(r"implementation\s+['\"]([^'\"]+)['\"]", content)
                for a in artifacts:
                    if a not in dependencies:
                        dependencies.append(a)
                        dependencies_details.append({
                            "package": a,
                            "version": "Build defined",
                            "ecosystem": "Maven/Gradle",
                            "purpose": "Java/Kotlin framework dependency",
                            "relationships": java_path
                        })
                        if "spring-boot" in a:
                            technologies.append("Spring Boot")
                            detected_backend = "Spring Boot Java API"

        # E. Go go.mod
        go_paths = [p for p in paths if p.endswith("go.mod")]
        for go_path in go_paths:
            content = fetch_file_content(owner, repo, go_path, token, branch=branch)
            if content:
                technologies.append("Go Modules")
                build_deployment_config.append("Go Module System")
                requires = re.findall(r"^\s*([^\s]+)\s+v[0-9]", content, re.MULTILINE)
                for r_dep in requires:
                    if r_dep not in dependencies:
                        dependencies.append(r_dep)
                        dependencies_details.append({
                            "package": r_dep,
                            "version": "go.mod defined",
                            "ecosystem": "Go Modules",
                            "purpose": "Go package module dependency",
                            "relationships": go_path
                        })
                        if "gin-gonic" in r_dep:
                            technologies.append("Gin")
                            detected_backend = "Go Gin Engine"

    except Exception as me:
        print(f"Error scanning dependency manifests: {me}")

    # ==========================================
    # 2. KEY COMPONENTS EXTRACTION & MAPPING
    # ==========================================
    try:
        # Filter out binary, generated, and vendor files
        code_paths = [
            p for p in paths
            if not any(skip in p for skip in ["node_modules/", "dist/", "build/", ".git/", ".lock", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico"])
            and not p.endswith((".g.dart", ".freezed.dart", ".min.js", ".min.css"))
            and p.endswith((".js", ".jsx", ".ts", ".tsx", ".py", ".java", ".kt", ".dart", ".go", ".cpp", ".c", ".cs", ".php", ".rb", ".rs", ".swift", ".vue", ".svelte", ".html", ".css", ".json", ".yaml"))
        ]

        for p in code_paths:
            p_lower = p.lower()
            comp_name = os.path.basename(p)
            comp_clean = os.path.splitext(comp_name)[0]
            comp_title = comp_clean.replace("_", " ").replace("-", " ").title()

            role = None
            purpose = None

            # Category matching
            if any(kw in p_lower for kw in ["/components/", "/widgets/", "/views/", "/screens/", "/pages/", "component", "screen", "widget"]):
                role = "UI Component View"
                purpose = f"Renders visual user interface component in {p}."
            elif any(kw in p_lower for kw in ["/controllers/", "/routers/", "/routes/", "/api/", "/endpoints/", "/handlers/", "controller", "router", "route", "endpoint"]):
                role = "API Router & Controller"
                purpose = f"Processes HTTP requests and handles endpoint routing logic in {p}."
            elif any(kw in p_lower for kw in ["/models/", "/entities/", "/schema/", "/dto/", "/db/", "/repository/", "/store/", "model", "schema", "entity"]):
                role = "Data Entity & Model"
                purpose = f"Defines data structure schemas and persistence mapping in {p}."
            elif any(kw in p_lower for kw in ["/services/", "/utils/", "/helpers/", "/providers/", "/context/", "/hooks/", "/middleware/", "/config/", "service", "provider", "context", "helper"]):
                role = "Service & Business Logic Module"
                purpose = f"Encapsulates core business logic, utility functions, or state management in {p}."
            elif comp_name in ["main.py", "App.tsx", "index.ts", "server.js", "app.js", "main.dart", "index.js", "App.js", "main.go", "Application.java"]:
                role = "Core Application Entrypoint"
                purpose = f"Main application entrypoint and initialization module in {p}."

            if role:
                component_key = f"{p} ({role})"
                if component_key not in key_components and len(key_components_details) < 25:
                    key_components.append(component_key)
                    key_components_details.append({
                        "path": p,
                        "name": comp_title,
                        "role": role,
                        "purpose": purpose,
                        "relationships": [os.path.dirname(p)] if os.path.dirname(p) else ["root"]
                    })

        # Fallback if no components matched strict categories: use primary source code files
        if not key_components_details and code_paths:
            for p in code_paths[:15]:
                comp_name = os.path.basename(p)
                comp_clean = os.path.splitext(comp_name)[0]
                comp_title = comp_clean.replace("_", " ").replace("-", " ").title()
                role = "Source Code Module"
                purpose = f"Source code implementation file in {p}."
                key_components.append(f"{p} ({role})")
                key_components_details.append({
                    "path": p,
                    "name": comp_title,
                    "role": role,
                    "purpose": purpose,
                    "relationships": [os.path.dirname(p)] if os.path.dirname(p) else ["root"]
                })

        if not key_components:
            key_components.append("None detected")

    except Exception as ke:
        print(f"Error extracting key components: {ke}")
        if not key_components:
            key_components.append("None detected")

    # ==========================================
    # 3. DEEP API SURFACE ROUTE EXTRACTION
    # ==========================================
    try:
        router_candidate_files = [
            p for p in paths 
            if p.endswith((".py", ".ts", ".js", ".tsx", ".jsx", ".go", ".java", ".dart", ".cs"))
            and not any(skip in p for skip in ["node_modules/", "dist/", "build/"])
            and (
                any(kw in p.lower() for kw in ["app", "main", "server", "router", "route", "controller", "api", "handler", "endpoint", "service"])
                or p.count("/") <= 2
            )
        ][:20]

        for rp in router_candidate_files:
            code_content = fetch_file_content(owner, repo, rp, token, branch=branch)
            if code_content:
                # React Router / Client Routes
                rr_routes = re.findall(r'path=["\']([^"\']+)["\']', code_content)
                for r in rr_routes:
                    if len(api_surface_details) < 25 and not r.startswith("http"):
                        api_entry = f"Route: {r} (Frontend)"
                        if api_entry not in api_surface:
                            api_surface.append(api_entry)
                            api_surface_details.append({
                                "method": "ROUTE",
                                "endpoint": r,
                                "description": f"Client-side view route defined in {rp}",
                                "source_file": rp,
                                "parameters": [p_param for p_param in ["id", "projectId", "repositoryId"] if ":" in r or "{" in r]
                            })

                # FastAPI / Flask / Django Endpoints
                py_routes = re.findall(r'@(?:app|router|api)\.(get|post|put|delete|patch)\(["\']([^"\']+)["\']', code_content, re.IGNORECASE)
                for method, endpoint in py_routes:
                    if len(api_surface_details) < 25:
                        api_entry = f"Endpoint: {method.upper()} {endpoint} (REST API)"
                        if api_entry not in api_surface:
                            api_surface.append(api_entry)
                            api_surface_details.append({
                                "method": method.upper(),
                                "endpoint": endpoint,
                                "description": f"REST API handler endpoint serving data for {endpoint}",
                                "source_file": rp,
                                "parameters": [p_param for p_param in ["projectId", "repositoryId", "id", "user_id"] if p_param in endpoint or "{" in endpoint]
                            })

                # Express / NestJS Endpoints
                node_routes = re.findall(r'(?:app|router)\.(get|post|put|delete|patch)\(["\']([^"\']+)["\']', code_content)
                for method, endpoint in node_routes:
                    if len(api_surface_details) < 25:
                        api_entry = f"Endpoint: {method.upper()} {endpoint} (Express/Node)"
                        if api_entry not in api_surface:
                            api_surface.append(api_entry)
                            api_surface_details.append({
                                "method": method.upper(),
                                "endpoint": endpoint,
                                "description": f"Node.js API handler endpoint serving data for {endpoint}",
                                "source_file": rp,
                                "parameters": [p_param for p_param in ["id", "userId", "projectId"] if ":" in endpoint]
                            })

                # Dart / Flutter / HTTP Client Service Calls
                if rp.endswith(".dart"):
                    http_calls = re.findall(r'(?:http|client|Dio|dio)\.(get|post|put|delete)\s*\(\s*["\']([^"\']+)["\']', code_content)
                    for method, endpoint in http_calls:
                        if len(api_surface_details) < 25:
                            api_entry = f"Client API: {method.upper()} {endpoint}"
                            if api_entry not in api_surface:
                                api_surface.append(api_entry)
                                api_surface_details.append({
                                    "method": method.upper(),
                                    "endpoint": endpoint,
                                    "description": f"HTTP network API call executed from {rp}",
                                    "source_file": rp,
                                    "parameters": []
                                })

        if not api_surface:
            api_surface.append("None detected")

    except Exception as ae:
        print(f"Error extracting API surface: {ae}")
        if not api_surface:
            api_surface.append("None detected")

    # ==========================================
    # 4. CODE PATTERNS EXTRACTION
    # ==========================================
    try:
        scan_files = [
            p for p in paths
            if p.endswith((".ts", ".tsx", ".py", ".go", ".dart", ".java", ".kt", ".js", ".jsx"))
            and not any(skip in p for skip in ["node_modules/", "dist/", "build/"])
            and not p.endswith(".g.dart")
        ][:15]

        code_samples = ""
        sample_file_map = {}
        for sf in scan_files:
            content = fetch_file_content(owner, repo, sf, token, branch=branch)
            if content:
                code_samples += f"\n--- {sf} ---\n" + content
                sample_file_map[sf] = content

        if code_samples:
            if any(kw in code_samples for kw in ["useState", "useEffect", "useContext"]):
                code_patterns.append("React Hooks Component Lifecycle")
                code_patterns_details.append({
                    "pattern_name": "Functional State & Lifecycle Management",
                    "category": "State Management",
                    "description": "Uses React functional hooks (useState, useEffect, useContext) for local and global state handling.",
                    "source_files": [sf for sf, c in sample_file_map.items() if any(kw in c for kw in ["useState", "useEffect"])],
                    "reusable_approach": "Encapsulates reactive view logic inside functional components."
                })
            if any(kw in code_samples.lower() for kw in ["riverpod", "ref.watch", "stateprovider", "changenotifier"]):
                code_patterns.append("Reactive State Management & Provider Pattern")
                code_patterns_details.append({
                    "pattern_name": "Declarative Reactive State Management",
                    "category": "State Management",
                    "description": "Uses compile-safe state providers (Riverpod/Provider) for decoupled state synchronization.",
                    "source_files": [sf for sf in scan_files if sf.endswith(".dart")],
                    "reusable_approach": "Decouples application state logic completely from visual UI widgets."
                })
            if any(kw in code_samples for kw in ["SQLAlchemy", "prisma", "mongoose", "sequelize", "typeorm", "Hive", "gorm"]):
                code_patterns.append("Object-Relational Mapping (ORM) Persistence")
                code_patterns_details.append({
                    "pattern_name": "Data Mapper ORM & Database Persistence",
                    "category": "Data Access & Architecture",
                    "description": "Utilizes object-relational mapping frameworks for structured entity persistence and queries.",
                    "source_files": [sf for sf in scan_files if any(kw in sf.lower() for kw in ["model", "entity", "schema", "db"])],
                    "reusable_approach": "Abstracts SQL database queries into typed object models."
                })
            if "async" in code_samples or "await" in code_samples or "Future<" in code_samples:
                code_patterns.append("Non-blocking Asynchronous I/O")
                code_patterns_details.append({
                    "pattern_name": "Asynchronous Non-blocking Execution",
                    "category": "Concurrency & I/O",
                    "description": "Utilizes async/await futures and non-blocking I/O operations for REST requests and database operations.",
                    "source_files": scan_files[:4],
                    "reusable_approach": "Prevents event-loop blocking during network and disk operations."
                })
            if "Depends(" in code_samples or "@Injectable" in code_samples or "@Autowired" in code_samples:
                code_patterns.append("Dependency Injection Architecture")
                code_patterns_details.append({
                    "pattern_name": "Dependency Injection & Modular Inversion",
                    "category": "Architecture",
                    "description": "Injects database sessions and services dynamically into request controllers.",
                    "source_files": [sf for sf, c in sample_file_map.items() if "Depends(" in c or "@Injectable" in c],
                    "reusable_approach": "Decouples connection lifecycle management from controller handlers."
                })
            if any(kw in code_samples for kw in ["try:", "catch", "HTTPException"]):
                code_patterns.append("Centralized Exception Guarding")
                code_patterns_details.append({
                    "pattern_name": "Structured Exception Guarding",
                    "category": "Error Handling",
                    "description": "Wraps external API communications and database sessions in try/except guards returning standard error payloads.",
                    "source_files": scan_files[:5],
                    "reusable_approach": "Ensures clean status codes and structured diagnostic error messages."
                })

        if not code_patterns:
            code_patterns.append("None detected")

    except Exception as cpe:
        print(f"Error extracting code patterns: {cpe}")
        if not code_patterns:
            code_patterns.append("None detected")

    # ==========================================
    # 5. INTEGRATION POINTS & EXTERNAL SERVICES
    # ==========================================
    try:
        if any(p.lower().endswith("dockerfile") for p in paths):
            integration_points.append("Docker Container Runtime Engine")
            integration_points_details.append({
                "service_name": "Docker Engine",
                "integration_type": "Containerization & Runtime",
                "direction": "Outbound",
                "file_config": "Dockerfile",
                "purpose": "Package application logic into reproducible container runtime images."
            })
        if any(p.lower().endswith("docker-compose.yml") for p in paths):
            integration_points.append("Docker-Compose Service Orchestrator")
            integration_points_details.append({
                "service_name": "Docker Compose",
                "integration_type": "Container Orchestration",
                "direction": "Bi-directional",
                "file_config": "docker-compose.yml",
                "purpose": "Orchestrates multi-container development environment services."
            })
        if any(p.startswith(".github/workflows/") for p in paths):
            integration_points.append("GitHub Actions CI/CD Pipeline")
            integration_points_details.append({
                "service_name": "GitHub Actions",
                "integration_type": "CI/CD Automation",
                "direction": "Outbound",
                "file_config": ".github/workflows",
                "purpose": "Automated build, test, and continuous integration workflows."
            })

        if not integration_points:
            integration_points.append("None detected")

    except Exception as ie:
        print(f"Error extracting integration points: {ie}")
        if not integration_points:
            integration_points.append("None detected")

    # Clean duplicates
    dependencies = sorted(list(set([d for d in dependencies if d])))[:30]
    key_components = sorted(list(set([k for k in key_components if k])))
    api_surface = sorted(list(set([a for a in api_surface if a])))
    code_patterns = sorted(list(set([c for c in code_patterns if c])))
    integration_points = sorted(list(set([i for i in integration_points if i])))

    # ==========================================
    # 6. FETCH README & ARCHITECTURE OVERVIEW
    # ==========================================
    readme_insights = extract_readme_insights(owner, repo, paths, token, branch=branch, repo_description=repo_description)
    project_purpose = readme_insights.get("summary")
    
    if project_purpose:
        project_purpose = re.sub(r'<[^>]+>', '', project_purpose)
        project_purpose = re.sub(r'[`*_~#]', '', project_purpose).strip()

    if not project_purpose:
        desc_sentences = []
        if repo_description:
            clean_desc = re.sub(r'<[^>]+>', '', repo_description)
            clean_desc = re.sub(r'[`*_~#]', '', clean_desc).strip()
            if clean_desc:
                if not clean_desc.endswith((".", "!", "?")):
                    clean_desc += "."
                desc_sentences.append(clean_desc)
        else:
            desc_sentences.append(f"This repository, {repo}, is a software project owned by {owner}.")
            
        if languages:
            top_langs = sorted(languages.keys(), key=lambda k: languages[k], reverse=True)[:3]
            desc_sentences.append(f"It is primarily developed using {', '.join(top_langs)}.")
        if technologies:
            desc_sentences.append(f"The project leverages key technologies including {', '.join(technologies[:5])}.")
        project_purpose = " ".join(desc_sentences)

    # Multi-Signal Frontend Detection Engine
    sig_fe, fe_techs, fe_report = detect_frontend_signals(
        owner, repo, paths, dependencies, file_structure,
        token=token, branch=branch,
        readme_summary=project_purpose, repo_description=repo_description
    )

    if sig_fe != "Not detected":
        detected_frontend = sig_fe

    for ft in fe_techs:
        if ft not in technologies:
            technologies.append(ft)

    # Multi-Signal Database Detection Engine
    sig_db, multi_db_techs, db_report = detect_database_signals(
        owner, repo, paths, dependencies, file_structure,
        token=token, branch=branch,
        readme_summary=project_purpose, repo_description=repo_description
    )

    if sig_db != "Not detected":
        detected_db = sig_db

    for dt in multi_db_techs:
        if dt not in database_technologies:
            database_technologies.append(dt)

    if db_report.get("primary_database") != "None" and db_report.get("evidence"):
        db_primary = db_report.get("primary_database")
        if not any(ip.get("service_name") == db_primary for ip in integration_points_details):
            integration_points.append(f"{db_primary} Database")
            integration_points_details.append({
                "service_name": db_primary,
                "integration_type": "Database Persistence Tier",
                "direction": "Bidirectional Data Persistence",
                "file_config": db_report.get("evidence")[0] if db_report.get("evidence") else "Project Config",
                "purpose": f"Database persistence tier detected with {db_report.get('confidence', 'High')} based on {len(db_report.get('evidence', []))} signals ({', '.join(db_report.get('evidence', [])[:2])})."
            })

    # Construct System Data Flow & Architecture Overview
    flow_desc = "Not detected"
    if detected_frontend != "Not detected" and detected_backend != "Not detected":
        flow_desc = (
            f"Asynchronous HTTP REST API flow: Client actions trigger router components in "
            f"the {detected_frontend} frontend, which communicate via standard endpoints with the "
            f"{detected_backend} backend service. The backend queries database rows and redirects responses."
        )
    elif detected_frontend != "Not detected":
        flow_desc = f"Single Page client-rendered flow managed by {detected_frontend} views."
    elif detected_backend != "Not detected":
        flow_desc = f"REST/gRPC API service flow managed by {detected_backend} path controllers."

    arch_sections = []
    if project_purpose:
        arch_sections.append(f"- **Repository Purpose**: {project_purpose}")
    arch_sections.append(f"- **Frontend Tier**: {detected_frontend}")
    arch_sections.append(f"- **Backend Tier**: {detected_backend}")
    arch_sections.append(f"- **Database Tier**: {detected_db}")
    if detected_auth != "Not detected":
        arch_sections.append(f"- **Authentication Security**: {detected_auth}")
    if detected_payment != "Not detected":
        arch_sections.append(f"- **Payment Gateway**: {detected_payment}")
    arch_sections.append(f"- **System Data Flow**: {flow_desc}")

    architecture_overview = "\n".join(arch_sections)

    analysis = {
        "overview": project_purpose,
        "technologies": technologies,
        "architecture_overview": architecture_overview,
        "key_components": key_components,
        "key_components_details": key_components_details,
        "api_surface": api_surface,
        "api_surface_details": api_surface_details,
        "code_patterns": code_patterns,
        "code_patterns_details": code_patterns_details,
        "integration_points": integration_points,
        "integration_points_details": integration_points_details,
        "dependencies": dependencies,
        "dependencies_details": dependencies_details,
        "build_deployment_config": build_deployment_config,
        "database_technologies": database_technologies,
        "external_services": external_services,
        "readme_insights": readme_insights
    }

    # Persist results to disk cache
    save_analysis_cache(
        repo_id,
        last_pushed_at,
        analysis,
        extra_data={
            "languages": languages,
            "file_structure": file_structure,
            "commits": commits,
            "total_commits": total_commits,
            "branches": branches,
            "contributors": contributors,
            "issues": issues,
            "pull_requests": pull_requests
        }
    )

    return analysis


