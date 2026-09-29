# Veraud

## Requirements
- [pnpm](https://github.com/pnpm/pnpm)
- [fnm](https://github.com/Schniz/fnm)
- [uv](https://github.com/astral-sh/uv)

#### Troubleshooting
- If you have any issues with fnm, follow the [shell setup guide](https://github.com/Schniz/fnm#shell-setup)

## Preparation
**Windows only**: Run `scripts/setup_dev_env.ps1` from the project root to install the required Node.js and Python versions and download all dependencies.

Once the setup is complete, you can start the services:
#### Frontend
```bash
cd frontend
pnpm run dev
```

#### Backend
```bash
cd backend
pnpm run dev
```

#### Agent server
```bash
cd agent-server
uv run dev
```