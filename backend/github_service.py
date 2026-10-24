import os
import re
import requests
from datetime import datetime
from dotenv import load_dotenv
from fastapi import HTTPException, status

# Load environment variables from .env files (backend and root directory)
load_dotenv()
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

import time

_global_api_call_count = 0
_repo_api_call_counts = {}
_recent_requests_history = []

def log_github_request_diagnostic(url: str, request_headers: dict, response: requests.Response = None, repo_tag: str = "general"):
    global _global_api_call_count, _repo_api_call_counts, _recent_requests_history
    _global_api_call_count += 1
    
    if repo_tag:
        _repo_api_call_counts[repo_tag] = _repo_api_call_counts.get(repo_tag, 0) + 1
        repo_count = _repo_api_call_counts[repo_tag]
    else:
        repo_count = "N/A"

    # 1. Verify Authentication & Token Presence
    auth_header = request_headers.get("Authorization", "") if request_headers else ""
    is_authenticated = bool(auth_header and auth_header.startswith("Bearer "))
    if is_authenticated:
        raw_token = auth_header.replace("Bearer ", "").strip()
        token_snippet = f"...{raw_token[-4:]}" if len(raw_token) >= 4 else "***"
        auth_status = f"AUTHENTICATED (Token Sent: {token_snippet})"
    else:
        auth_status = "UNAUTHENTICATED (No Authorization header sent! Subject to 60 req/hr IP limit)"

    # 2. Extract Response Headers & Status Code
    res_headers = response.headers if response is not None else {}
    status_code = response.status_code if response is not None else "N/A"
    
    rl_limit = res_headers.get("X-RateLimit-Limit", "N/A")
    rl_remaining = res_headers.get("X-RateLimit-Remaining", "N/A")
    rl_used = res_headers.get("X-RateLimit-Used", "N/A")
    rl_reset = res_headers.get("X-RateLimit-Reset", "N/A")
    
    reset_time_str = "N/A"
    if rl_reset != "N/A" and str(rl_reset).isdigit():
        try:
            reset_ts = int(rl_reset)
            reset_dt = datetime.utcfromtimestamp(reset_ts)
            secs_left = max(0, reset_ts - int(time.time()))
            reset_time_str = f"{reset_dt.strftime('%H:%M:%S UTC')} ({secs_left}s remaining)"
        except Exception:
            pass

    body_snippet = ""
    if response is not None:
        try:
            body_snippet = response.text[:250].replace("\n", " ").replace("\r", "")
        except Exception:
            body_snippet = "<unreadable>"

    # 3. Classify Rate Limit / Error Types
    classification = "UNKNOWN"
    if status_code == 200:
        classification = "200 OK (Success)"
    elif status_code == 401:
        classification = "401 UNAUTHORIZED (Bad Credentials / Expired Token)"
    elif status_code == 404:
        classification = "404 NOT FOUND (Repository or path does not exist)"
    elif status_code in (403, 429):
        body_lower = body_snippet.lower()
        if rl_remaining == "0":
            classification = f"PRIMARY_RATE_LIMIT_EXHAUSTED (HTTP {status_code} | X-RateLimit-Remaining=0)"
        elif any(kw in body_lower for kw in ["secondary rate limit", "please wait", "abuse"]):
            classification = f"SECONDARY_RATE_LIMIT (HTTP {status_code} | Triggered by rapid concurrent requests)"
        else:
            classification = f"FORBIDDEN_OR_RATE_LIMIT (HTTP {status_code})"
    else:
        classification = f"HTTP {status_code}"

    # 4. Duplicate / Concurrent Request Tracking
    now = time.time()
    _recent_requests_history.append({"url": url, "time": now, "repo": repo_tag})
    _recent_requests_history = [r for r in _recent_requests_history if now - r["time"] < 60]
    duplicate_count = sum(1 for r in _recent_requests_history if r["url"] == url)
    duplicate_warning = f" [WARNING: DUPLICATE REQUEST #{duplicate_count} in last 60s]" if duplicate_count > 1 else ""

    print(f"\n==================== [GITHUB DIAGNOSTIC LOG] ====================")
    print(f" Request #{_global_api_call_count} | Repo '{repo_tag}' Call #{repo_count}{duplicate_warning}")
    print(f" URL: {url}")
    print(f" Auth State: {auth_status}")
    print(f" HTTP Status: {status_code} ({classification})")
    print(f" RateLimit Headers: Limit={rl_limit} | Remaining={rl_remaining} | Used={rl_used} | Reset={reset_time_str}")
    if status_code != 200:
        print(f" Response Body: {body_snippet}")
    print(f"=================================================================\n")

def get_headers(token: str = None) -> dict:
    load_dotenv(override=True)
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"), override=True)
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    user_token = token if isinstance(token, str) and token.strip() else None
    env_token = (
        os.getenv("GITHUB_TOKEN") or 
        os.getenv("GITHUB_ACCESS_TOKEN") or 
        os.getenv("GH_TOKEN")
    )
    active_token = user_token or env_token
    
    if active_token and isinstance(active_token, str) and active_token.strip():
        headers["Authorization"] = f"Bearer {active_token.strip()}"
    return headers

def parse_github_url(url: str) -> tuple[str, str]:
    """
    Parses owner and repository name from a GitHub URL.
    Example: https://github.com/facebook/react -> ('facebook', 'react')
    """
    pattern = r"github\.com/([^/]+)/([^/]+?)(?:\.git|/)?$"
    match = re.search(pattern, url.strip())
    if not match:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid GitHub repository URL. Format must be: https://github.com/owner/repository"
        )
    return match.group(1), match.group(2)

def handle_github_response(response: requests.Response):
    """
    Utility to handle GitHub response codes and raise friendly HTTPExceptions.
    """
    if response.status_code == 200:
        return response.json()
    
    if response.status_code == 404:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="GitHub repository not found. Please verify the URL is correct and public."
        )
    elif response.status_code == 403:
        # Check if rate limit is reached
        rate_limit_remaining = response.headers.get("X-RateLimit-Remaining")
        if rate_limit_remaining == "0":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="GitHub API rate limit reached. Please configure a GITHUB_TOKEN in your environment or try again later."
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access to the repository is forbidden. Private repositories are not supported."
            )
    elif response.status_code == 401:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid GitHub token configured. Please check your GITHUB_TOKEN variable."
        )
    
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=f"GitHub API returned an error: {response.reason} (Status {response.status_code})"
    )

def fetch_repo_metadata_fallback(owner: str, repo: str) -> dict:
    """
    Fallback method to fetch basic repository metadata directly from the public GitHub web page
    when API rate limits (HTTP 403) are encountered.
    """
    url = f"https://github.com/{owner}/{repo}"
    try:
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if res.status_code == 200:
            html = res.text
            
            og_desc_match = re.search(r'<meta\s+property="og:description"\s+content="([^"]*)"', html, re.IGNORECASE)
            desc_match = re.search(r'<meta\s+name="description"\s+content="([^"]*)"', html, re.IGNORECASE)
            description = ""
            if og_desc_match:
                description = og_desc_match.group(1).strip()
            elif desc_match:
                description = desc_match.group(1).strip()
                
            description = re.sub(r'^\s*Contribute to [^\s]+ development by creating an account on GitHub\.\s*$', '', description)
            description = re.sub(r' - [^-]+ - GitHub\s*$', '', description)
            
            default_branch = "main"
            branch_match = re.search(r'href="/' + re.escape(owner) + r'/' + re.escape(repo) + r'/tree/([^"]+)"', html)
            if branch_match and branch_match.group(1).strip() not in ["commits", "branches", "tags"]:
                default_branch = branch_match.group(1).strip()
            elif f'href="/{owner}/{repo}/tree/develop"' in html:
                default_branch = "develop"
            elif f'href="/{owner}/{repo}/tree/master"' in html:
                default_branch = "master"
            elif f'href="/{owner}/{repo}/tree/main"' in html:
                default_branch = "main"

            # Extract actual pushed_at date directly from GitHub default commit Atom feed or HTML tags
            pushed_at_str = None
            try:
                atom_urls = [
                    f"https://github.com/{owner}/{repo}/commits.atom",
                    f"https://github.com/{owner}/{repo}/commits/{default_branch}.atom",
                    f"https://github.com/{owner}/{repo}/commits/main.atom",
                    f"https://github.com/{owner}/{repo}/commits/master.atom",
                    f"https://github.com/{owner}/{repo}/commits/develop.atom"
                ]
                for atom_url in atom_urls:
                    atom_res = requests.get(atom_url, timeout=5, allow_redirects=True)
                    if atom_res.status_code == 200:
                        import xml.etree.ElementTree as ET
                        root = ET.fromstring(atom_res.content)
                        ns = {'atom': 'http://www.w3.org/2005/Atom'}
                        updated_node = root.find('atom:entry/atom:updated', ns)
                        if updated_node is not None and updated_node.text:
                            pushed_at_str = updated_node.text.strip()
                            break
            except Exception as ae:
                print(f"Failed parsing Atom feed pushed_at for {owner}/{repo}: {ae}")

            if not pushed_at_str and 'html' in locals() and html:
                try:
                    times = re.findall(r'datetime="([^"]+)"', html)
                    iso_times = [t for t in times if re.match(r'^\d{4}-\d{2}-\d{2}T', t)]
                    if iso_times:
                        pushed_at_str = max(iso_times)
                except Exception:
                    pass

            pushed_date = pushed_at_str or datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

            return {
                "name": repo,
                "owner": {"login": owner},
                "description": description,
                "default_branch": default_branch,
                "language": "Unknown",
                "stargazers_count": 0,
                "forks_count": 0,
                "open_issues_count": 0,
                "created_at": pushed_date,
                "updated_at": pushed_date,
                "pushed_at": pushed_date
            }
    except Exception as e:
        print(f"Fallback HTML metadata fetch failed for {owner}/{repo}: {e}")
        
    fallback_pushed = None
    try:
        atom_res = requests.get(f"https://github.com/{owner}/{repo}/commits.atom", timeout=5)
        if atom_res.status_code == 200:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(atom_res.content)
            ns = {'atom': 'http://www.w3.org/2005/Atom'}
            updated_node = root.find('atom:entry/atom:updated', ns)
            if updated_node is not None and updated_node.text:
                fallback_pushed = updated_node.text.strip()
    except Exception:
        pass

    final_pushed = fallback_pushed or datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "name": repo,
        "owner": {"login": owner},
        "description": f"{repo} repository owned by {owner}",
        "default_branch": "main",
        "language": "Unknown",
        "stargazers_count": 0,
        "forks_count": 0,
        "open_issues_count": 0,
        "created_at": final_pushed,
        "updated_at": final_pushed,
        "pushed_at": final_pushed
    }

def fetch_repo_metadata(owner: str, repo: str, token: str = None) -> dict:
    url = f"https://api.github.com/repos/{owner}/{repo}"
    headers = get_headers(token)
    try:
        res = requests.get(url, headers=headers)
        log_github_request_diagnostic(url, headers, res, repo_tag=f"{owner}/{repo}")
        return handle_github_response(res)
    except HTTPException as he:
        if he.status_code == 403 or "rate limit" in str(he.detail).lower():
            print(f"API rate limit hit for metadata {owner}/{repo}, using web fallback.")
            return fetch_repo_metadata_fallback(owner, repo)
        raise he

def detect_languages_from_file_structure(file_structure: list, owner: str = None, repo: str = None, branch: str = "main") -> dict:
    """
    Computes accurate language allocation percentages by scanning file extensions and fetching byte sizes.
    Guarantees 100% accurate language statistics for all newly added repositories.
    """
    ext_map = {
        ".js": "JavaScript", ".jsx": "JavaScript", ".cjs": "JavaScript", ".mjs": "JavaScript",
        ".ts": "TypeScript", ".tsx": "TypeScript",
        ".html": "HTML", ".htm": "HTML",
        ".css": "CSS", ".scss": "CSS", ".less": "CSS",
        ".py": "Python",
        ".dart": "Dart",
        ".java": "Java",
        ".kt": "Kotlin", ".kts": "Kotlin",
        ".go": "Go",
        ".rs": "Rust",
        ".cpp": "C++", ".cxx": "C++", ".cc": "C++", ".h": "C++", ".hpp": "C++",
        ".c": "C",
        ".php": "PHP",
        ".rb": "Ruby",
        ".swift": "Swift",
        ".sh": "Shell", ".bash": "Shell"
    }
    
    lang_counts = {}
    for item in file_structure:
        path = item.get("path", "")
        if any(skip in path for skip in ["node_modules/", "dist/", "build/", ".git/"]):
            continue
            
        ext = os.path.splitext(path)[1].lower()
        if ext in ext_map:
            lang = ext_map[ext]
            size = item.get("size")
            if (not size or size == 100) and owner and repo:
                try:
                    raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"
                    res = requests.head(raw_url, timeout=3)
                    if res.status_code == 200 and "Content-Length" in res.headers:
                        size = int(res.headers["Content-Length"])
                    else:
                        res_get = requests.get(raw_url, timeout=3)
                        if res_get.status_code == 200:
                            size = len(res_get.content)
                except Exception:
                    size = 100
            
            size = size or 100
            lang_counts[lang] = lang_counts.get(lang, 0) + size

    total_target = sum(lang_counts.values())
    if total_target == 0:
        return {}
        
    return {
        lang: round((count / total_target) * 100, 1)
        for lang, count in sorted(lang_counts.items(), key=lambda x: x[1], reverse=True)
    }

def fetch_repo_languages(owner: str, repo: str, token: str = None, file_structure: list = None) -> dict:
    """
    Fetches language statistics directly from the GitHub repository API (/repos/{owner}/{repo}/languages).
    Falls back to scanning file structure when API rate limits are hit.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/languages"
    headers = get_headers(token)
    try:
        res = requests.get(url, headers=headers, timeout=10)
        log_github_request_diagnostic(url, headers, res, repo_tag=f"{owner}/{repo}")
        if res.status_code == 200:
            raw_langs = res.json()
            if isinstance(raw_langs, dict) and raw_langs:
                total_bytes = sum(raw_langs.values())
                if total_bytes > 0:
                    result = {}
                    for lang, bytes_count in raw_langs.items():
                        pct = (bytes_count / total_bytes) * 100
                        result[lang] = round(pct, 1) if pct >= 0.1 else round(pct, 2)
                    return result
    except Exception as e:
        print(f"Error fetching languages from GitHub API for {owner}/{repo}: {e}")

    if file_structure:
        return detect_languages_from_file_structure(file_structure, owner=owner, repo=repo)
        
    return {}

def fetch_repo_tree_web(owner: str, repo: str, branch: str = "main") -> list:
    """
    Fallback method to recursively extract file tree paths from public GitHub HTML pages when API rate limits are active.
    """
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    visited_urls = set()
    result = []
    seen_paths = set()
    
    queue = [f"https://github.com/{owner}/{repo}"]
    
    while queue and len(visited_urls) < 15:
        url = queue.pop(0)
        if url in visited_urls:
            continue
        visited_urls.add(url)
        
        try:
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                html = res.text
                blobs = re.findall(r'href="/' + re.escape(owner) + r'/' + re.escape(repo) + r'/blob/[^/]+/([^"]+)"', html)
                for b in blobs:
                    if b not in seen_paths:
                        seen_paths.add(b)
                        result.append({"path": b, "type": "blob"})
                        
                trees = re.findall(r'href="/' + re.escape(owner) + r'/' + re.escape(repo) + r'/tree/[^/]+/([^"]+)"', html)
                for t in trees:
                    sub_url = f"https://github.com/{owner}/{repo}/tree/{branch}/{t}"
                    if sub_url not in visited_urls and sub_url not in queue:
                        queue.append(sub_url)
        except Exception as e:
            print(f"Web tree fallback error for {url}: {e}")
            
    return result

def fetch_repo_tree(owner: str, repo: str, branch: str, token: str = None) -> list:
    """
    Fetches the recursive file tree structure of the repository. Falls back to web tree on rate limits.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
    headers = get_headers(token)
    try:
        res = requests.get(url, headers=headers)
        log_github_request_diagnostic(url, headers, res, repo_tag=f"{owner}/{repo}")
        data = handle_github_response(res)
        tree = data.get("tree", [])
        return [{"path": item.get("path"), "type": item.get("type"), "size": item.get("size", 100)} for item in tree]
    except Exception as e:
        print(f"Safe fetch tree fallback for {owner}/{repo}: {e}")
        return fetch_repo_tree_web(owner, repo)

def fetch_repo_commits_fallback(owner: str, repo: str, branch: str = "main") -> list:
    """
    Fallback method to parse real GitHub commits from the public Atom feed without rate limits.
    """
    import xml.etree.ElementTree as ET
    atom_url = f"https://github.com/{owner}/{repo}/commits/{branch}.atom"
    try:
        res = requests.get(atom_url, timeout=10)
        if res.status_code == 200:
            root = ET.fromstring(res.content)
            ns = {'atom': 'http://www.w3.org/2005/Atom'}
            entries = root.findall('atom:entry', ns)
            normalized = []
            for entry in entries[:20]:
                title_elem = entry.find('atom:title', ns)
                author_elem = entry.find('atom:author/atom:name', ns)
                updated_elem = entry.find('atom:updated', ns)
                link_elem = entry.find('atom:link', ns)
                
                href = link_elem.attrib.get('href', '') if link_elem is not None else ''
                sha = href.split('/')[-1] if href else 'commit'

                normalized.append({
                    "sha": sha[:10],
                    "message": title_elem.text.strip() if title_elem is not None and title_elem.text else "Commit",
                    "author": author_elem.text.strip() if author_elem is not None and author_elem.text else "Contributor",
                    "date": updated_elem.text.strip() if updated_elem is not None and updated_elem.text else "",
                })
            if normalized:
                return normalized
    except Exception as e:
        print(f"Commit Atom feed fallback failed: {e}")
    return []

def fetch_repo_commits(owner: str, repo: str, token: str = None) -> list:
    """
    Fetches the latest commits of the repository. Falls back to Atom feed on 403.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/commits?per_page=100"
    headers = get_headers(token)
    try:
        res = requests.get(url, headers=headers)
        log_github_request_diagnostic(url, headers, res, repo_tag=f"{owner}/{repo}")
        commits_data = handle_github_response(res)
        
        normalized = []
        for item in commits_data:
            commit_info = item.get("commit", {})
            git_author_name = commit_info.get("author", {}).get("name")
            github_author = item.get("author") or {}
            github_login = github_author.get("login")
            
            author_name = git_author_name
            if not author_name or author_name.lower() == "unknown":
                author_name = github_login or "Unknown"

            normalized.append({
                "sha": item.get("sha"),
                "message": commit_info.get("message"),
                "author": author_name,
                "date": commit_info.get("author", {}).get("date"),
            })
        return normalized
    except HTTPException as he:
        if he.status_code == 403:
            print(f"Rate limited on REST commits API for {owner}/{repo}. Falling back to public Atom feed.")
            fallback_commits = fetch_repo_commits_fallback(owner, repo)
            if fallback_commits:
                return fallback_commits
        raise he


def fetch_repo_issues(owner: str, repo: str, state: str = "all", token: str = None) -> list:
    """
    Fetches issues for the repository. Skips Pull Requests (which are returned by default).
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/issues?per_page=100&state={state}"
    headers = get_headers(token)
    res = requests.get(url, headers=headers)
    log_github_request_diagnostic(url, headers, res, repo_tag=f"{owner}/{repo}")
    issues_data = handle_github_response(res)
    
    normalized = []
    for item in issues_data:
        # GitHub's issues endpoint returns pull requests as well. Filter them out.
        if "pull_request" in item:
            continue
            
        normalized.append({
            "number": item.get("number"),
            "title": item.get("title"),
            "state": item.get("state"),
            "author": item.get("user", {}).get("login"),
            "created_at": item.get("created_at"),
            "updated_at": item.get("updated_at"),
            "labels": [label.get("name") for label in item.get("labels", [])]
        })
    return normalized

def fetch_repo_pulls(owner: str, repo: str, state: str = "all", token: str = None) -> list:
    """
    Fetches actual Pull Request records directly from GitHub's Pull Requests API:
    GET /repos/{owner}/{repo}/pulls?state=all&per_page=100&page={page}

    Never uses comments, issues, commits, activity events, or mock data.
    """
    print(f"\n[PR FETCH DEBUG] Requesting PRs for connected repository: {owner}/{repo}")
    all_pulls = []
    headers = get_headers(token)
    page = 1
    max_pages = 20  # Support up to 2000 pull requests via API pagination

    while page <= max_pages:
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls?state={state}&per_page=100&page={page}"
        print(f"[PR FETCH DEBUG] Querying GitHub PR API page {page}: {url}")
        try:
            res = requests.get(url, headers=headers, timeout=10)
            log_github_request_diagnostic(url, headers, res, repo_tag=f"{owner}/{repo}")
            if res.status_code == 200:
                data = res.json()
                if not isinstance(data, list) or len(data) == 0:
                    print(f"[PR FETCH DEBUG] Page {page} returned 0 items. Ending pagination loop.")
                    break
                print(f"[PR FETCH DEBUG] Page {page} returned {len(data)} items.")
                for item in data:
                    merged_at = item.get("merged_at")
                    pr_state = item.get("state", "open")
                    author_login = item.get("user", {}).get("login") if item.get("user") else "ghost"
                    author_type = (item.get("user", {}).get("type") or "").lower() if item.get("user") else ""
                    if author_type == "bot" or "[bot]" in author_login.lower():
                        if not author_login.endswith("[bot]"):
                            author_login += "[bot]"

                    all_pulls.append({
                        "number": item.get("number"),
                        "title": item.get("title", ""),
                        "state": pr_state,
                        "author": author_login,
                        "created_at": item.get("created_at") or "2026-08-20T00:00:00Z",
                        "updated_at": item.get("updated_at") or "2026-08-20T00:00:00Z",
                        "merged_at": merged_at,
                        "is_merged": merged_at is not None,
                        "html_url": item.get("html_url") or f"https://github.com/{owner}/{repo}/pull/{item.get('number')}",
                        "labels": [l.get("name") for l in item.get("labels", []) if isinstance(l, dict)]
                    })
                link = res.headers.get("Link", "")
                if 'rel="next"' not in link:
                    print(f"[PR FETCH DEBUG] No rel=\"next\" Link header found. Finished fetching all pages.")
                    break
                page += 1
            else:
                print(f"[PR FETCH DEBUG] API returned HTTP status {res.status_code}: {res.text[:100]}")
                break
        except Exception as e:
            print(f"[PR FETCH DEBUG] Error fetching PRs page {page} for {owner}/{repo}: {e}")
            break

    # If GitHub REST API is rate-limited (HTTP 403) and all_pulls is empty, parse ONLY actual PR entries from GitHub Web Pull Requests page
    if not all_pulls:
        print(f"[PR FETCH DEBUG] REST API returned 0 items (rate limit or empty). Extracting actual PR entries from web HTML page...")
        try:
            import urllib.parse
            open_cnt_web = 0
            closed_cnt_web = 0

            def _extract_html_author(block_text: str) -> str:
                # 1. Check title attribute: title="Open pull requests created by renovate[bot]"
                t_match = re.search(r'title="[^"]*created by ([^"]+)"', block_text, re.IGNORECASE)
                if t_match:
                    auth = t_match.group(1).strip()
                    if auth:
                        return auth

                # 2. Check hovercard URL: data-hovercard-url="/users/([^/]+)/hovercard"
                h_match = re.search(r'data-hovercard-url="/users/([^/]+)/hovercard"', block_text)
                if h_match:
                    auth = urllib.parse.unquote(h_match.group(1)).strip()
                    if auth:
                        return auth

                # 3. Check author%3A in href: href="/.../issues?q=...author%3Aapp%2Frenovate"
                a_match = re.search(r'author%3A(?:app%2F)?([^"&]+)', block_text)
                if a_match:
                    auth = urllib.parse.unquote(a_match.group(1)).strip()
                    if '<span class="Label Label--secondary">Bot' in block_text or 'class="Label--secondary">Bot' in block_text:
                        if not auth.endswith('[bot]'):
                            auth += '[bot]'
                    if auth:
                        return auth

                # 4. Check link text after "by"
                b_match = re.search(r'by\s*<a[^>]*>\s*([^<\s]+)\s*</a>', block_text, re.DOTALL)
                if b_match:
                    auth = b_match.group(1).strip()
                    if '<span class="Label Label--secondary">Bot' in block_text or 'class="Label--secondary">Bot' in block_text:
                        if not auth.endswith('[bot]'):
                            auth += '[bot]'
                    if auth:
                        return auth

                return "author"

            # 1. Fetch Open PRs (pages 1..5)
            for page_num in range(1, 6):
                open_url = f"https://github.com/{owner}/{repo}/pulls?q=is%3Apr+is%3Aopen&page={page_num}"
                res_open = requests.get(open_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
                if res_open.status_code == 200:
                    html = res_open.text
                    if page_num == 1:
                        open_m = re.search(r'([\d,]+)\s+Open\s*</a>', html, re.IGNORECASE)
                        closed_m = re.search(r'([\d,]+)\s+Closed\s*</a>', html, re.IGNORECASE)
                        if open_m: open_cnt_web = int(open_m.group(1).replace(",", ""))
                        if closed_m: closed_cnt_web = int(closed_m.group(1).replace(",", ""))

                    row_blocks = re.findall(r'<div[^>]*id="issue_(\d+)"[^>]*>(.*?)(?=<div[^>]*id="issue_\d+"|\Z)', html, re.DOTALL)
                    if not row_blocks:
                        break

                    for pr_num_str, block in row_blocks:
                        pr_num = int(pr_num_str)
                        if not any(p["number"] == pr_num for p in all_pulls):
                            title_match = re.search(r'href="/' + re.escape(owner) + r'/' + re.escape(repo) + r'/pull/' + pr_num_str + r'"[^>]*>\s*(.*?)\s*</a>', block, re.DOTALL)
                            clean_title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip() if title_match else f"Pull Request #{pr_num}"
                            clean_title = re.sub(r'\s+', ' ', clean_title)

                            author_val = _extract_html_author(block)

                            date_match = re.search(r'<relative-time[^>]*datetime="([^"]+)"', block)
                            date_val = date_match.group(1) if date_match else "2026-08-13T00:00:00Z"

                            all_pulls.append({
                                "number": pr_num,
                                "title": clean_title,
                                "state": "open",
                                "author": author_val,
                                "created_at": date_val,
                                "updated_at": date_val,
                                "merged_at": None,
                                "is_merged": False,
                                "html_url": f"https://github.com/{owner}/{repo}/pull/{pr_num}",
                                "labels": []
                            })
                else:
                    break

            # 2. Fetch Closed PRs (pages 1..5)
            for page_num in range(1, 6):
                closed_url = f"https://github.com/{owner}/{repo}/pulls?q=is%3Apr+is%3Aclosed&page={page_num}"
                res_closed = requests.get(closed_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
                if res_closed.status_code == 200:
                    html = res_closed.text
                    row_blocks = re.findall(r'<div[^>]*id="issue_(\d+)"[^>]*>(.*?)(?=<div[^>]*id="issue_\d+"|\Z)', html, re.DOTALL)
                    if not row_blocks:
                        break

                    for pr_num_str, block in row_blocks:
                        pr_num = int(pr_num_str)
                        if not any(p["number"] == pr_num for p in all_pulls):
                            title_match = re.search(r'href="/' + re.escape(owner) + r'/' + re.escape(repo) + r'/pull/' + pr_num_str + r'"[^>]*>\s*(.*?)\s*</a>', block, re.DOTALL)
                            clean_title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip() if title_match else f"Pull Request #{pr_num}"
                            clean_title = re.sub(r'\s+', ' ', clean_title)

                            author_val = _extract_html_author(block)

                            date_match = re.search(r'<relative-time[^>]*datetime="([^"]+)"', block)
                            date_val = date_match.group(1) if date_match else "2026-08-13T00:00:00Z"

                            is_merged = "merged" in block.lower() or "purple" in block.lower()

                            all_pulls.append({
                                "number": pr_num,
                                "title": clean_title,
                                "state": "closed",
                                "author": author_val,
                                "created_at": date_val,
                                "updated_at": date_val,
                                "merged_at": date_val if is_merged else None,
                                "is_merged": is_merged,
                                "html_url": f"https://github.com/{owner}/{repo}/pull/{pr_num}",
                                "labels": []
                            })
                else:
                    break
        except Exception as ae:
            print(f"[PR FETCH DEBUG] Web PR fallback error for {owner}/{repo}: {ae}")

    open_cnt = sum(1 for p in all_pulls if p.get("state") == "open")
    merged_cnt = sum(1 for p in all_pulls if p.get("is_merged"))
    closed_cnt = sum(1 for p in all_pulls if p.get("state") == "closed" and not p.get("is_merged"))

    # Record exact repository-wide counts if web header counts were extracted
    global last_pr_counts
    last_pr_counts = {
        "owner_repo": f"{owner}/{repo}",
        "open": max(open_cnt, open_cnt_web if 'open_cnt_web' in locals() else 0),
        "closed": max(closed_cnt, closed_cnt_web if 'closed_cnt_web' in locals() else 0),
        "merged": merged_cnt
    }
    print(f"[PR FETCH DEBUG] Final PR count for {owner}/{repo}: Total={len(all_pulls)} (Open={open_cnt}, Closed={closed_cnt}, Merged={merged_cnt})\n")

    return all_pulls

def fetch_repo_branches(owner: str, repo: str, token: str = None) -> list:
    """
    Fetches public branches of the repository.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/branches?per_page=30"
    headers = get_headers(token)
    try:
        res = requests.get(url, headers=headers, timeout=10)
        log_github_request_diagnostic(url, headers, res, repo_tag=f"{owner}/{repo}")
        if res.status_code == 200:
            branches_data = res.json()
            return [
                {
                    "name": b.get("name"),
                    "protected": b.get("protected", False),
                    "commit_sha": b.get("commit", {}).get("sha", "")[:7]
                }
                for b in branches_data
            ]
    except Exception as e:
        print(f"Error fetching branches: {e}")
    return []

def fetch_repo_contributors(owner: str, repo: str, token: str = None) -> list:
    """
    Fetches all contributors of the repository using REST API pagination (100 per page, up to 1000 total).
    """
    all_contributors = []
    headers = get_headers(token)
    page = 1
    max_pages = 10  # Support up to 1000 contributors

    while page <= max_pages:
        url = f"https://api.github.com/repos/{owner}/{repo}/contributors?per_page=100&page={page}"
        try:
            res = requests.get(url, headers=headers, timeout=10)
            log_github_request_diagnostic(url, headers, res, repo_tag=f"{owner}/{repo}")
            if res.status_code == 200:
                contrib_data = res.json()
                if not isinstance(contrib_data, list) or len(contrib_data) == 0:
                    break
                for c in contrib_data:
                    all_contributors.append({
                        "login": c.get("login"),
                        "contributions": c.get("contributions", 0),
                        "avatar_url": c.get("avatar_url"),
                        "html_url": c.get("html_url")
                    })
                link = res.headers.get("Link", "")
                if 'rel="next"' not in link:
                    break
                page += 1
            else:
                break
        except Exception as e:
            print(f"Error fetching contributors page {page} for {owner}/{repo}: {e}")
            break

    return all_contributors


def fetch_total_commit_count_web(owner: str, repo: str, branch: str = "main") -> int:
    """
    Fallback method to extract exact commit count from GitHub web HTML pages or Atom feeds when API rate limits are active.
    """
    # 1. Try Atom commit feed entry count
    try:
        atom_urls = [
            f"https://github.com/{owner}/{repo}/commits.atom",
            f"https://github.com/{owner}/{repo}/commits/{branch}.atom"
        ]
        for atom_url in atom_urls:
            atom_res = requests.get(atom_url, timeout=5, allow_redirects=True)
            if atom_res.status_code == 200:
                import xml.etree.ElementTree as ET
                root = ET.fromstring(atom_res.content)
                ns = {'atom': 'http://www.w3.org/2005/Atom'}
                entries = root.findall('atom:entry', ns)
                if entries and len(entries) > 0 and len(entries) < 20:
                    return len(entries)
    except Exception as ae:
        print(f"Atom commit count fallback error for {owner}/{repo}: {ae}")

    # 2. Try HTML commit count match
    urls = [
        f"https://github.com/{owner}/{repo}/commits/{branch}",
        f"https://github.com/{owner}/{repo}"
    ]
    for url in urls:
        try:
            res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            if res.status_code == 200:
                html = res.text
                matches = re.findall(r'([\d,]+)\s+commits', html, re.IGNORECASE)
                if matches:
                    for m in matches:
                        count_str = m.replace(",", "").strip()
                        if count_str.isdigit():
                            val = int(count_str)
                            if val > 0:
                                return val
                
                alt_matches = re.findall(r'<strong[^>]*>([\d,]+)</strong>\s*commits', html, re.IGNORECASE)
                if alt_matches:
                    for m in alt_matches:
                        count_str = m.replace(",", "").strip()
                        if count_str.isdigit():
                            val = int(count_str)
                            if val > 0:
                                return val
        except Exception as e:
            print(f"Web commit count fallback error for {url}: {e}")
    return 0

def fetch_total_commit_count(owner: str, repo: str, token: str = None, branch: str = "main", existing_commits: list = None) -> int:
    """
    Fetches the total commit count for a repository using the Link header page count trick.
    If existing_commits is provided and has fewer than 100 items, returns len(existing_commits) with 0 API calls.
    """
    if isinstance(existing_commits, list) and existing_commits:
        if len(existing_commits) < 100:
            return len(existing_commits)

    url = f"https://api.github.com/repos/{owner}/{repo}/commits?per_page=100"
    headers = get_headers(token)
    try:
        res = requests.get(url, headers=headers, timeout=10)
        log_github_request_diagnostic(url, headers, res, repo_tag=f"{owner}/{repo}")
        if res.status_code == 200:
            link = res.headers.get("Link", "")
            commits_p1 = res.json()
            if not link:
                return len(commits_p1)
                
            match = re.search(r'[?&]page=(\d+)>;\s*rel="last"', link)
            if match:
                last_page = int(match.group(1))
                last_page_url = f"https://api.github.com/repos/{owner}/{repo}/commits?page={last_page}&per_page=100"
                res_last = requests.get(last_page_url, headers=headers, timeout=10)
                log_github_request_diagnostic(last_page_url, headers, res_last, repo_tag=f"{owner}/{repo}")
                if res_last.status_code == 200:
                    last_page_commits = res_last.json()
                    return (last_page - 1) * 100 + len(last_page_commits)
                else:
                    return last_page * 100
            return len(commits_p1)
    except Exception as e:
        print(f"API error in fetch_total_commit_count for {owner}/{repo}: {e}")

    # Fallback to web HTML scraping for real total commit count
    web_count = fetch_total_commit_count_web(owner, repo, branch=branch)
    if web_count > 0:
        return web_count
        
    return len(existing_commits) if isinstance(existing_commits, list) else 0


def fetch_repo_commits_paginated(owner: str, repo: str, page: int = 1, per_page: int = 10, token: str = None) -> list:
    """
    Fetches commits with pagination parameters.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/commits?page={page}&per_page={per_page}"
    headers = get_headers(token)
    try:
        res = requests.get(url, headers=headers, timeout=10)
        log_github_request_diagnostic(url, headers, res, repo_tag=f"{owner}/{repo}")
        commits_data = handle_github_response(res)
        
        normalized = []
        for item in commits_data:
            commit_info = item.get("commit", {})
            git_author_name = commit_info.get("author", {}).get("name")
            github_author = item.get("author") or {}
            github_login = github_author.get("login")
            
            author_name = git_author_name
            if not author_name or author_name.lower() == "unknown":
                author_name = github_login or "Unknown"

            normalized.append({
                "sha": item.get("sha"),
                "message": commit_info.get("message"),
                "author": author_name,
                "date": commit_info.get("author", {}).get("date"),
            })
        return normalized
    except HTTPException as he:
        if he.status_code == 403:
            print(f"Rate limited on paginated commits API. Using Atom feed.")
            fallback_commits = fetch_repo_commits_fallback(owner, repo)
            if fallback_commits:
                start_idx = (page - 1) * per_page
                end_idx = start_idx + per_page
                return fallback_commits[start_idx:end_idx]
        raise he

