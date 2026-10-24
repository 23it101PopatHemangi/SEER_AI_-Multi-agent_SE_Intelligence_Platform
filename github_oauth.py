import os
import urllib.parse
import requests
from fastapi import APIRouter, Depends, HTTPException, status, Query, Header
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from database import get_db, UserToken

router = APIRouter(prefix="/api/github", tags=["GitHub OAuth"])

def get_credentials():
    client_id = os.getenv("GITHUB_CLIENT_ID", "").strip()
    client_secret = os.getenv("GITHUB_CLIENT_SECRET", "").strip()
    redirect_uri = os.getenv("GITHUB_REDIRECT_URI", "http://localhost:8000/api/github/callback").strip()
    return client_id, client_secret, redirect_uri

def check_credentials():
    client_id, client_secret, _ = get_credentials()
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GitHub Client credentials are not configured on the server. Please define GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET in backend/.env"
        )

@router.get("/auth-url")
def get_auth_url(
    user_email: str = Query(...),
    project_id: str = Query(...)
):
    """
    Generates the GitHub OAuth authorization redirect URL.
    A unique nonce is appended to state so GitHub treats each request as fresh.
    """
    check_credentials()
    client_id, _, redirect_uri = get_credentials()
    
    import secrets
    nonce = secrets.token_hex(8)
    
    # State encodes user_email, project_id, and a nonce for uniqueness
    state = f"{user_email}:{project_id}:{nonce}"
    encoded_state = urllib.parse.quote(state)
    encoded_redirect = urllib.parse.quote(redirect_uri)
    
    # Build the authorization URL.
    auth_url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={client_id}"
        f"&redirect_uri={encoded_redirect}"
        f"&scope=repo"
        f"&state={encoded_state}"
    )
    return {"auth_url": auth_url}

@router.get("/callback")
def oauth_callback(
    code: str = Query(None),
    state: str = Query(None),
    error: str = Query(None),
    error_description: str = Query(None),
    db: Session = Depends(get_db)
):
    """
    Callback endpoint that GitHub redirects to after authorization.
    Exchanges code for access token, saves it, and redirects to frontend project page.
    """
    # 1. Handle GitHub authorization errors
    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"GitHub OAuth error: {error_description or error}"
        )
    
    if not code or not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authorization code or state parameter is missing."
        )

    # 2. Parse state parameters (format: user_email:project_id:nonce)
    try:
        parts = state.split(":")
        if len(parts) < 2:
            raise ValueError("Too few parts")
        user_email = parts[0]
        project_id = parts[1]
        # nonce (parts[2]) is discarded — it was only used to make the URL unique
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid state parameter structure."
        )

    check_credentials()
    client_id, client_secret, redirect_uri = get_credentials()

    # 3. Exchange code for access token
    token_url = "https://github.com/login/oauth/access_token"
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri
    }
    headers = {"Accept": "application/json"}
    
    try:
        res = requests.post(token_url, json=payload, headers=headers, timeout=10)
        res_data = res.json()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to communicate with GitHub token service: {str(e)}"
        )

    access_token = res_data.get("access_token")
    if not access_token:
        error_msg = res_data.get("error_description") or res_data.get("error") or "Unknown token exchange failure"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Token exchange failed: {error_msg}"
        )

    # 4. Fetch GitHub user profile details
    user_url = "https://api.github.com/user"
    user_headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    
    try:
        user_res = requests.get(user_url, headers=user_headers, timeout=10)
        if user_res.status_code != 200:
            raise Exception("GitHub user API rejected token")
        user_data = user_res.json()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch GitHub profile with token: {str(e)}"
        )

    github_username = user_data.get("login")
    if not github_username:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="GitHub profile does not contain login credentials"
        )

    # 5. Store / Update user access token in the Database
    db_token = db.query(UserToken).filter(UserToken.user_email == user_email).first()
    if db_token:
        db_token.github_access_token = access_token
        db_token.github_username = github_username
    else:
        db_token = UserToken(
            user_email=user_email,
            github_access_token=access_token,
            github_username=github_username
        )
        db.add(db_token)
        
    db.commit()

    # 6. Redirect the browser back to the frontend repositories panel
    frontend_url = f"http://localhost:5173/projects/{project_id}/repositories?github_connected=true"
    return RedirectResponse(url=frontend_url)

@router.get("/status")
def get_connection_status(
    user_email: str = Query(None),
    x_user_email: str = Header(None, alias="X-User-Email"),
    db: Session = Depends(get_db)
):
    """
    Checks if a user email is connected to GitHub. If so, fetches their GitHub repository list.
    """
    email = user_email or x_user_email
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User email is required in query params or X-User-Email header."
        )

    db_token = db.query(UserToken).filter(UserToken.user_email == email).first()
    if not db_token:
        return {"connected": False}

    # Fetch user repositories from GitHub
    repo_url = "https://api.github.com/user/repos?per_page=100&sort=updated"
    headers = {
        "Authorization": f"Bearer {db_token.github_access_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }

    try:
        res = requests.get(repo_url, headers=headers, timeout=10)
        
        # Self-healing: if the token was revoked or is invalid, delete it from the DB
        if res.status_code in [401, 403]:
            db.delete(db_token)
            db.commit()
            return {"connected": False}
            
        if res.status_code != 200:
            return {"connected": True, "github_username": db_token.github_username, "repositories": []}
            
        raw_repos = res.json()
        
        # Filter and normalize repository details
        repositories = []
        for r in raw_repos:
            repositories.append({
                "name": r.get("name"),
                "full_name": r.get("full_name"),
                "html_url": r.get("html_url"),
                "description": r.get("description") or ""
            })
            
        return {
            "connected": True,
            "github_username": db_token.github_username,
            "repositories": repositories
        }
    except Exception as e:
        print(f"Error fetching repos for status check: {e}")
        return {
            "connected": True,
            "github_username": db_token.github_username,
            "repositories": []
        }

@router.post("/disconnect")
def disconnect_github(
    user_email: str = Query(None),
    x_user_email: str = Header(None, alias="X-User-Email"),
    db: Session = Depends(get_db)
):
    """
    Fully revokes the GitHub OAuth token at GitHub's API level,
    then deletes it from the local database.
    This ensures the user MUST re-authorize through GitHub's consent screen on reconnect.
    """
    email = user_email or x_user_email
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User email is required."
        )

    db_token = db.query(UserToken).filter(UserToken.user_email == email).first()
    if db_token:
        client_id, client_secret, _ = get_credentials()
        if client_id and client_secret and db_token.github_access_token:
            try:
                grant_url = f"https://api.github.com/applications/{client_id}/grant"
                revoke_res = requests.delete(
                    grant_url,
                    auth=(client_id, client_secret),
                    json={"access_token": db_token.github_access_token},
                    headers={"Accept": "application/vnd.github+json"},
                    timeout=10
                )
                print(f"GitHub grant revoke status: {revoke_res.status_code}")
            except Exception as e:
                print(f"Warning: GitHub grant revocation request failed: {e}")

        # Step 2: Always delete from local database
        db.delete(db_token)
        db.commit()

    return {"status": "disconnected"}

