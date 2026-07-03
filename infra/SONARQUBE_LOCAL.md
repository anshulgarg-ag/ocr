# Local SonarQube Setup

This project includes SonarQube for local code quality analysis. It's automatically started as part of the Docker Compose stack.

## Starting SonarQube

SonarQube runs in Docker Compose alongside other services:

```bash
docker-compose up sonarqube
```

Or start the full stack including SonarQube:

```bash
docker-compose up
```

SonarQube will be available at: **http://localhost:9000**

## Initial Setup

1. Access http://localhost:9000
2. Default login: `admin` / `admin`
3. Change the password on first login
4. Create a new project or use the automatically detected one

## Running Code Analysis Locally

Install the SonarQube Scanner CLI:

```bash
pip install pylint
# or for better SonarQube integration:
npm install -g sonar-scanner
```

Run analysis from the project root:

```bash
sonar-scanner \
  -Dsonar.projectKey=ocr-pipeline \
  -Dsonar.sources=pipeline,config,query_api \
  -Dsonar.tests=tests \
  -Dsonar.host.url=http://localhost:9000 \
  -Dsonar.login=admin \
  -Dsonar.password=<your-admin-password>
```

Or using Python analysis (pytest + coverage):

```bash
pytest tests/unit/ \
  --cov=pipeline \
  --cov=config \
  --cov-report=xml

sonar-scanner \
  -Dsonar.projectKey=ocr-pipeline \
  -Dsonar.sources=pipeline,config,query_api \
  -Dsonar.python.coverage.reportPaths=coverage.xml \
  -Dsonar.host.url=http://localhost:9000
```

## GitHub Actions Integration (Optional)

For CI/CD integration, the `.github/workflows/sonarqube.yml` workflow:
- Only runs if `SONAR_TOKEN` and `SONAR_HOST_URL` secrets are configured
- Requires a remote SonarQube instance (not the local Docker version)
- Set up by adding GitHub secrets pointing to your SonarQube server

## Troubleshooting

**SonarQube won't start:**
- Check PostgreSQL is healthy: `docker-compose ps postgres`
- Check logs: `docker-compose logs sonarqube`

**Can't connect to http://localhost:9000:**
- Wait 30-60 seconds for SonarQube to fully initialize
- Check port isn't in use: `lsof -i :9000` (Linux/Mac)

**Database issues:**
- Reset SonarQube data: `docker-compose down -v sonarqube_data`
- Restart: `docker-compose up sonarqube`
