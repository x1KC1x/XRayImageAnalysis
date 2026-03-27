# Python
__pycache__/
*.py[cod]
*$py.class
*.pyo
*.pyd
.Python
env/
venv/
.env
.venv
pip-log.txt
pip-delete-this-directory.txt
*.egg-info/
dist/
build/
*.egg

# Jupyter Notebooks
.ipynb_checkpoints
*.ipynb

# Node.js
node_modules/
npm-debug.log*
yarn-debug.log*
yarn-error.log*
package-lock.json

# Environment variables - NEVER commit secrets!
.env
.env.local
.env.development
.env.staging
.env.production
*.env

# Database connection strings - NEVER commit!
connection_strings.json
db_config.json
secrets.json
appsettings.json
appsettings.*.json

# Azure credentials - NEVER commit!
*.publishsettings
azure.json
azureauth.json

# API Keys - NEVER commit!
api_keys.txt
credentials.json

# Data files - store in Azure Blob, not GitHub
data/raw/*
data/processed/*
data/annotations/*
*.pdf
*.dcm
*.png
*.jpg
*.jpeg
*.tiff
*.bmp

# Keep folder structure but ignore contents
!data/raw/.gitkeep
!data/processed/.gitkeep
!data/annotations/.gitkeep

# Models - store separately, not in GitHub
models/*.pkl
models/*.h5
models/*.pt
models/*.pth
models/*.onnx

# IDE and editor files
.vscode/
.idea/
*.suo
*.user
*.userosscache
*.sln.docstates
*.swp
*.swo
*~

# OS files
.DS_Store
Thumbs.db
desktop.ini

# Logs
logs/
*.log
*.logs

# Test coverage
.coverage
htmlcov/
.pytest_cache/
coverage.xml

# Distribution
dist/
build/
*.spec
