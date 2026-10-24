# SEER AI — Multi-Agent Software Engineering Intelligence Platform

SEER AI is an AI-powered software engineering intelligence platform designed to help development teams analyze code repositories, understand software architecture, manage project backlogs, identify risks, and generate software documentation and Jira user stories.

The platform brings repository analysis, project management integrations, and AI-powered insights together in a centralized workspace.

## ✨ Features

- **Project Management:** Create, organize, and manage software projects.
- **GitHub Integration:** Connect GitHub repositories and analyze codebases.
- **Repository Analysis:** Explore repository structures and software components.
- **Architecture Visualization:** Visualize and understand software architecture.
- **Jira Integration:** Connect Jira and access project-related information.
- **Backlog Management:** View and manage project backlog items.
- **Jira Timeline:** Explore project activities and timeline information.
- **AI Insights:** Generate AI-assisted insights for software engineering workflows.
- **Risk Analysis:** Analyze potential project and software risks.
- **SRS Generation:** Generate Software Requirements Specification documents.
- **Jira Story Generation:** Assist with creating Jira story drafts from project requirements.
- **Authentication:** Secure application routes using Okta authentication.
- **Responsive UI:** Access the platform through a consistent, responsive interface.

## 🛠️ Technology Stack

### Frontend
- React
- TypeScript
- Vite
- Tailwind CSS
- React Router
- Lucide React
- Okta React
- Okta Auth JS

### Backend
- Python
- FastAPI
- Uvicorn
- REST APIs

### Integrations and AI
- GitHub API
- Jira API
- Okta authentication
- Google Gemini or the configured AI provider

### Development Tools
- Git and GitHub
- Visual Studio Code
- npm
- Python virtual environments

## 📁 Project Structure

```text
SEER_AI/
├── backend/
│   ├── main.py
│   ├── database.py
│   ├── schemas.py
│   ├── github_oauth.py
│   ├── github_service.py
│   ├── repo_analyzer.py
│   ├── jira_oauth.py
│   ├── jira_service.py
│   ├── insights.py
│   ├── risk_analysis.py
│   ├── srs_documents.py
│   └── jira_story_drafts.py
│
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── context/
│   │   ├── services/
│   │   ├── App.tsx
│   │   ├── main.tsx
│   │   └── index.css
│   ├── package.json
│   └── index.html
│
├── .gitignore
└── README.md
```

*This is a representative structure; the actual files may vary as the project evolves.*

## ⚙️ Prerequisites

Before running the project, ensure you have installed:

- [Python](https://www.python.org/downloads/)
- [Node.js and npm](https://nodejs.org/)
- [Git](https://git-scm.com/downloads)
- A code editor such as Visual Studio Code

You may also need credentials for GitHub, Jira, Okta, and the configured AI provider.

## 🚀 Getting Started

### 1. Clone the Repository

```bash
git clone https://github.com/23it101PopatHemangi/SEER_AI_-Multi-agent_SE_Intelligence_Platform.git
cd SEER_AI_-Multi-agent_SE_Intelligence_Platform
```

### 2. Run the Backend

Open a terminal in the project root and navigate to the backend directory:

```powershell
cd backend
```

#### Activate the virtual environment

If the `.venv` folder already exists:

```powershell
.\.venv\Scripts\Activate.ps1
```

If the `.venv` folder does not exist, create and activate it:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

#### Install dependencies

With the virtual environment activated:

```powershell
pip install -r requirements.txt
```

If activation fails but the `.venv` folder exists, install dependencies directly through its Python executable:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

#### Start the backend server

```powershell
python -m uvicorn main:app --reload --port 8000
```

The backend will be available at:

- **Backend API:** http://localhost:8000
- **API documentation:** http://localhost:8000/docs (if enabled)

Keep this terminal running while using the application.

### 3. Run the Frontend

Open a **second terminal** in the project root.

Navigate to the frontend directory:

```powershell
cd frontend
```

Install frontend dependencies:

```powershell
npm install
```

Start the development server:

```powershell
npm run dev
```

Open the local URL displayed in the terminal, usually:

**http://localhost:5173**

Keep this terminal running as well.

## 🔐 Environment Configuration

The application may require environment variables for:

- Backend API URL
- Okta issuer, client ID, and redirect URI
- GitHub OAuth client ID and secret
- Jira OAuth credentials and callback URL
- AI provider API key
- Database connection settings

Create local `.env` files in the appropriate directories and use the variable names expected by the application.

**Security guidelines:**

- Never commit `.env` files containing credentials.
- Never commit API keys, passwords, OAuth client secrets, access tokens, or database credentials.
- Never expose private credentials through frontend environment variables.
- Ensure `.env` and other secret files are excluded by `.gitignore`.
- Rotate any credentials that may have been exposed in a repository.

## 🔄 Git Workflow

The project uses Git for version control and collaborative development.

Check the current working tree:

```bash
git status
```

Stage only the intended files:

```bash
git add <specific-files>
```

Create a commit:

```bash
git commit -m "type: describe your changes"
```

Synchronize with the remote repository before pushing:

```bash
git pull --rebase origin main
git push origin main
```

Since multiple contributors work on `main`, synchronize regularly and resolve any merge conflicts carefully. Avoid force-pushing shared history.

### Example Commit Messages

```text
feat: implement GitHub repository services
feat: add Jira OAuth integration
feat: implement risk analysis engine
feat: add SRS and Jira story generation
feat: improve responsive layout and UI consistency
docs: update project README
fix: handle repository connection errors
```

## 🧪 Testing and Build

### Frontend build

From the frontend directory:

```powershell
npm run build
```

This runs the build script defined in `frontend/package.json`, if configured.

### Backend tests

From the backend directory, if pytest and project tests are available:

```powershell
python -m pytest
```

Review any test failures before deploying changes.

## 🎯 Project Objectives

SEER AI aims to:

- Reduce manual effort in software project analysis.
- Improve visibility into codebases and software architecture.
- Support project planning and risk assessment.
- Accelerate software documentation and user-story creation.
- Integrate development workflows with GitHub and Jira.
- Provide AI-assisted intelligence for software engineering teams.

## 🔮 Future Enhancements

Potential future improvements include:

- More advanced multi-agent collaboration.
- Deeper code dependency and architecture analysis.
- Improved automated risk detection.
- Enhanced documentation and user-story generation.
- Expanded testing, monitoring, and deployment support.

## 👥 Contributors

Developed collaboratively as a software engineering project.

Add contributor names and GitHub profile links here.

## 📄 License

A license has not yet been specified. Add an appropriate license before distributing or reusing this project publicly.

---

**SEER AI — Turning software project data into actionable engineering intelligence.**
